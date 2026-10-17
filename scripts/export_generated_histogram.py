#!/usr/bin/env python3
"""Export the generated-vector RTL cycle histogram from Verilator logs."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.perf_model import predict_cycles  # noqa: E402
from model.trace import trace_case  # noqa: E402
from model.vector_corpus import load_vector_cases  # noqa: E402

PASS_LINE = re.compile(
    r"PASS verify tc=(\d+) RPC=(\d+) valid=(\d+) cycles=(\d+) perms=(\d+)"
)


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/generated.json")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--bin-width", type=int, default=5000)
    parser.add_argument("--output", type=Path, default=ROOT / "bench/generated_cycle_histogram.csv")
    args = parser.parse_args()
    if args.bin_width < 1:
        parser.error("--bin-width must be positive")

    vectors = load_vector_cases(args.vectors)
    selected = [v for v in vectors if len(v["signature"]) == 7856 * 2
                and len(v["pk"]) == 32 * 2
                and (v["mode"] == "internal" or len(v.get("context", "")) <= 255 * 2)]
    if not selected:
        parser.error("no well-formed verifier vectors found")

    samples: list[tuple[str, int]] = []
    max_model_error = 0.0
    for vector in selected:
        log = ROOT / "build/sim_verify" / f"tc{vector['tcId']}_rpc{args.rpc}" / "run.log"
        match = PASS_LINE.search(log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else None
        if not match:
            parser.error(f"missing PASS cycle record for tc{vector['tcId']}; run test-verify-ext first")
        test_id, rpc, valid, cycles, measured_perms = map(int, match.groups())
        expected = int(vector["testPassed"])
        if test_id != vector["tcId"] or rpc != args.rpc or valid != expected:
            parser.error(f"cycle record disagrees with vector tc{vector['tcId']}")
        records, oracle_result = trace_case(vector)
        if oracle_result != expected:
            parser.error(f"reference result disagrees with vector tc{vector['tcId']}")
        predicted_perms = sum(int(record["perms"]) for record in records
                              if record.get("event") == "hash")
        if predicted_perms != measured_perms:
            parser.error(f"permutation count mismatch for tc{vector['tcId']}")
        predicted = predict_cycles(records, rpc=args.rpc, lane_bytes=1, load_cycles=0,
                                   overlap=False, permute_overhead=0, call_overhead=14)
        max_model_error = max(max_model_error, abs(predicted - cycles) / cycles)
        samples.append(("valid" if expected else "invalid", cycles))

    rtl_files = sorted((ROOT / "rtl").rglob("*.sv"))
    digest = hashlib.sha256()
    for path in rtl_files:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    source_hash = digest.hexdigest()
    simulation_digest = hashlib.sha256()
    for path in (ROOT / "sim/verify/tb_verify.sv", ROOT / "scripts/run_verify_sim.py",
                 ROOT / "scripts/verilator_build.py"):
        simulation_digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        simulation_digest.update(path.read_bytes())
    simulation_hash = simulation_digest.hexdigest()
    model_digest = hashlib.sha256()
    for path in sorted((ROOT / "model").glob("*.py")):
        model_digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        model_digest.update(path.read_bytes())
    model_hash = model_digest.hexdigest()
    if max_model_error > 0.02:
        parser.error(f"cycle model maximum error {max_model_error:.2%} exceeds 2.00%")

    bins: dict[tuple[str, int], int] = {}
    summaries: dict[str, tuple[int, int, float, int, int, float]] = {}
    for result, cycles in samples:
        lower = cycles // args.bin_width * args.bin_width
        bins[(result, lower)] = bins.get((result, lower), 0) + 1
    for result in ("valid", "invalid"):
        values = sorted(cycles for category, cycles in samples if category == result)
        if values:
            p95 = values[(95 * len(values) + 99) // 100 - 1]
            summaries[result] = (len(values), values[0], statistics.median(values),
                                 p95, values[-1], statistics.fmean(values))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("rtl_sha256", "simulation_sha256", "model_sha256", "rpc", "result",
                         "cycles_from", "cycles_to", "count", "sample_count", "min_cycles",
                         "median_cycles", "p95_cycles", "max_cycles", "mean_cycles",
                         "model_max_error_pct"))
        for (result, lower), count in sorted(bins.items(), key=lambda item: (item[0][0], item[0][1])):
            summary = summaries[result]
            writer.writerow((source_hash, simulation_hash, model_hash, args.rpc, result, lower,
                             lower + args.bin_width - 1, count, *summary[:-1],
                             f"{summary[-1]:.2f}", f"{max_model_error * 100:.4f}"))

    print(f"Wrote {len(samples)} RTL samples to {display_path(args.output)}")
    print(f"cycle model: max error {max_model_error:.2%}")
    for result in ("valid", "invalid"):
        values = sorted(cycles for category, cycles in samples if category == result)
        if values:
            median = statistics.median(values)
            p95 = values[(95 * len(values) + 99) // 100 - 1]
            print(f"{result}: n={len(values)} min={values[0]} median={median:g} "
                  f"p95={p95} max={values[-1]} mean={statistics.fmean(values):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
