#!/usr/bin/env python3
"""Refresh the README summary from the validated board evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = "<!-- bench-results:start -->"
END = "<!-- bench-results:end -->"


def render(readme: Path, manifest_path: Path, identity_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    fit = manifest["fit"]
    resources = fit["resources"]
    clock = fit["clocks"]["core_clk"]
    acvp = identity["functional_regression"]
    generated = identity["generated_regression"]
    parity = identity["system_simulation_parity"]
    checks = (
        f"{acvp['passed']}/{acvp['vector_count']} ACVP; "
        f"{generated['passed']}/{generated['vector_count']} generated; "
        f"{parity['exact_cycle_matches']}/{parity['cases']} exact parity"
    )
    lines = [
        "<!-- Generated from validated board evidence by make bench. -->",
        "| Board | Device | Logic cells | FF | BSRAM | Fmax / core clock | Timing margin | UART verification |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        f"| {identity['board']} | {identity['device']} | "
        f"{resources['logic']['used']:,} / {resources['logic']['available']:,} | "
        f"{resources['ff']['used']:,} / {resources['ff']['available']:,} | "
        f"{resources['bsram']['used']} / {resources['bsram']['available']} | "
        f"{clock['fmax_mhz']:.3f} / {clock['constraint_mhz']:.3f} MHz | "
        f"{fit['core_clock_margin_fraction'] * 100:.2f}% | {checks} |",
        "",
        f"Bitstream SHA-256: `{manifest['bitstream']['sha256']}`.",
    ]

    content = readme.read_text(encoding="utf-8")
    if content.count(START) != 1 or content.count(END) != 1:
        raise ValueError(f"{readme}: expected one results marker pair")
    before, rest = content.split(START, 1)
    _, after = rest.split(END, 1)
    return before + START + "\n" + "\n".join(lines) + "\n" + END + after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "bench/evidence/gowin_c6_board_rpc1/manifest.json",
    )
    parser.add_argument(
        "--identity", type=Path,
        default=ROOT / "bench/evidence/gowin_c6_board_rpc1/hardware_identity.json",
    )
    args = parser.parse_args()
    updated = render(args.readme, args.manifest, args.identity)
    args.readme.write_text(updated, encoding="utf-8", newline="\n")
    print(f"Updated {args.readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
