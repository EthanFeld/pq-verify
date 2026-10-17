#!/usr/bin/env python3
"""Validate a source-bound Gowin image and load only volatile FPGA SRAM."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from board_build import ROOT
from gowin_build import current_sources, inspect_reports
from tools import resolve_programmer_cli

DEVICE = "GW2AR-18C"
DEVICE_ID = "0x0000081B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/gowin_final")
    parser.add_argument("--cable-index", type=int, default=4)
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--check-only", action="store_true",
                        help="validate the image and scan the device without programming")
    args = parser.parse_args()
    build = args.build_dir if args.build_dir.is_absolute() else ROOT / args.build_dir
    build = build.resolve()

    try:
        manifest_path = build / "build_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("device") != "GW2AR-LV18QN88C8/I7":
            raise ValueError("build manifest does not target GW2AR-LV18QN88C8/I7")
        if manifest.get("sources") != current_sources():
            raise ValueError("image source or constraint hashes are stale")

        bitstream = (build / manifest["bitstream"]).resolve()
        bitstream.relative_to(build)
        if not bitstream.is_file():
            raise ValueError(f"bitstream is missing: {bitstream}")
        if hashlib.sha256(bitstream.read_bytes()).hexdigest() != manifest.get("bitstream_sha256"):
            raise ValueError("bitstream checksum does not match its build manifest")
        fit = inspect_reports(build)

        programmer = Path(resolve_programmer_cli())

        scan_command = [str(programmer), "--scan", "--cable-index", str(args.cable_index),
                        "--channel", str(args.channel)]
        scan = subprocess.run(scan_command, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
        scan_text = scan.stdout + scan.stderr
        (build / "device_scan.txt").write_text(scan_text, encoding="utf-8")
        if scan.returncode or DEVICE_ID not in scan_text or "device(s) found" not in scan_text:
            raise RuntimeError(f"expected {DEVICE} ({DEVICE_ID}) not found on selected cable/channel:\n"
                               f"{scan_text[-3000:]}")

        summary = {"mode": "SRAM", "device": DEVICE, "device_id": DEVICE_ID,
                   "cable_index": args.cable_index, "channel": args.channel,
                   "bitstream": str(bitstream),
                   "bitstream_sha256": manifest["bitstream_sha256"], "fit": fit}
        if args.check_only:
            print(json.dumps(summary, indent=2), flush=True)
            return 0

        console_log = build / "programmer_sram_console.txt"
        cli_report = build / "programmer_sram.txt"
        command = [str(programmer), "--device", DEVICE, "--operation_index", "2",
                   "--fsFile", str(bitstream), "--cable-index", str(args.cable_index),
                   "--channel", str(args.channel), "--output", str(cli_report)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        output = result.stdout + result.stderr
        console_log.write_text(output, encoding="utf-8")
        if (result.returncode or 'Operation "SRAM Program"' not in output
                or "Finished." not in output or not re.search(r"Status Code is: 0x[0-9A-Fa-f]+", output)):
            raise RuntimeError(f"SRAM programming did not report success (exit {result.returncode}):\n"
                               f"{output[-4000:]}")
        if not cli_report.is_file() or not cli_report.stat().st_size:
            cli_report.write_text(output, encoding="utf-8")

        report = {**summary, "programmed": True, "operation": 2,
                  "exit_code": result.returncode, "console_log": str(console_log),
                  "cli_report": str(cli_report)}
        report_path = build / "programmer_report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"SRAM programmed: {DEVICE}; bitstream {bitstream}", flush=True)
        print(f"Programmer console: {console_log}", flush=True)
        print(f"Programming report: {report_path}", flush=True)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired,
            subprocess.SubprocessError) as exc:
        print(f"program-board: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
