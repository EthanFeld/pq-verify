#!/usr/bin/env python3
"""Run Gowin full-board sweeps, retain per-configuration failures, then collect."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def run(command: list[str]) -> bool:
    print("\n$ " + subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def reusable_manifest(mode: str, rpc: int, style: int | None,
                      expected_sources: dict[str, str]) -> Path | None:
    current_rtl = {name: digest for name, digest in expected_sources.items()
                   if name.startswith("rtl/")}
    candidates: list[Path] = []
    for path in (ROOT / "build").glob("gowin_*/gowin_synthesis_manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (data.get("rpc") == rpc
                and (mode == "keccak" or data.get("scratch_style") == style)
                and data.get("device") == "GW2AR-LV18QN88C8/I7"
                and data.get("rtl_sources") == current_rtl):
            candidates.append(path)
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def recorded_vendor_failure(path: Path, expected_sources: dict[str, str]) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (data.get("sources") == expected_sources
            and bool(re.search(r"ERROR\s+\([A-Z]{2}\d+\)", data.get("error", ""))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rpc", "scratch", "keccak"), required=True)
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--scratch-style", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--place-option", type=int, choices=(0, 1, 2, 3, 4), default=0)
    parser.add_argument("--route-option", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--retry-failures", action="store_true",
                        help="retry a matching build that has a saved failure manifest")
    args = parser.parse_args()

    if args.mode == "keccak":
        from gowin_keccak_build import current_sources
    else:
        from gowin_build import current_sources
    expected_sources = current_sources()

    if args.mode == "rpc":
        configurations = [(rpc, args.scratch_style) for rpc in (1, 2, 3, 4)]
    elif args.mode == "scratch":
        configurations = [(args.rpc, style) for style in (0, 1, 2)]
    else:
        configurations = [(rpc, None) for rpc in (1, 2, 3, 4)]

    failed = False
    for rpc, style in configurations:
        label = f"RPC{rpc}" + (f" scratch{style}" if style is not None else " Keccak OOC")
        print(f"\n=== {label} ===", flush=True)
        if args.mode != "keccak":
            sim = [sys.executable, "scripts/run_verify_sim.py", "--all",
                   "--rpc", str(rpc), "--scratch-style", str(style), "--jobs", "4"]
            if not run(sim):
                print(f"Core regression failed for {label}; continuing to collect other configurations.",
                      flush=True)
                failed = True

        if args.mode == "keccak":
            build_dir = ROOT / f"build/gowin_keccak_rpc{rpc}_p{args.place_option}r{args.route_option}_v2"
            build_script = "scripts/gowin_keccak_build.py"
        else:
            source_tag = hashlib.sha256(
                json.dumps(expected_sources, sort_keys=True).encode("utf-8")
            ).hexdigest()[:10]
            suffix = f"_p{args.place_option}r{args.route_option}_src{source_tag}"
            build_dir = ROOT / f"build/gowin_rpc{rpc}_scratch{style}{suffix}"
            build_script = "scripts/gowin_build.py"
        failure_manifest = build_dir / "gowin_failure_manifest.json"
        if failure_manifest.is_file() and not args.retry_failures:
            failure_data = json.loads(failure_manifest.read_text(encoding="utf-8"))
            if failure_data.get("sources") == expected_sources:
                print(f"Matching failure is already recorded for {label}; skipping identical fit retry.",
                      flush=True)
                continue
        command = [sys.executable, build_script, "--rpc", str(rpc),
                   "--place-option", str(args.place_option),
                   "--route-option", str(args.route_option),
                   "--build-dir", str(build_dir)]
        if style is not None:
            command += ["--scratch-style", str(style)]
        if (build_dir / "build_manifest.json").is_file():
            command.append("--inspect-existing")
        elif (build_dir / "gowin_synthesis_manifest.json").is_file():
            command += ["--reuse-netlist", str(build_dir / "gowin_synthesis_manifest.json")]
        elif reuse_from := reusable_manifest(args.mode, rpc, style, expected_sources):
            command += ["--reuse-netlist", str(reuse_from)]
        if not run(command):
            if recorded_vendor_failure(failure_manifest, expected_sources):
                print(f"Gowin fit failure for {label} is captured; continuing.", flush=True)
            else:
                print(f"Gowin build failed without a recognized vendor fit result for {label}.",
                      flush=True)
                failed = True

    collector = ("scripts/collect_keccak_gowin.py" if args.mode == "keccak"
                 else "scripts/collect_gowin.py")
    if not run([sys.executable, collector]):
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
