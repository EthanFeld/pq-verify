#!/usr/bin/env python3
"""Compare committed FPGA counters with UART-top simulation results."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_RESULT = re.compile(
    r"PASS system tc=(\d+) valid=(\d+) cycles=(\d+) perms=(\d+)"
)
FIELDS = (
    "dataset", "tcId", "mode", "expected", "status", "hardware_actual",
    "simulation_actual", "hardware_cycles", "simulation_cycles", "cycle_delta",
    "hardware_perms", "simulation_perms", "permutation_delta", "verdict_match",
    "cycle_match", "permutation_match",
)


def read_hardware(path: Path, dataset: str) -> dict[int, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    cases: dict[int, dict[str, str]] = {}
    for row in rows:
        tc_id = int(row["tcId"])
        if tc_id in cases:
            raise ValueError(f"{path}: duplicate tcId {tc_id}")
        if int(row["passed"]) != 1:
            raise ValueError(f"{path}: tcId {tc_id} did not pass on hardware")
        cases[tc_id] = {**row, "dataset": dataset}
    return cases


def read_simulation(path: Path, tc_id: int) -> tuple[int, int, int]:
    if not path.is_file():
        raise ValueError(f"missing UART-top simulation log for tcId {tc_id}: {path}")
    match = SYSTEM_RESULT.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        raise ValueError(f"missing passing system result in {path}")
    parsed_id, valid, cycles, perms = map(int, match.groups())
    if parsed_id != tc_id:
        raise ValueError(f"{path}: tcId {parsed_id} does not match expected {tc_id}")
    return valid, cycles, perms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence", type=Path,
        default=ROOT / "bench/evidence/gowin_c6_board_rpc1",
        help="directory containing hardware_results.csv and hardware_generated_results.csv",
    )
    parser.add_argument("--sim-dir", type=Path, default=ROOT / "build/sim_system")
    parser.add_argument("--uart-clks-per-bit", type=int, default=4)
    args = parser.parse_args()
    if args.uart_clks_per_bit < 4:
        parser.error("--uart-clks-per-bit must be at least 4")

    try:
        cases = read_hardware(args.evidence / "hardware_results.csv", "acvp")
        generated = read_hardware(args.evidence / "hardware_generated_results.csv", "generated")
        overlap = cases.keys() & generated.keys()
        if overlap:
            raise ValueError(f"duplicate tcIds across datasets: {sorted(overlap)}")
        cases.update(generated)

        compared: list[dict[str, object]] = []
        for tc_id, hardware in sorted(cases.items(), key=lambda item: (item[1]["dataset"], item[0])):
            sim_valid, sim_cycles, sim_perms = read_simulation(
                args.sim_dir / f"tc{tc_id}" / "run.log", tc_id
            )
            hardware_valid = int(hardware["actual"])
            hardware_cycles = int(hardware["cycles"])
            hardware_perms = int(hardware["perms"])
            cycle_delta = sim_cycles - hardware_cycles
            permutation_delta = sim_perms - hardware_perms
            verdict_match = sim_valid == hardware_valid
            cycle_match = sim_cycles == hardware_cycles
            permutation_match = sim_perms == hardware_perms
            compared.append({
                "dataset": hardware["dataset"],
                "tcId": tc_id,
                "mode": hardware["mode"],
                "expected": int(hardware["expected"]),
                "status": hardware["status"],
                "hardware_actual": hardware_valid,
                "simulation_actual": sim_valid,
                "hardware_cycles": hardware_cycles,
                "simulation_cycles": sim_cycles,
                "cycle_delta": cycle_delta,
                "hardware_perms": hardware_perms,
                "simulation_perms": sim_perms,
                "permutation_delta": permutation_delta,
                "verdict_match": int(verdict_match),
                "cycle_match": int(cycle_match),
                "permutation_match": int(permutation_match),
            })

        output_csv = args.evidence / "hardware_sim_parity.csv"
        with output_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(compared)

        count = len(compared)
        verdict_matches = sum(int(row["verdict_match"]) for row in compared)
        cycle_matches = sum(int(row["cycle_match"]) for row in compared)
        permutation_matches = sum(int(row["permutation_match"]) for row in compared)
        absolute_cycle_deltas = [abs(int(row["cycle_delta"])) for row in compared]
        summary = {
            "cases": count,
            "acvp_cases": sum(row["dataset"] == "acvp" for row in compared),
            "generated_cases": sum(row["dataset"] == "generated" for row in compared),
            "verdict_matches": verdict_matches,
            "exact_cycle_matches": cycle_matches,
            "exact_permutation_matches": permutation_matches,
            "max_absolute_cycle_delta": max(absolute_cycle_deltas, default=0),
            "mean_absolute_cycle_delta": round(statistics.mean(absolute_cycle_deltas), 2)
            if absolute_cycle_deltas else 0,
            "uart_simulation_clks_per_bit": args.uart_clks_per_bit,
            "uart_simulation_note": "Accelerated UART framing; verifier response counters compared per vector.",
            "results_csv": output_csv.name,
        }
        output_json = args.evidence / "hardware_sim_parity.json"
        output_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(
            f"PASS hardware/simulation parity: {count} cases; "
            f"verdict {verdict_matches}/{count}, cycles {cycle_matches}/{count}, "
            f"permutations {permutation_matches}/{count}; "
            f"evidence {output_csv.relative_to(ROOT)}"
        )
        if verdict_matches != count or cycle_matches != count or permutation_matches != count:
            print("hardware and UART-top simulation counters differ", file=sys.stderr)
            return 1
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"hardware-sim-parity: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
