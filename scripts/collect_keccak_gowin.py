#!/usr/bin/env python3
"""Collect source-matched isolated Keccak Gowin fit rows."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from gowin_keccak_build import ROOT, source_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, default=ROOT / "bench/keccak_gowin_measurements.csv")
    args = parser.parse_args()
    paths = sorted(args.build_root.glob("gowin_keccak_rpc*/build_manifest.json"))
    if not paths:
        parser.error(f"no Gowin Keccak manifests found in {args.build_root}")
    try:
        expected = source_hashes()
        rows = []
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("sources") != expected:
                print(f"Skipping stale Keccak fit: {path}")
                continue
            fit = data["fit"]
            clock = fit["clock"]
            resources = fit
            stages = data.get("stage_seconds", {})
            rows.append({
                "rpc": data["rpc"],
                "place_option": data["place_option"],
                "route_option": data["route_option"],
                "logic_cells": resources["logic_cells"]["used"],
                "ff": resources["ff"]["used"],
                "fmax_mhz": clock["fmax_mhz"],
                "clock_mhz": clock["constraint_mhz"],
                "setup_violations": fit["violated_endpoints"]["setup"],
                "hold_violations": fit["violated_endpoints"]["hold"],
                "bitstream_bytes": fit["bitstream"]["binary_bytes"],
                "gowin_fit_pack_seconds": stages.get("gowin_fit_pack", ""),
            })
        if not rows:
            raise ValueError("no source-matched Keccak Gowin fits")
        configs = [(row["rpc"], row["place_option"], row["route_option"]) for row in rows]
        if len(configs) != len(set(configs)):
            raise ValueError("duplicate RPC/placer/router Keccak fits found")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        columns = (
            "rpc", "place_option", "route_option", "logic_cells", "ff", "fmax_mhz",
            "clock_mhz", "setup_violations", "hold_violations", "bitstream_bytes",
            "gowin_fit_pack_seconds",
        )
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Collected {len(rows)} Keccak fits into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
