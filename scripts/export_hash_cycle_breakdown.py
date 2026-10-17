#!/usr/bin/env python3
"""Export per-hash-kind cycle totals and a stacked SVG from verifier logs."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.vector_corpus import load_vector_cases  # noqa: E402
KIND_NAMES = {0: "F", 1: "H", 2: "T_k", 3: "T_len", 4: "H_msg"}
TOTAL_LINE = re.compile(
    r"HASH_TOTAL tc=(\d+) kind=(\d+) calls=(\d+) absorb=(\d+) "
    r"permutation=(\d+) response=(\d+) idle=(\d+)"
)
PASS_LINE = re.compile(
    r"PASS verify tc=(\d+) RPC=(\d+) valid=(\d+) cycles=(\d+) perms=(\d+)"
)


def hash_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def svg_plot(rows: list[dict[str, float | int | str]], path: Path) -> None:
    colors = {
        "absorb": "#3b82f6",
        "permutation": "#f59e0b",
        "response": "#10b981",
        "idle": "#a78bfa",
    }
    categories = list(colors)
    width, height = 920, 480
    left, right, top, bottom = 92, 28, 62, 94
    plot_width, plot_height = width - left - right, height - top - bottom
    max_value = max(sum(float(row[f"mean_{category}"]) for category in categories)
                    for row in rows)
    axis_max = max(1, int((max_value + 999) // 1000) * 1000)
    scale = plot_height / axis_max
    bar_width = min(88, plot_width // max(1, len(rows) * 2))
    gap = (plot_width - bar_width * len(rows)) / (len(rows) + 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="460" y="30" text-anchor="middle" font-family="sans-serif" font-size="20" font-weight="600">Mean cycles per hash call</text>',
        '<text x="460" y="50" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#555">RPC1 · exclusive absorb, permutation, response, and controller gaps</text>',
    ]
    for tick in range(0, axis_max + 1, max(1000, axis_max // 5)):
        y = top + plot_height - tick * scale
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#ddd"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="#444">{tick:,}</text>')
    for index, row in enumerate(rows):
        x = left + gap * (index + 1) + bar_width * index
        y_bottom = top + plot_height
        for category in categories:
            value = float(row[f"mean_{category}"])
            bar_height = value * scale
            y_bottom -= bar_height
            parts.append(f'<rect x="{x:.1f}" y="{y_bottom:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="{colors[category]}"/>')
        label = str(row["kind"])
        parts.append(f'<text x="{x + bar_width/2:.1f}" y="{top + plot_height + 24}" text-anchor="middle" font-family="sans-serif" font-size="12">{label}</text>')
        total = sum(float(row[f"mean_{category}"]) for category in categories)
        parts.append(f'<text x="{x + bar_width/2:.1f}" y="{top + plot_height - total*scale - 7:.1f}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#333">{total:.1f}</text>')
    legend_x = left
    for category in categories:
        parts.append(f'<rect x="{legend_x}" y="{height-31}" width="14" height="14" fill="{colors[category]}"/>')
        parts.append(f'<text x="{legend_x+20}" y="{height-19}" font-family="sans-serif" font-size="12">{category}</text>')
        legend_x += 154
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/generated.json")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "bench/cycle_breakdown.csv")
    parser.add_argument("--plot", type=Path, default=ROOT / "bench/plots/hash_call_cycle_breakdown.svg")
    args = parser.parse_args()

    vectors = load_vector_cases(args.vectors)
    selected = [v for v in vectors if len(v["signature"]) == 7856 * 2
                and len(v["pk"]) == 32 * 2
                and (v["mode"] == "internal" or len(v.get("context", "")) <= 255 * 2)]
    if not selected:
        parser.error("no well-formed verifier vectors found")

    totals = {kind: {key: 0 for key in ("calls", "absorb", "permutation", "response", "idle")}
              for kind in KIND_NAMES}
    for vector in selected:
        log_path = ROOT / "build/sim_verify" / f"tc{vector['tcId']}_rpc{args.rpc}" / "run.log"
        if not log_path.is_file():
            parser.error(f"missing simulation log for tc{vector['tcId']}; run test-verify-ext first")
        local_totals = {kind: {key: 0 for key in ("calls", "absorb", "permutation", "response", "idle")}
                        for kind in KIND_NAMES}
        found: set[int] = set()
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in log_lines:
            match = TOTAL_LINE.search(line)
            if not match:
                continue
            test_id, kind, calls, absorb, permutation, response, idle = map(int, match.groups())
            if test_id != vector["tcId"] or kind not in KIND_NAMES or kind in found:
                parser.error(f"invalid hash-call summary in tc{vector['tcId']} log")
            found.add(kind)
            for key, value in zip(local_totals[kind], (calls, absorb, permutation, response, idle)):
                local_totals[kind][key] = value
        if found != set(KIND_NAMES):
            parser.error(f"missing hash kinds for tc{vector['tcId']}: {sorted(set(KIND_NAMES) - found)}")
        pass_match = next((PASS_LINE.search(line) for line in log_lines if PASS_LINE.search(line)), None)
        if not pass_match:
            parser.error(f"missing PASS cycle record for tc{vector['tcId']}")
        test_id, rpc, valid, cycles, permutations = map(int, pass_match.groups())
        if (test_id != vector["tcId"] or rpc != args.rpc
                or valid != int(vector["testPassed"])):
            parser.error(f"PASS record disagrees with vector tc{vector['tcId']}")
        accounted_cycles = sum(sum(local_totals[kind][key]
                                   for key in ("absorb", "permutation", "response", "idle"))
                               for kind in KIND_NAMES)
        measured_permutation_cycles = sum(local_totals[kind]["permutation"] for kind in KIND_NAMES)
        if accounted_cycles != cycles:
            parser.error(f"hash-cycle ledger for tc{test_id} sums to {accounted_cycles}, expected {cycles}")
        if measured_permutation_cycles != permutations * (24 // args.rpc):
            parser.error(f"permutation ledger mismatch for tc{test_id}")
        for kind in KIND_NAMES:
            for key in totals[kind]:
                totals[kind][key] += local_totals[kind][key]

    rtl_hash = hash_paths(list((ROOT / "rtl").rglob("*.sv")))
    simulation_hash = hash_paths([
        ROOT / "sim/verify/tb_verify.sv", ROOT / "scripts/run_verify_sim.py",
        ROOT / "scripts/verilator_build.py",
    ])
    model_hash = hash_paths(list((ROOT / "model").glob("*.py")))
    rows: list[dict[str, float | int | str]] = []
    for kind, label in KIND_NAMES.items():
        values = totals[kind]
        calls = values["calls"]
        if calls == 0:
            parser.error(f"no {label} calls found in selected corpus")
        row: dict[str, float | int | str] = {
            "rtl_sha256": rtl_hash,
            "simulation_sha256": simulation_hash,
            "model_sha256": model_hash,
            "rpc": args.rpc,
            "vectors": len(selected),
            "kind": label,
            **values,
        }
        for category, key in (("absorb", "absorb"), ("permutation", "permutation"),
                              ("response", "response"), ("idle", "idle")):
            row[f"mean_{category}"] = values[key] / calls
            row[f"mean_verify_{category}"] = values[key] / len(selected)
        row["mean_verify_total"] = sum(values[key] for key in
                                       ("absorb", "permutation", "response", "idle")) / len(selected)
        rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ("rtl_sha256", "simulation_sha256", "model_sha256", "rpc", "vectors", "kind", "calls",
              "absorb", "permutation", "response", "idle", "mean_absorb",
              "mean_permutation", "mean_response", "mean_idle", "mean_verify_absorb",
              "mean_verify_permutation", "mean_verify_response", "mean_verify_idle",
              "mean_verify_total")
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    svg_plot(rows, args.plot)
    print(f"Wrote {len(selected)} vectors: {display_path(args.output)} and {display_path(args.plot)}")
    for row in rows:
        print(f"{row['kind']}: calls={row['calls']} mean_absorb={row['mean_absorb']:.2f} "
              f"mean_permutation={row['mean_permutation']:.2f} "
              f"mean_response={row['mean_response']:.2f} mean_idle={row['mean_idle']:.2f} "
              f"mean_verify_total={row['mean_verify_total']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
