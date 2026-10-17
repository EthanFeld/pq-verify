#!/usr/bin/env python3
"""Fit the isolated Keccak wrapper with Gowin EDA and record its timing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "rtl/keccak/keccak_round.sv",
    "rtl/keccak/keccak_f1600.sv",
    "rtl/top/keccak_ooc_top.sv",
    "syn/keccak_ooc.cst",
    "syn/keccak_ooc.sdc",
    "syn/gowin_keccak_ooc.tcl",
)


def source_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in SOURCES
    }


def specialize_top(path: Path, rpc: int) -> None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^module keccak_ooc_top\s*#?\s*\(.*?^endmodule", text)
    if not match:
        raise ValueError("sv2v output lacks keccak_ooc_top")
    top = match.group(0)
    top, count = re.subn(
        r"(?m)^([ \t]*parameter integer RPC = )\d+(;)$",
        rf"\g<1>{rpc}\2", top, count=1,
    )
    if count != 1:
        raise ValueError("could not specialize the Keccak RPC parameter")
    path.write_text(text[:match.start()] + top + text[match.end():], encoding="utf-8")


def inspect_fit(build: Path) -> dict:
    pnr = build / "keccak_ooc/impl/pnr"
    report = (pnr / "keccak_ooc.rpt.txt").read_text(encoding="utf-8", errors="replace")
    timing = (pnr / "keccak_ooc.tr").read_text(encoding="utf-8", errors="replace")
    fs_files = list(pnr.glob("*.fs"))
    bin_files = list(pnr.glob("*.bin"))
    if len(fs_files) != 1 or len(bin_files) != 1:
        raise ValueError("Gowin P&R output must contain one FS and one binary image")
    fs = fs_files[0]
    binary = bin_files[0]
    match = re.search(r"^\s*Logic\s*\|\s*(\d+)/(\d+)", report, re.M)
    if not match:
        raise ValueError("Gowin resource report lacks Logic utilization")
    logic, logic_available = map(int, match.groups())

    def resource(name: str) -> tuple[int, int]:
        found = re.search(r"^\s*" + re.escape(name) + r"\s*\|\s*(\d+)/(\d+)", report, re.M)
        return tuple(map(int, found.groups())) if found else (0, 0)

    ff, ff_available = resource("--Logic Register as FF")
    bsram, bsram_available = resource("BSRAM")
    dsp, dsp_available = resource("DSP")
    clock = re.search(r"^\s*\d+\s+clk\s+[\d.]+\(MHz\)\s+([\d.]+)\(MHz\)", timing, re.M)
    if not clock:
        raise ValueError("Gowin timing report lacks the clk Fmax")
    violations = {}
    for kind in ("Setup", "Hold"):
        found = re.search(r"<Numbers of " + kind + r" Violated Endpoints>:(\d+)", timing)
        if not found:
            raise ValueError(f"Gowin timing report lacks {kind} violation count")
        violations[kind.lower()] = int(found[1])
    if any(violations.values()):
        raise ValueError(f"Gowin reports timing violations: {violations}")
    fs_header = fs.read_bytes()[:4096].decode("ascii", errors="ignore")
    compression = re.search(r"(?m)^//Compress:\s*(ON|OFF)\s*$", fs_header)
    if not compression:
        raise ValueError("Gowin bitstream lacks a compression status header")
    return {
        "logic_cells": {"used": logic, "available": logic_available},
        "ff": {"used": ff, "available": ff_available},
        "bsram": {"used": bsram, "available": bsram_available},
        "dsp": {"used": dsp, "available": dsp_available},
        "clock": {"name": "clk", "constraint_mhz": 27.0, "fmax_mhz": float(clock[1])},
        "violated_endpoints": violations,
        "bitstream": {
            "binary_bytes": binary.stat().st_size,
            "compression_enabled": compression[1] == "ON",
        },
    }


def write_synthesis_manifest(build: Path, rpc: int, hashes: dict[str, str]) -> Path | None:
    source_path = build / "source_manifest.json"
    converted = build / "keccak_ooc.v"
    netlist = build / "keccak_ooc/impl/gwsynthesis/keccak_ooc.vg"
    if not source_path.is_file() or not converted.is_file() or not netlist.is_file():
        return None
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("rpc") != rpc:
        raise ValueError("Keccak synthesis manifest RPC mismatch")
    current_rtl = {name: digest for name, digest in hashes.items() if name.startswith("rtl/")}
    source_rtl = {name: digest for name, digest in source["sources"].items() if name.startswith("rtl/")}
    if source_rtl != current_rtl:
        raise ValueError("Keccak RTL changed during synthesis")
    data = {
        "rpc": rpc,
        "device": "GW2AR-LV18QN88C8/I7",
        "rtl_sources": current_rtl,
        "verilog_file": "keccak_ooc.v",
        "verilog_sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
        "netlist_file": "keccak_ooc/impl/gwsynthesis/keccak_ooc.vg",
        "netlist_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
    }
    manifest = build / "gowin_synthesis_manifest.json"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--place-option", type=int, choices=(0, 1, 2, 3, 4), default=0)
    parser.add_argument("--route-option", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--reuse-netlist", type=Path,
                        help="reuse a checksum-verified Gowin synthesis manifest")
    parser.add_argument("--inspect-existing", action="store_true")
    args = parser.parse_args()
    build = (args.build_dir or ROOT / f"build/gowin_keccak_rpc{args.rpc}").resolve()
    manifest = build / "build_manifest.json"
    bitstream = build / "keccak_ooc/impl/pnr/keccak_ooc.fs"
    stages: dict[str, float] = {}
    try:
        if args.inspect_existing:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if (data.get("sources") != source_hashes() or data.get("rpc") != args.rpc
                    or data.get("place_option") != args.place_option
                    or data.get("route_option") != args.route_option):
                raise ValueError("Keccak fit source/configuration differs from the request")
            bitstream = build / data.get("bitstream_file", "keccak_ooc/impl/pnr/keccak_ooc.fs")
            if hashlib.sha256(bitstream.read_bytes()).hexdigest() != data["bitstream_sha256"]:
                raise ValueError("Keccak bitstream checksum mismatch")
            data["fit"] = inspect_fit(build)
            manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(data["fit"], indent=2), flush=True)
            return 0
        if manifest.exists() or bitstream.exists():
            raise ValueError("existing fit preserved; choose a new --build-dir")
        gowin = Path(os.environ.get("GOWIN_HOME", r"C:\Gowin\Gowin_V1.9.11.03_Education_x64"))
        shell = gowin / "IDE/bin/gw_sh.exe"
        if not shell.is_file():
            raise ValueError(f"Gowin command-line tool missing: {shell}")
        local_sv2v = ROOT / ".tools/sv2v/sv2v-Windows/sv2v.exe"
        sv2v = os.environ.get("SV2V") or shutil.which("sv2v")
        if not sv2v and local_sv2v.is_file():
            sv2v = str(local_sv2v)
        if not sv2v:
            raise ValueError("sv2v is required")
        build.mkdir(parents=True, exist_ok=True)
        hashes = source_hashes()
        converted = build / "keccak_ooc.v"
        reuse_netlist_path = None
        if args.reuse_netlist:
            cache_path = args.reuse_netlist.resolve()
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            current_rtl = {name: digest for name, digest in hashes.items() if name.startswith("rtl/")}
            if (cache.get("rpc") != args.rpc or cache.get("device") != "GW2AR-LV18QN88C8/I7"
                    or cache.get("rtl_sources") != current_rtl):
                raise ValueError("cached Keccak netlist configuration or RTL hashes differ")
            cached_netlist = (cache_path.parent / cache["netlist_file"]).read_bytes()
            cached_verilog = (cache_path.parent / cache["verilog_file"]).read_bytes()
            if (hashlib.sha256(cached_netlist).hexdigest() != cache["netlist_sha256"]
                    or hashlib.sha256(cached_verilog).hexdigest() != cache["verilog_sha256"]):
                raise ValueError("cached Keccak synthesis output checksum mismatch")
            cache_dir = ROOT / "build/gowin_keccak_synthesis_cache" / f"rpc{args.rpc}_{cache['netlist_sha256']}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            reuse_netlist_path = cache_dir / "keccak_ooc.vg"
            if not reuse_netlist_path.exists():
                reuse_netlist_path.write_bytes(cached_netlist)
            converted.write_bytes(cached_verilog)
            reuse_record = dict(cache)
            reuse_record["netlist_file"] = str(reuse_netlist_path.resolve())
            reuse_record["verilog_file"] = converted.name
            (build / "gowin_synthesis_manifest.json").write_text(
                json.dumps(reuse_record, indent=2) + "\n", encoding="utf-8")
            stages["synthesis_reused"] = 0.0
        else:
            started = time.perf_counter()
            with converted.open("wb") as output, (build / "sv2v.log").open("wb") as log:
                subprocess.run([sv2v, "-DPQ_GOWIN_LUT4", *[str(ROOT / name) for name in SOURCES[:3]]], cwd=ROOT,
                               stdout=output, stderr=log, check=True)
            stages["sv2v"] = round(time.perf_counter() - started, 3)
            specialize_top(converted, args.rpc)
        (build / "source_manifest.json").write_text(json.dumps({
            "rpc": args.rpc, "sources": hashes,
        }, indent=2) + "\n", encoding="utf-8")
        env = os.environ.copy()
        env["PQ_VERIFY_BUILD_DIR"] = str(build)
        env["PQ_VERIFY_PLACE_OPTION"] = str(args.place_option)
        env["PQ_VERIFY_ROUTE_OPTION"] = str(args.route_option)
        if reuse_netlist_path:
            env["PQ_VERIFY_REUSE_NETLIST"] = str(reuse_netlist_path)
        started = time.perf_counter()
        try:
            with (build / "build.log").open("wb") as log:
                result = subprocess.run([str(shell), str(ROOT / "syn/gowin_keccak_ooc.tcl")],
                                        cwd=build, env=env, stdout=log, stderr=subprocess.STDOUT)
        finally:
            stages["gowin_fit_pack"] = round(time.perf_counter() - started, 3)
        if not args.reuse_netlist:
            write_synthesis_manifest(build, args.rpc, hashes)
        bitstreams = list((build / "keccak_ooc/impl/pnr").glob("*.fs"))
        if len(bitstreams) != 1:
            raise ValueError("Gowin did not emit exactly one Keccak image")
        bitstream = bitstreams[0]
        if result.returncode or not bitstream.is_file():
            tail = (build / "build.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            raise RuntimeError(f"Gowin Keccak fit failed ({result.returncode})\n" + "\n".join(tail))
        if source_hashes() != hashes:
            bitstream.unlink()
            raise RuntimeError("Keccak RTL or constraints changed during the build")
        data = {
            "rpc": args.rpc,
            "device": "GW2AR-LV18QN88C8/I7",
            "place_option": args.place_option,
            "route_option": args.route_option,
            "sources": hashes,
            "verilog_sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
            "fit": inspect_fit(build),
            "stage_seconds": stages,
            "bitstream_file": str(bitstream.relative_to(build)).replace("\\", "/"),
            "bitstream_sha256": hashlib.sha256(bitstream.read_bytes()).hexdigest(),
        }
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data["fit"], indent=2), flush=True)
    except KeyboardInterrupt:
        if not args.inspect_existing and not args.reuse_netlist and "hashes" in locals():
            try:
                write_synthesis_manifest(build, args.rpc, hashes)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if not args.inspect_existing:
            try:
                (build / "gowin_failure_manifest.json").write_text(json.dumps({
                    "rpc": args.rpc, "place_option": args.place_option,
                    "route_option": args.route_option,
                    "error": "Gowin Keccak fit interrupted", "stage_seconds": stages,
                }, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
        print("Gowin Keccak fit interrupted", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
