#!/usr/bin/env python3
"""Build a parameterized Tang Nano 20K verifier image with Gowin EDA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from board_build import ROOT, RTL, source_hashes
from tools import resolve_gw_sh, resolve_sv2v

EXPECTED_UNCOMPRESSED_BYTES = 907_418


def inspect_reports(build: Path) -> dict:
    directory = build / "pq_verify/impl/pnr"
    resources = (directory / "pq_verify.rpt.txt").read_text(encoding="utf-8", errors="replace")
    timing = (directory / "pq_verify.tr").read_text(encoding="utf-8", errors="replace")
    bitstream_fs = directory / "pq_verify.fs"
    bitstream_bin = directory / "pq_verify.bin"
    process_config = json.loads(
        (build / "pq_verify/impl/pq_verify_process_config.json").read_text(encoding="utf-8"))
    compression_flag = re.search(r"(?m)^//Compress:\s*(ON|OFF)\s*$",
                                 bitstream_fs.read_bytes()[:4096].decode("ascii", errors="ignore"))
    if not compression_flag:
        raise ValueError("vendor bitstream lacks its compression status header")
    binary_size = bitstream_bin.stat().st_size
    compressed = compression_flag[1] == "ON"
    if not compressed and binary_size != EXPECTED_UNCOMPRESSED_BYTES:
        raise ValueError(
            "uncompressed GW2AR-18 bitstream must be "
            f"{EXPECTED_UNCOMPRESSED_BYTES:,} bytes; got {binary_size:,}"
        )

    def resource(name: str) -> dict[str, int]:
        match = re.search(r"^\s*" + re.escape(name) + r"\s*\|\s*(\d+)/(\d+)", resources, re.M)
        if not match:
            raise ValueError(f"vendor report lacks resource {name}")
        used, available = map(int, match.groups())
        return {"used": used, "available": available}

    usage = {key: resource(name) for key, name in (
        ("logic", "Logic"), ("ff", "--Logic Register as FF"),
        ("io_ff", "--I/O Register as FF"), ("bsram", "BSRAM"), ("dsp", "DSP"), ("cls", "CLS"))}
    ssram = re.search(r"^\s*--SSRAM\(RAM16\)\s*\|\s*(\d+)", resources, re.M)
    if not ssram:
        raise ValueError("vendor report lacks SSRAM usage")
    usage["ssram"] = {"used": int(ssram[1]), "available": None}
    clocks = {}
    for match in re.finditer(r"^\s*\d+\s+(clk_27|core_clk)\s+([\d.]+)\(MHz\)\s+([\d.]+)\(MHz\)", timing, re.M):
        clocks[match[1]] = {"constraint_mhz": float(match[2]), "fmax_mhz": float(match[3])}
    if set(clocks) != {"clk_27", "core_clk"}:
        raise ValueError("vendor timing report lacks both clock frequencies")
    violations = {}
    for kind in ("Setup", "Hold"):
        match = re.search(r"<Numbers of " + kind + r" Violated Endpoints>:(\d+)", timing)
        if not match:
            raise ValueError(f"vendor report lacks {kind} violation count")
        violations[kind.lower()] = int(match[1])
    if any(violations.values()):
        raise ValueError(f"vendor timing violations remain: {violations}")
    for name, values in clocks.items():
        if values["fmax_mhz"] <= values["constraint_mhz"]:
            raise ValueError(f"{name} fails its frequency constraint")
    for category in ("logic", "ff"):
        if usage[category]["used"] >= 0.85 * usage[category]["available"]:
            raise ValueError(f"vendor {category} utilization fails the 85% gate")
    for name, pin in (("clk_27", 4), ("uart_rx_pin", 70), ("uart_tx_pin", 69)):
        if not re.search(r"^\s*" + name + r"\s*\|\s*-\s*\|\s*" + str(pin) + r"/", resources, re.M):
            raise ValueError(f"vendor pin report does not match {name} = {pin}")
    slack = re.search(r"3\.1\.1 Setup Paths Table.*?^\s*1\s+(-?[\d.]+)\s", timing, re.M | re.S)
    if not slack or float(slack[1]) <= 0:
        raise ValueError("vendor report lacks positive setup slack")
    core = clocks["core_clk"]
    margin = 1 - core["constraint_mhz"] / core["fmax_mhz"]
    return {"resources": usage, "clocks": clocks, "violated_endpoints": violations,
            "worst_setup_slack_ns": float(slack[1]), "core_clock_margin_fraction": margin,
            "recommended_10pct_margin": margin >= 0.1,
            "configuration_bitstream": {
                "binary_bytes": binary_size,
                "expected_uncompressed_bytes": EXPECTED_UNCOMPRESSED_BYTES,
                "compression_requested": bool(process_config.get("COMPRESS", False)),
                "compression_enabled_in_output": compressed,
            }}


def current_sources() -> dict[str, str]:
    hashes = source_hashes()
    hashes["syn/gowin_build.tcl"] = hashlib.sha256((ROOT / "syn/gowin_build.tcl").read_bytes()).hexdigest()
    return hashes


def specialize_top(converted: Path, rpc: int, scratch_style: int) -> None:
    """Set only top_tn20k defaults, keeping its hierarchy and constrained nets intact."""
    text = converted.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^module top_tn20k\s*\(.*?^endmodule", text)
    if not match:
        raise ValueError("sv2v output lacks the top_tn20k module")
    top = match.group(0)
    top, rpc_count = re.subn(
        r"(?m)^([ \t]*parameter integer RPC = )\d+(;)$",
        rf"\g<1>{rpc}\2", top, count=1,
    )
    top, style_count = re.subn(
        r"(?m)^([ \t]*parameter integer SCRATCH_STYLE = )\d+(;)$",
        rf"\g<1>{scratch_style}\2", top, count=1,
    )
    if rpc_count != 1 or style_count != 1:
        raise ValueError("could not uniquely specialize RPC and SCRATCH_STYLE in top_tn20k")
    converted.write_text(text[:match.start()] + top + text[match.end():], encoding="utf-8")


def write_synthesis_manifest(build: Path, rpc: int, scratch_style: int,
                             hashes: dict[str, str]) -> Path | None:
    """Preserve a verified Gowin netlist even when later routing fails."""
    converted = build / "verifier.v"
    netlist = build / "pq_verify/impl/gwsynthesis/pq_verify.vg"
    source_manifest = build / "source_manifest.json"
    if not converted.is_file() or not netlist.is_file() or not source_manifest.is_file():
        return None
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    if source.get("rpc") != rpc or source.get("scratch_style") != scratch_style:
        raise ValueError("synthesis source manifest configuration mismatch")
    current_rtl = {name: digest for name, digest in hashes.items() if name.startswith("rtl/")}
    source_rtl = {name: digest for name, digest in source["sources"].items() if name.startswith("rtl/")}
    if source_rtl != current_rtl:
        raise ValueError("RTL changed during Gowin synthesis")
    data = {
        "rpc": rpc,
        "scratch_style": scratch_style,
        "device": "GW2AR-LV18QN88C8/I7",
        "rtl_sources": current_rtl,
        "verilog_file": "verifier.v",
        "verilog_sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
        "netlist_file": "pq_verify/impl/gwsynthesis/pq_verify.vg",
        "netlist_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
    }
    manifest = build / "gowin_synthesis_manifest.json"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/gowin_final")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--scratch-style", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--place-option", type=int, choices=(0, 1, 2, 3, 4), default=0)
    parser.add_argument("--route-option", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--reuse-netlist", type=Path,
                        help="reuse a checksum-verified Gowin synthesis manifest")
    parser.add_argument("--inspect-existing", action="store_true",
                        help="check a completed image's identity, resources, pins and timing")
    args = parser.parse_args()
    build = args.build_dir.resolve()
    project = build / "pq_verify"
    bitstream = project / "impl/pnr/pq_verify.fs"
    manifest = build / "build_manifest.json"
    script = ROOT / "syn/gowin_build.tcl"
    stage_seconds: dict[str, float] = {}
    try:
        if args.inspect_existing:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["sources"] != current_sources():
                raise ValueError("image sources or constraints differ from the current checkout")
            if (data.get("rpc", 1) != args.rpc or data.get("scratch_style", 0) != args.scratch_style):
                raise ValueError("image RPC or scratch-style configuration differs from the request")
            if (data.get("place_option", 0) != args.place_option
                    or data.get("route_option", 0) != args.route_option):
                raise ValueError("image placement/routing options differ from the request")
            if hashlib.sha256(bitstream.read_bytes()).hexdigest() != data["bitstream_sha256"]:
                raise ValueError("image checksum mismatch")
            data["fit"] = inspect_reports(build)
            manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(data["fit"], indent=2), flush=True)
            return 0
        if manifest.exists() or bitstream.exists():
            raise ValueError("existing image preserved; choose a new --build-dir")
        shell = Path(resolve_gw_sh())
        sv2v = resolve_sv2v()
        build.mkdir(parents=True, exist_ok=True)
        hashes = current_sources()
        (build / "source_manifest.json").write_text(json.dumps({
            "rpc": args.rpc, "scratch_style": args.scratch_style, "sources": hashes,
        }, indent=2) + "\n", encoding="utf-8")
        converted = build / "verifier.v"
        synthesis_source = "fresh"
        reuse_netlist_path = None
        if args.reuse_netlist:
            cache_path = args.reuse_netlist.resolve()
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            current_rtl = {name: digest for name, digest in hashes.items() if name.startswith("rtl/")}
            if (cache.get("rpc") != args.rpc or cache.get("scratch_style") != args.scratch_style
                    or cache.get("device") != "GW2AR-LV18QN88C8/I7"
                    or cache.get("rtl_sources") != current_rtl):
                raise ValueError("cached Gowin netlist configuration or RTL hashes differ")
            cached_netlist = (cache_path.parent / cache["netlist_file"]).read_bytes()
            cached_verilog = (cache_path.parent / cache["verilog_file"]).read_bytes()
            if (hashlib.sha256(cached_netlist).hexdigest() != cache["netlist_sha256"]
                    or hashlib.sha256(cached_verilog).hexdigest() != cache["verilog_sha256"]):
                raise ValueError("cached Gowin synthesis output checksum mismatch")
            cache_dir = ROOT / "build/gowin_synthesis_cache" / f"rpc{args.rpc}_scratch{args.scratch_style}_{cache['netlist_sha256']}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            reuse_netlist_path = cache_dir / "pq_verify.vg"
            if not reuse_netlist_path.exists():
                reuse_netlist_path.write_bytes(cached_netlist)
            converted.write_bytes(cached_verilog)
            reuse_record = dict(cache)
            reuse_record["netlist_file"] = str(reuse_netlist_path.resolve())
            reuse_record["verilog_file"] = converted.name
            (build / "gowin_synthesis_manifest.json").write_text(
                json.dumps(reuse_record, indent=2) + "\n", encoding="utf-8")
            synthesis_source = str(cache_path)
            stage_seconds["synthesis_reused"] = 0.0
        else:
            started = time.perf_counter()
            with converted.open("wb") as output, (build / "sv2v.log").open("wb") as log:
                subprocess.run([sv2v, "-DPQ_GOWIN_LUT4", *[str(ROOT / "rtl" / name) for name in RTL]], cwd=ROOT,
                               stdout=output, stderr=log, check=True)
            stage_seconds["sv2v"] = round(time.perf_counter() - started, 3)
            started = time.perf_counter()
            specialize_top(converted, args.rpc, args.scratch_style)
            stage_seconds["specialize_parameters"] = round(time.perf_counter() - started, 3)
        env = os.environ.copy()
        env["PQ_VERIFY_BUILD_DIR"] = str(build)
        env["PQ_VERIFY_RPC"] = str(args.rpc)
        env["PQ_VERIFY_SCRATCH_STYLE"] = str(args.scratch_style)
        env["PQ_VERIFY_PLACE_OPTION"] = str(args.place_option)
        env["PQ_VERIFY_ROUTE_OPTION"] = str(args.route_option)
        if reuse_netlist_path:
            env["PQ_VERIFY_REUSE_NETLIST"] = str(reuse_netlist_path)
        print(f"Gowin build: {build}; log {build / 'build.log'}", flush=True)
        started = time.perf_counter()
        try:
            with (build / "build.log").open("wb") as log:
                result = subprocess.run([str(shell), str(script)], cwd=build, env=env,
                                        stdout=log, stderr=subprocess.STDOUT)
        finally:
            stage_seconds["gowin_fit_pack"] = round(time.perf_counter() - started, 3)
        if not args.reuse_netlist:
            write_synthesis_manifest(build, args.rpc, args.scratch_style, hashes)
        if result.returncode or not bitstream.is_file():
            tail = (build / "build.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            raise RuntimeError(f"Gowin build failed ({result.returncode})\n" + "\n".join(tail))
        if current_sources() != hashes:
            bitstream.unlink()
            raise RuntimeError("RTL or constraints changed during the build; current image required")
        data = {"device": "GW2AR-LV18QN88C8/I7", "rpc": args.rpc,
                "scratch_style": args.scratch_style,
                "place_option": args.place_option, "route_option": args.route_option,
                "tool": str(shell), "sources": hashes,
                "synthesis_source": synthesis_source,
                "fit": inspect_reports(build),
                "verilog_sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
                "stage_seconds": stage_seconds,
                "bitstream": str(bitstream.relative_to(build)).replace("\\", "/"),
                "bitstream_sha256": hashlib.sha256(bitstream.read_bytes()).hexdigest()}
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Image: {bitstream}", flush=True)
        print("Inspect the vendor resource and timing reports before hardware use.", flush=True)
    except KeyboardInterrupt:
        message = "Gowin fit interrupted"
        if not args.inspect_existing and not args.reuse_netlist and "hashes" in locals():
            try:
                write_synthesis_manifest(build, args.rpc, args.scratch_style, hashes)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if not args.inspect_existing:
            try:
                (build / "gowin_failure_manifest.json").write_text(json.dumps({
                    "rpc": args.rpc, "scratch_style": args.scratch_style,
                    "place_option": args.place_option, "route_option": args.route_option,
                    "error": message, "stage_seconds": stage_seconds,
                }, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
        print(message, file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        if not args.inspect_existing and not args.reuse_netlist and "hashes" in locals():
            try:
                write_synthesis_manifest(build, args.rpc, args.scratch_style, hashes)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if not args.inspect_existing:
            try:
                failure = {
                    "rpc": args.rpc,
                    "scratch_style": args.scratch_style,
                    "place_option": args.place_option,
                    "route_option": args.route_option,
                    "error": str(exc),
                    "stage_seconds": stage_seconds,
                    "synthesis_source": locals().get("synthesis_source", "unknown"),
                }
                if "hashes" in locals():
                    failure["sources"] = hashes
                (build / "gowin_failure_manifest.json").write_text(
                    json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
