#!/usr/bin/env python3
"""Render the source-matched full-verifier Gowin area/latency sweep as SVG."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import html
import math

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def source_hash(rows: list[dict[str, str]], label: str) -> str:
    hashes = {row.get("source_sha256", "") for row in rows if row.get("source_sha256")}
    if len(hashes) != 1:
        raise ValueError(f"{label} must contain one shared non-empty source_sha256")
    return next(iter(hashes))


def render(measured: list[dict[str, str]], failed: list[dict[str, str]]) -> str:
    if not measured:
        raise ValueError("no fitted configurations to plot")
    digests = {source_hash(measured, "measurements")}
    if failed:
        digests.add(source_hash(failed, "failures"))
    if len(digests) != 1:
        raise ValueError("fit and failure rows have different source hashes")

    fitted = [
        (row["config"], float(row["logic_cells"]), float(row["latency_us_mean"]),
         float(row["f_run_mhz"]))
        for row in measured
    ]
    rejected = []
    for row in failed:
        area = float(row.get("reported_logic") or row.get("synth_lut") or 0)
        if area <= 0:
            raise ValueError(f"{row['config']}: missing synthesized logic estimate")
        latency = float(row["latency_us_mean"])
        rejected.append((row["config"], area, latency, row["failure_code"],
                         row["failure"], row.get("reported_logic", "")))

    all_x = [row[1] for row in fitted] + [row[1] for row in rejected]
    all_y = [row[2] for row in fitted] + [row[2] for row in rejected]
    x_min = max(0, math.floor((min(all_x) - 1000) / 2000) * 2000)
    x_max = math.ceil((max(all_x) + 1200) / 2000) * 2000
    y_min = max(0, math.floor((min(all_y) - 150) / 250) * 250)
    y_max = math.ceil((max(all_y) + 250) / 250) * 250
    width, height = 1000, 650
    left, right, top, bottom = 95, 55, 100, 105
    plot_w, plot_h = width - left - right, height - top - bottom
    x = lambda value: left + (value - x_min) / max(1, x_max - x_min) * plot_w
    y = lambda value: top + (y_max - value) / max(1, y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<style>text{font-family:Inter,Segoe UI,Arial,sans-serif;fill:#183044}.grid{stroke:#d8e1e8;stroke-width:1}.axis{stroke:#526878;stroke-width:1.5}.fit{fill:#147d92;stroke:#fff;stroke-width:2}.failed{fill:#fff;stroke:#c24f38;stroke-width:3}.label{font-size:13px}.small{font-size:12px;fill:#506474}.title{font-size:23px;font-weight:700}.subtitle{font-size:13px;fill:#506474}</style>',
        '<text x="95" y="36" class="title">Full-verifier Gowin area and latency</text>',
        '<text x="95" y="60" class="subtitle">20 ACVP core vectors per RPC configuration · configured core clock shown in labels</text>',
    ]

    for tick in range(0, 6):
        xv = x_min + (x_max - x_min) * tick / 5
        xp = x(xv)
        parts.extend((f'<line x1="{xp:.1f}" y1="{top}" x2="{xp:.1f}" y2="{height-bottom}" class="grid"/>',
                      f'<text x="{xp:.1f}" y="{height-bottom+24}" text-anchor="middle" class="small">{xv:,.0f}</text>'))
        yv = y_min + (y_max - y_min) * tick / 5
        yp = y(yv)
        parts.extend((f'<line x1="{left}" y1="{yp:.1f}" x2="{width-right}" y2="{yp:.1f}" class="grid"/>',
                      f'<text x="{left-12}" y="{yp+4:.1f}" text-anchor="end" class="small">{yv:,.0f}</text>'))
    parts.extend((f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"/>',
                  f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"/>',
                  f'<text x="{left + plot_w/2:.1f}" y="{height-32}" text-anchor="middle" class="label">Gowin logic cells (fits); pre-fit synthesis estimate (failures)</text>',
                  f'<text transform="translate(27 {top + plot_h/2:.1f}) rotate(-90)" text-anchor="middle" class="label">Mean verify latency at configured clock (µs)</text>'))

    for name, area, latency, mhz in fitted:
        px, py = x(area), y(latency)
        parts.extend((f'<circle cx="{px:.1f}" cy="{py:.1f}" r="8" class="fit"/>',
                      f'<text x="{px+12:.1f}" y="{py-18:.1f}" class="label">{html.escape(name)} · {mhz:.3f} MHz</text>'))
    reason_labels = {
        "PR0003": "placement failed",
        "PR0004": "routing failed",
        "RP0006": "device resource limit",
    }
    for name, area, latency, code, reason, reported in rejected:
        px, py = x(area), y(latency)
        points = f'{px:.1f},{py-9:.1f} {px+9:.1f},{py:.1f} {px:.1f},{py+9:.1f} {px-9:.1f},{py:.1f}'
        source_note = "reported logic" if reported else "synth LUT proxy"
        label = f'{name} · {code}: {reason_labels.get(code, "fit failed")} · {area:,.0f} {source_note}'
        anchor = "end" if px > width - right - 180 else "start"
        label_x = px - 14 if anchor == "end" else px + 14
        parts.extend((f'<polygon points="{points}" class="failed"><title>{html.escape(reason)}</title></polygon>',
                      f'<text x="{label_x:.1f}" y="{py+20:.1f}" text-anchor="{anchor}" class="label">{html.escape(label)}</text>'))
    parts.extend((f'<text x="{left}" y="{height-12}" class="small">Source SHA-256: {next(iter(digests))}</text>',
                  '<text x="615" y="76" class="small">● fitted   ◇ failed (open marker)</text>',
                  '<text x="95" y="88" class="small">Failed-fit area uses Gowin reported logic count when available; otherwise synthesized LUT count as a proxy.</text>',
                  '</svg>'))
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, default=ROOT / "bench/gowin_measurements.csv")
    parser.add_argument("--failures", type=Path, default=ROOT / "bench/gowin_failures.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "bench/plots/pareto.svg")
    args = parser.parse_args()
    try:
        svg = render(read_rows(args.measurements), read_rows(args.failures))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote source-matched Pareto SVG to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
