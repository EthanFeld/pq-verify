#!/usr/bin/env python3
"""Export measured core cycles and source-bound synthesis/P&R inputs for bench."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def checked_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("rpc") != 1 or manifest.get("scratch_style") != 0:
        raise ValueError(f"{path}: expected the RPC1/block-scratch hardware candidate")
    for name, expected in manifest.get("sources", {}).items():
        source = ROOT / name
        if not source.is_file():
            raise ValueError(f"{path}: source missing: {name}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{path}: source changed since fit: {name}")
    fit = manifest.get("fit", {})
    clock = fit.get("clocks", {}).get("core_clk", {})
    if not clock.get("fmax_mhz") or not clock.get("constraint_mhz"):
        raise ValueError(f"{path}: missing fitted core clock data")
    return manifest


def parse_synthesis(path: Path) -> dict[str, int]:
    log = path.read_text(encoding="utf-8", errors="replace")
    marker = "=== top_tn20k ==="
    if marker not in log:
        raise ValueError(f"{path}: missing final top_tn20k statistics")
    summary = log.rsplit(marker, 1)[1]

    def cell_count(kind: str, *, required: bool = True) -> int:
        match = re.search(rf"^\s*(\d+)\s+{re.escape(kind)}\s*$", summary, re.MULTILINE)
        if not match:
            if required:
                raise ValueError(f"{path}: missing {kind} count")
            return 0
        return int(match.group(1))

    ff_types = ("DFF", "DFFC", "DFFCE", "DFFP", "DFFR", "DFFS", "DFFSR")
    lutram_types = ("RAM16", "RAM32", "RAM64", "LUTRAM")
    return {
        # LUT1/2/3 cells occupy the same physical LUT4 slots.
        "lut4": cell_count("LUT4") + sum(cell_count(f"LUT{width}", required=False)
                                         for width in (1, 2, 3)),
        "ff": sum(cell_count(kind, required=False) for kind in ff_types),
        "bsram": cell_count("DPX9B", required=False) + cell_count("SDPX9B", required=False),
        "lutram": sum(cell_count(kind, required=False) for kind in lutram_types),
    }


def read_vector_modes(path: Path) -> dict[str, str]:
    vectors = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(vector["tcId"]): vector["mode"]
        for vector in vectors
        if len(vector["signature"]) == 7856 * 2
        and len(vector["pk"]) == 32 * 2
        and (vector["mode"] == "internal"
             or len(vector.get("context", "")) <= 255 * 2)
    }


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--sim-dir", type=Path, default=ROOT / "build/sim_verify")
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    parser.add_argument("--synthesis-log", type=Path,
                        default=ROOT / "build/bench_lut4_final/top_tn20k_rpc1_scratch0_yosys.log")
    parser.add_argument("--fit-manifest", type=Path,
                        default=ROOT / "build/gowin_lut4_final_rpc1/build_manifest.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "bench")
    args = parser.parse_args()
    if args.rpc != 1:
        parser.error("current source-bound board fit and hardware candidate are RPC1 only")
    try:
        fit = checked_manifest(args.fit_manifest)
        resources = parse_synthesis(args.synthesis_log)
        modes = read_vector_modes(args.vectors)
        selected = {
            tcid for tcid, mode in modes.items()
            if mode in {"internal", "pure"}
            and (log := args.sim_dir / f"tc{tcid}_rpc{args.rpc}" / "run.log").is_file()
            and "PASS verify " in log.read_text(encoding="utf-8", errors="replace")
        }
        expected_modes = {
            tcid for tcid, mode in modes.items()
            if mode in {"internal", "pure"}
        }
        if len(selected) != 20 or selected != expected_modes:
            raise ValueError(f"expected all 20 well-formed vectors; found {len(selected)}")

        config = f"rpc{args.rpc}_scratch0"
        cycles_rows: list[dict[str, object]] = []
        stage_rows: list[dict[str, object]] = []
        for tcid in sorted(selected, key=int):
            log_path = args.sim_dir / f"tc{tcid}_rpc{args.rpc}" / "run.log"
            text = log_path.read_text(encoding="utf-8", errors="replace")
            result = re.search(
                rf"PASS verify tc={tcid} RPC={args.rpc} valid=\d+ cycles=(\d+) perms=(\d+)", text
            )
            if not result:
                raise ValueError(f"{log_path}: missing final cycle/permutation record")
            cycles, perms = map(int, result.groups())
            found_stages = re.findall(rf"STAGE tc={tcid} name=([a-z_]+) cycles=(\d+)", text)
            if {name for name, _ in found_stages} != {"hmsg", "fors", "hypertree"}:
                raise ValueError(f"{log_path}: missing one or more stage counters")
            stage_total = 0
            for name, value in found_stages:
                stage_cycles = int(value)
                stage_total += stage_cycles
                stage_rows.append({"config": config, "tcId": tcid,
                                   "stage": name, "cycles": stage_cycles})
            if stage_total > cycles:
                raise ValueError(f"{log_path}: stage sum exceeds verifier cycles")
            cycles_rows.append({"config": config, "tcId": tcid, "mode": modes[tcid],
                                "cycles": cycles, "perms": perms,
                                "keccak_cycles": perms * (24 // args.rpc)})

        synthesis_manifest_path = args.synthesis_log.with_name(
            f"top_tn20k_rpc{args.rpc}_scratch0_synthesis_manifest.json"
        )
        synthesis_manifest = json.loads(synthesis_manifest_path.read_text(encoding="utf-8"))
        rtl_fit_hashes = {name: digest for name, digest in fit["sources"].items()
                          if name.startswith("rtl/")}
        if synthesis_manifest.get("sources", {}) != fit["sources"]:
            if {name: digest for name, digest in synthesis_manifest.get("sources", {}).items()
                    if name.startswith("rtl/")} != rtl_fit_hashes:
                raise ValueError("synthesis and fitted hardware RTL hashes differ")

        core_clock = fit["fit"]["clocks"]["core_clk"]
        measurement = [{
            "config": config, "rpc": args.rpc, **resources,
            "fmax_mhz": core_clock["fmax_mhz"],
            "f_run_mhz": core_clock["constraint_mhz"],
            "timing_flow": "gowin",
            "gowin_logic_cells": fit["fit"]["resources"]["logic"]["used"],
        }]
        write_csv(args.output_dir / "measurements.csv",
                  ("config", "rpc", "lut4", "ff", "bsram", "lutram", "fmax_mhz", "f_run_mhz",
                   "timing_flow", "gowin_logic_cells"),
                  measurement)
        write_csv(args.output_dir / "verify_cycles.csv",
                  ("config", "tcId", "mode", "cycles", "perms", "keccak_cycles"),
                  cycles_rows)
        write_csv(args.output_dir / "stage_cycles.csv",
                  ("config", "tcId", "stage", "cycles"), stage_rows)
        print(f"Exported source-checked {config} measurements, {len(cycles_rows)} vectors, "
              f"{len(stage_rows)} stage intervals to {args.output_dir}")
        return 0
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
