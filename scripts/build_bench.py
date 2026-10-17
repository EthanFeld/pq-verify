#!/usr/bin/env python3
"""Aggregate measured FPGA resources and per-vector cycles into benchmark outputs."""

from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from pathlib import Path


def read_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing benchmark input: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def number(row: dict[str, str], key: str, path: Path, *, positive: bool = False) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path}: invalid {key} value {row.get(key)!r}") from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = "positive and finite" if positive else "nonnegative and finite"
        raise ValueError(f"{path}: {key} must be {qualifier}")
    return value


def load_measurements(path: Path) -> dict[str, dict[str, float]]:
    required = {
        "config", "rpc", "lut4", "ff", "bsram", "lutram", "fmax_mhz", "f_run_mhz"
    }
    rows = read_rows(path, required)
    if not rows:
        raise ValueError(f"{path}: no measurement rows")
    measurements: dict[str, dict[str, float]] = {}
    for row in rows:
        config = row["config"].strip()
        if not config or config in measurements:
            raise ValueError(f"{path}: empty or duplicate config {config!r}")
        measurements[config] = {
            field: number(row, field, path, positive=field in {"rpc", "fmax_mhz", "f_run_mhz"})
            for field in required - {"config"}
        }
        for field in ("rpc", "lut4", "ff", "bsram", "lutram"):
            if not measurements[config][field].is_integer():
                raise ValueError(f"{path}: {field} must be an integer for {config!r}")
        if int(measurements[config]["rpc"]) not in {1, 2, 3, 4, 6, 8, 12, 24}:
            raise ValueError(f"{path}: unsupported RPC for {config!r}")
        if measurements[config]["f_run_mhz"] > measurements[config]["fmax_mhz"]:
            raise ValueError(f"{path}: f_run_mhz exceeds fmax_mhz for {config!r}")
    return measurements


def load_cycles(path: Path, measurements: dict[str, dict[str, float]]) -> dict[str, list[dict[str, float | str]]]:
    required = {"config", "tcId", "mode", "cycles", "perms", "keccak_cycles"}
    rows = read_rows(path, required)
    if not rows:
        raise ValueError(f"{path}: no cycle rows")
    grouped: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        config, tcid = row["config"].strip(), row["tcId"].strip()
        if config not in measurements:
            raise ValueError(f"{path}: {config!r} has no resource measurement")
        if not tcid or (config, tcid) in seen:
            raise ValueError(f"{path}: empty or duplicate tcId for {config!r}: {tcid!r}")
        seen.add((config, tcid))
        cycles = number(row, "cycles", path, positive=True)
        perms = number(row, "perms", path)
        keccak = number(row, "keccak_cycles", path)
        if any(not value.is_integer() for value in (cycles, perms, keccak)):
            raise ValueError(f"{path}: cycle and permutation counters must be integers for {config}/{tcid}")
        if keccak > cycles:
            raise ValueError(f"{path}: keccak_cycles exceeds cycles for {config}/{tcid}")
        grouped[config].append(
            {"tcId": tcid, "mode": row["mode"], "cycles": cycles, "perms": perms, "keccak_cycles": keccak}
        )
    absent = measurements.keys() - grouped.keys()
    if absent:
        raise ValueError(f"{path}: no cycle rows for: {', '.join(sorted(absent))}")
    return grouped


def read_stages(
    path: Path,
    measurements: dict[str, dict[str, float]],
    cycles: dict[str, list[dict[str, float | str]]],
) -> dict[str, dict[str, list[float]]]:
    required = {"config", "tcId", "stage", "cycles"}
    rows = read_rows(path, required)
    by_config: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str, str]] = set()
    stage_tcids: dict[tuple[str, str], set[str]] = defaultdict(set)
    stage_totals: dict[tuple[str, str], float] = defaultdict(float)
    cycle_totals = {
        (config, str(row["tcId"])): float(row["cycles"])
        for config, samples in cycles.items()
        for row in samples
    }
    for row in rows:
        config, tcid, stage = row["config"].strip(), row["tcId"].strip(), row["stage"].strip()
        if config not in measurements or not tcid or not stage:
            raise ValueError(f"{path}: invalid config, tcId or stage in row {row}")
        if (config, tcid) not in cycle_totals:
            raise ValueError(f"{path}: stage row has no matching verify cycle row for {config}/{tcid}")
        key = (config, tcid, stage)
        if key in seen:
            raise ValueError(f"{path}: duplicate stage row for {config}/{tcid}/{stage}")
        seen.add(key)
        stage_tcids[(config, stage)].add(tcid)
        stage_cycles = number(row, "cycles", path, positive=True)
        by_config[config][stage].append(stage_cycles)
        stage_totals[(config, tcid)] += stage_cycles
    if not rows:
        raise ValueError(f"{path}: no stage rows")
    reference_stages: set[str] | None = None
    for config, samples in cycles.items():
        expected_tcids = {str(row["tcId"]) for row in samples}
        stages = by_config.get(config, {})
        if not stages:
            raise ValueError(f"{path}: no stage rows for {config!r}")
        config_stages = set(stages)
        if reference_stages is None:
            reference_stages = config_stages
        elif config_stages != reference_stages:
            raise ValueError(f"{path}: stage names differ across configurations")
        for stage in stages:
            present_tcids = stage_tcids[(config, stage)]
            missing = expected_tcids - present_tcids
            if missing:
                sample = ", ".join(sorted(missing)[:5])
                raise ValueError(f"{path}: {config}/{stage} missing vectors: {sample}")
        for tcid in expected_tcids:
            if stage_totals[(config, tcid)] > cycle_totals[(config, tcid)]:
                raise ValueError(f"{path}: summed stage cycles exceed verify cycles for {config}/{tcid}")
    return by_config


