#!/usr/bin/env python3
"""Collect mapped resources and Fmax from completed full-design P&R reports."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any


CONFIG_RE = re.compile(r"top_tn20k_rpc([1-4])_scratch([0-2])_pnr_report\.json$")
F_RUN_MHZ = 50.143


def used_resources(value: Any, parent: str = "") -> dict[str, float]:
    found: dict[str, float] = {}
    if isinstance(value, dict):
        if "used" in value and isinstance(value["used"], (int, float)):
            found[parent.upper()] = float(value["used"])
        else:
            for key, child in value.items():
                found.update(used_resources(child, str(key)))
    elif isinstance(value, list):
        for child in value:
            found.update(used_resources(child, parent))
    return found


def resource_value(resources: dict[str, float], category: str) -> int:
    def matches(name: str) -> bool:
        key = name.upper().replace("_", "")
        if category == "lut4":
            return key == "LUT4" or key.endswith("LUT4")
        if category == "ff":
            return key in {"FF", "DFF", "DFFE", "DFFR", "DFFS", "DFFSR"} or key.startswith("DFF")
        if category == "bsram":
            return "BSRAM" in key or "BLOCKRAM" in key
        if category == "lutram":
            return "LUTRAM" in key or key.startswith(("RAM16", "RAM32", "RAM64"))
        return False

    values = [amount for name, amount in resources.items() if matches(name)]
    if not values:
        if category in {"bsram", "lutram"}:
            return 0
        raise ValueError(f"P&R report lacks a recognized {category} utilization entry")
    total = sum(values)
    if not math.isfinite(total) or total < 0 or not total.is_integer():
        raise ValueError(f"invalid {category} resource count {total}")
    return int(total)


def fmax_values(value: Any, under_fmax: bool = False) -> list[float]:
    results: list[float] = []
    if isinstance(value, dict):
        for key, child in value.items():
            is_fmax = under_fmax or "fmax" in str(key).lower()
            if is_fmax and isinstance(child, dict):
                for metric in ("achieved", "fmax", "frequency"):
                    result = child.get(metric)
                    if isinstance(result, (int, float)):
                        results.append(float(result))
            results.extend(fmax_values(child, is_fmax))
    elif isinstance(value, list):
        for child in value:
            results.extend(fmax_values(child, under_fmax))
    return [item for item in results if math.isfinite(item) and item > 0]


def collect_report(path: Path) -> dict[str, object]:
    match = CONFIG_RE.search(path.name)
    if not match:
        raise ValueError(f"unexpected P&R report filename: {path.name}")
    rpc, style = map(int, match.groups())
    data = json.loads(path.read_text(encoding="utf-8"))
    resources = used_resources(data)
    frequencies = fmax_values(data)
    if not frequencies:
        raise ValueError(f"{path}: report lacks an achieved Fmax")
    return {
        "config": f"rpc{rpc}_scratch{style}",
        "rpc": rpc,
        "lut4": resource_value(resources, "lut4"),
        "ff": resource_value(resources, "ff"),
        "bsram": resource_value(resources, "bsram"),
        "lutram": resource_value(resources, "lutram"),
        "fmax_mhz": min(frequencies),
        "f_run_mhz": F_RUN_MHZ,
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=repo / "build")
    parser.add_argument("--output", type=Path, default=repo / "bench" / "measurements.csv")
    args = parser.parse_args()
    reports = sorted(args.build_dir.glob("top_tn20k_rpc*_scratch*_pnr_report.json"))
    if not reports:
        parser.error(f"no full-design P&R reports found in {args.build_dir}")
    try:
        rows = [collect_report(path) for path in reports]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        columns = ("config", "rpc", "lut4", "ff", "bsram", "lutram", "fmax_mhz", "f_run_mhz")
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Collected {len(rows)} configurations into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