def aggregate(measurements: dict[str, dict[str, float]], cycles: dict[str, list[dict[str, float | str]]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for config, samples in sorted(cycles.items()):
        resource = measurements[config]
        values = [float(row["cycles"]) for row in samples]
        mean_cycles = sum(values) / len(values)
        frequency = resource["f_run_mhz"]
        latency = mean_cycles / frequency
        total_perms = sum(float(row["perms"]) for row in samples)
        total_cycles = sum(values)
        busy_cycles = sum(float(row["keccak_cycles"]) for row in samples)
        results.append(
            {
                "config": config,
                "scope": "verifier",
                "rpc": int(resource["rpc"]),
                "lut4": int(resource["lut4"]),
                "ff": int(resource["ff"]),
                "bsram": int(resource["bsram"]),
                "lutram": int(resource["lutram"]),
                "fmax_mhz": resource["fmax_mhz"],
                "f_run_mhz": frequency,
                "cycles_min": min(values),
                "cycles_mean": mean_cycles,
                "cycles_max": max(values),
                "latency_us": latency,
                "verifies_per_s": 1_000_000 / latency,
                "atp": resource["lut4"] * latency,
                "perms": total_perms / len(samples),
                "keccak_busy_pct": 100 * busy_cycles / total_cycles,
            }
        )
    return results


RESULT_COLUMNS = (
    "config", "scope", "rpc", "lut4", "ff", "bsram", "lutram", "fmax_mhz", "f_run_mhz",
    "cycles_min", "cycles_mean", "cycles_max", "latency_us", "verifies_per_s", "atp",
    "perms", "keccak_busy_pct", "permutation_cycles", "permutation_latency_at_fmax_us", "timing_flow",
    "clock_constraint_mhz", "timing_met",
)


def load_keccak(path: Path) -> list[dict[str, object]]:
    """Keep isolated permutation measurements distinct from verifier latency."""
    if not path.is_file():
        return []
    import json
    if __package__:
        from .keccak_build import ROOT, TIMING_PROFILES, checksum, fit_result, mapped_resources, source_hashes
    else:
        from keccak_build import ROOT, TIMING_PROFILES, checksum, fit_result, mapped_resources, source_hashes

    samples = read_rows(path, {"config", "rpc", "lut4", "ff", "bsram", "lutram", "fmax_mhz", "manifest"})
    results = []
    seen = set()
    for sample in samples:
        rpc_value = number(sample, "rpc", path, positive=True)
        if not rpc_value.is_integer():
            raise ValueError(f"{path}: Keccak RPC must be an integer")
        rpc = int(rpc_value)
        if rpc not in (1, 2, 3, 4) or rpc in seen:
            raise ValueError(f"{path}: invalid or duplicate Keccak RPC {rpc}")
        seen.add(rpc)
        manifest_path = ROOT / sample["manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["sources"] != source_hashes() or manifest["rpc"] != rpc:
            raise ValueError(f"{manifest_path}: stale Keccak implementation")
        if manifest.get("lut_timing") not in TIMING_PROFILES:
            raise ValueError(f"{manifest_path}: incomplete small-LUT timing arcs")
        for name, digest in manifest["outputs"].items():
            if checksum(manifest_path.parent / name) != digest:
                raise ValueError(f"{manifest_path}: Keccak output checksum mismatch")
        mapped_resources(manifest_path.parent / "timing_netlist.json", require_full_timing=True)
        mapped_resources(manifest_path.parent / "routed.json", require_full_timing=True)
        fit = fit_result(manifest_path.parent / "pnr_report.json")
        for key in ("lut4", "ff", "bsram", "lutram", "fmax_mhz"):
            if abs(number(sample, key, path) - fit[key]) > 1e-6:
                raise ValueError(f"{path}: {key} differs from its routed report")
        results.append({"config": f"keccak_ooc_rpc{rpc}", "scope": "keccak_ooc", "rpc": rpc,
                        **{key: fit[key] for key in ("lut4", "ff", "bsram", "lutram", "fmax_mhz")},
                        "permutation_cycles": 24 // rpc,
                        "permutation_latency_at_fmax_us": (24 // rpc) / fit["fmax_mhz"],
                        "timing_flow": "nextpnr", "clock_constraint_mhz": fit["clock_constraint_mhz"],
                        "timing_met": fit["fmax_mhz"] >= fit["clock_constraint_mhz"]})
    return results


def write_results(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def svg_text(x: float, y: float, value: str, *, size: int = 12, anchor: str = "middle") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{size}">{html.escape(value)}</text>'


def scale(value: float, low: float, high: float, start: float, end: float) -> float:
    return (start + end) / 2 if high == low else start + (value - low) * (end - start) / (high - low)


def write_area_latency(path: Path, rows: list[dict[str, object]]) -> None:
    width, height = 820, 520
    left, right, top, bottom = 90, 35, 55, 80
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [float(row["lut4"]) for row in rows]
    ys = [float(row["latency_us"]) for row in rows]
    xlo, xhi = min(xs) * 0.9, max(xs) * 1.05
    ylo, yhi = min(ys) * 0.9, max(ys) * 1.08
    xmap = lambda value: scale(value, xlo, xhi, left, left + plot_w)
    ymap = lambda value: scale(value, ylo, yhi, top + plot_h, top)
    pareto = [
        row for row in rows
        if not any(
            int(other["lut4"]) <= int(row["lut4"])
            and float(other["latency_us"]) <= float(row["latency_us"])
            and (int(other["lut4"]) < int(row["lut4"]) or float(other["latency_us"]) < float(row["latency_us"]))
            for other in rows if other is not row
        )
    ]
    pareto.sort(key=lambda row: int(row["lut4"]))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<style>text{font-family:Arial,sans-serif;fill:#222} line{stroke:#777;stroke-width:1}</style>',
             svg_text(width / 2, 28, "LUT4 area vs mean verify latency", size=18),
             f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}"/>',
             f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>',
             svg_text(left + plot_w / 2, height - 25, "LUT4", size=14),
             f'<text x="20" y="{top + plot_h / 2}" transform="rotate(-90 20 {top + plot_h / 2})" text-anchor="middle" font-family="Arial" font-size="14">Latency (µs)</text>']
    if len(pareto) > 1:
        points = " ".join(f'{xmap(float(row["lut4"])):.1f},{ymap(float(row["latency_us"])):.1f}' for row in pareto)
        parts.append(f'<polyline points="{points}" fill="none" stroke="#dc5a44" stroke-width="2"/>')
    for row in rows:
        x, y = xmap(float(row["lut4"])), ymap(float(row["latency_us"]))
        front = row in pareto
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{"#dc5a44" if front else "#2878b5"}"/>')
        parts.append(svg_text(x, y - 10, str(row["config"]), size=11))
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_fmax_rpc(path: Path, rows: list[dict[str, object]]) -> None:
    width, height = 820, 460
    left, right, top, bottom = 85, 35, 55, 75
    values = [float(row["fmax_mhz"]) for row in rows]
    low, high = 0.0, max(values) * 1.12
    rpcs = sorted({int(row["rpc"]) for row in rows})
    xmap = lambda rpc: scale(rpc, min(rpcs), max(rpcs), left, width - right)
    ymap = lambda value: scale(value, low, high, height - bottom, top)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<style>text{font-family:Arial,sans-serif;fill:#222} line{stroke:#777;stroke-width:1}</style>',
             svg_text(width / 2, 28, "Routed Fmax: verifier and isolated Keccak", size=18),
             f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"/>',
             f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"/>',
             svg_text((left + width - right) / 2, height - 22, "Rounds per cycle (RPC)", size=14),
             f'<text x="20" y="{(top + height - bottom) / 2}" transform="rotate(-90 20 {(top + height - bottom) / 2})" text-anchor="middle" font-family="Arial" font-size="14">Fmax (MHz)</text>']
    for tick in range(5):
        value = high * tick / 4
        y = ymap(value)
        parts.append(f'<line x1="{left - 4}" y1="{y:.1f}" x2="{left}" y2="{y:.1f}"/>')
        parts.append(svg_text(left - 9, y + 4, f"{value:.0f}", size=11, anchor="end"))
    for row in rows:
        x, y = xmap(int(row["rpc"])), ymap(float(row["fmax_mhz"]))
        color = "#d65f5f" if row.get("scope") == "keccak_ooc" else "#2878b5"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>')
        anchor = "start" if int(row["rpc"]) == min(rpcs) else "end" if int(row["rpc"]) == max(rpcs) else "middle"
        parts.append(svg_text(x, y - 10, f"{row['config']} ({float(row['fmax_mhz']):.1f})",
                              size=11, anchor=anchor))
    for rpc in rpcs:
        parts.append(svg_text(xmap(rpc), height - bottom + 22, str(rpc), size=11))
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_stage_breakdown(path: Path, rows: list[dict[str, object]], stage_data: dict[str, dict[str, list[float]]]) -> None:
    rpc1_rows = [row for row in rows if int(row["rpc"]) == 1]
    baseline_rows = [
        row for row in rpc1_rows
        if "baseline" in str(row["config"]).lower()
    ]
    if not baseline_rows:
        baseline_rows = [
            row for row in rpc1_rows
            if "overlap" not in str(row["config"]).lower()
        ]
    baseline = str((baseline_rows or rpc1_rows or rows)[0]["config"])
    best = str(min(rows, key=lambda row: float(row["latency_us"]))["config"])
    configs = list(dict.fromkeys((baseline, best)))
    stages = sorted({stage for config in configs for stage in stage_data.get(config, {})})
    if not stages:
        return
    values = {
        config: [sum(stage_data.get(config, {}).get(stage, [])) / max(1, len(stage_data.get(config, {}).get(stage, []))) for stage in stages]
        for config in configs
    }
    max_total = max(sum(values[config]) for config in configs)
    width, height = 820, 500
    left, right, top, bottom = 90, 35, 55, 85
    plot_h = height - top - bottom
    colors = ("#2878b5", "#4b9b63", "#e3a43b", "#9664a8", "#d65f5f", "#52a8a8")
    bar_w = min(130, (width - left - right) // max(3, len(configs) * 2))
    centers = [left + (i + 1) * (width - left - right) / (len(configs) + 1) for i in range(len(configs))]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<style>text{font-family:Arial,sans-serif;fill:#222} line{stroke:#777;stroke-width:1}</style>',
             svg_text(width / 2, 28, "Mean cycle breakdown by stage", size=18),
             f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}"/>',
             f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>',
             svg_text(20, top + plot_h / 2, "Cycles per verify", size=13)]
    for i, config in enumerate(configs):
        y_bottom = top + plot_h
        for idx, stage in enumerate(stages):
            bar_h = values[config][idx] / max_total * plot_h if max_total else 0
            y_bottom -= bar_h
            parts.append(f'<rect x="{centers[i] - bar_w / 2:.1f}" y="{y_bottom:.1f}" width="{bar_w}" height="{bar_h:.1f}" fill="{colors[idx % len(colors)]}"/>')
        parts.append(svg_text(centers[i], height - bottom + 20, config, size=11))
    legend_y = height - 20
    legend_x = left
    for idx, stage in enumerate(stages):
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 12}" width="12" height="12" fill="{colors[idx % len(colors)]}"/>')
        parts.append(svg_text(legend_x + 18, legend_y - 2, stage, size=11, anchor="start"))
        legend_x += 95
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, default=repo / "bench" / "measurements.csv")
    parser.add_argument("--cycles", type=Path, default=repo / "bench" / "verify_cycles.csv")
    parser.add_argument("--stages", type=Path, default=repo / "bench" / "stage_cycles.csv")
    parser.add_argument("--keccak", type=Path, default=repo / "bench" / "keccak_measurements.csv")
    parser.add_argument("--output", type=Path, default=repo / "bench" / "results.csv")
    parser.add_argument("--plots", type=Path, default=repo / "bench" / "plots")
    args = parser.parse_args()
    try:
        measurements = load_measurements(args.measurements)
        cycles = load_cycles(args.cycles, measurements)
        stage_data = read_stages(args.stages, measurements, cycles)
        results = aggregate(measurements, cycles)
        timing_flows = {row["config"].strip(): row.get("timing_flow", "")
                        for row in read_rows(args.measurements, {"config"})}
        for result in results:
            result["timing_flow"] = timing_flows[str(result["config"])]
            result["clock_constraint_mhz"] = result["f_run_mhz"]
            result["timing_met"] = result["fmax_mhz"] >= result["f_run_mhz"]
        keccak_results = load_keccak(args.keccak)
        write_results(args.output, results + keccak_results)
        write_area_latency(args.plots / "lut4_latency.svg", results)
        write_fmax_rpc(args.plots / "fmax_rpc.svg", results + keccak_results)
        write_stage_breakdown(args.plots / "cycle_breakdown.svg", results, stage_data)
        print(f"Wrote {args.output} and plots to {args.plots}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
