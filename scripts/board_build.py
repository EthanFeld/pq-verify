#!/usr/bin/env python3
"""Build the Tang Nano 20K verifier with native tools on Windows or Unix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RTL = (
    "keccak/keccak_round.sv", "keccak/keccak_f1600.sv", "keccak/shake256.sv",
    "slh/adrs.sv", "slh/sig_ram.sv", "slh/scratch_ram.sv", "slh/thash.sv",
    "slh/hmsg.sv", "slh/fors_verify.sv", "slh/wots_verify.sv", "slh/xmss_verify.sv",
    "slh/ht_verify.sv", "slh/slh_verify_top.sv", "io/uart_rx.sv", "io/uart_tx.sv",
    "io/crc8.sv", "io/cmd_ctrl.sv", "top/top_tn20k.sv",
)


def source_hashes() -> dict[str, str]:
    files = [ROOT / "rtl" / name for name in RTL] + [ROOT / "syn/tn20k.cst", ROOT / "syn/tn20k.sdc"]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def synthesis_manifest(build: Path, tag: str, rpc: int, scratch_style: int,
                       hashes: dict[str, str]) -> dict:
    netlist = build / f"{tag}_syn.json"
    verilog = build / f"{tag}.v"
    return {"rpc": rpc, "scratch_style": scratch_style, "sources": hashes,
            "synthesis_file": netlist.name,
            "synthesis_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
            "verilog_file": verilog.name,
            "verilog_sha256": hashlib.sha256(verilog.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("synth", "pnr", "bit"))
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--scratch-style", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--placer-density", type=float, default=0.8,
                        help="maximum analytic placement density (default: 0.8)")
    parser.add_argument("--router", choices=("default", "router1", "router2"), default="default",
                        help="nextpnr routing algorithm (default: device default)")
    parser.add_argument("--reuse-synthesis", type=Path,
                        help="reuse a source- and checksum-verified synthesis manifest")
    args = parser.parse_args()
    if not 0 < args.placer_density <= 1:
        parser.error("--placer-density must be in (0, 1]")
    build = args.build_dir if args.build_dir.is_absolute() else ROOT / args.build_dir
    build.mkdir(parents=True, exist_ok=True)
    tag = f"top_tn20k_rpc{args.rpc}_scratch{args.scratch_style}"
    env = os.environ.copy()
    oss = Path(env.get("YOSYSHQ_ROOT", r"C:\oss-cad-suite\oss-cad-suite"))
    if oss.is_dir():
        env["PATH"] = os.pathsep.join((str(oss / "bin"), str(oss / "lib"), env.get("PATH", "")))
    commands_used: dict[str, list[str]] = {}
    stage_seconds: dict[str, float] = {}

    def tool(variable: str, default: str) -> str:
        name = env.get(variable, default)
        resolved = shutil.which(name, path=env.get("PATH"))
        if resolved:
            return resolved
        candidate = ROOT / name
        if candidate.is_file():
            return str(candidate)
        raise ValueError(f"{variable}: executable not found: {name}")

    def run(stage: str, command: list[str], output: Path | None = None) -> None:
        logfile = build / f"{tag}_{stage}.log"
        stage_env = env.copy()
        executable_dir = Path(command[0]).resolve().parent
        runtime = executable_dir.parent / "lib"
        # Keep each selected tool paired with its own DLL bundle.
        paths = [str(executable_dir)]
        if runtime.is_dir():
            paths.append(str(runtime))
        stage_env["PATH"] = os.pathsep.join((*paths, env.get("PATH", "")))
        commands_used[stage] = command
        print(f"{stage}: running; log {logfile.relative_to(ROOT)}", flush=True)
        started = time.perf_counter()
        with logfile.open("wb") as log:
            if output is None:
                result = subprocess.run(command, cwd=ROOT, env=stage_env, stdout=log, stderr=subprocess.STDOUT)
            else:
                with output.open("wb") as stream:
                    result = subprocess.run(command, cwd=ROOT, env=stage_env, stdout=stream, stderr=log)
        stage_seconds[stage] = round(time.perf_counter() - started, 3)
        if result.returncode:
            tail = logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            raise RuntimeError(f"{stage} failed ({result.returncode})\n" + "\n".join(tail))
        print(f"{stage}: complete", flush=True)

    vfile = build / f"{tag}.v"
    synjson = build / f"{tag}_syn.json"
    pnrjson = build / f"{tag}_pnr.json"
    report = build / f"{tag}_pnr_report.json"
    bit = build / f"{tag}.fs"
    manifest = build / f"{tag}_manifest.json"
    synth_manifest = build / f"{tag}_synthesis_manifest.json"
    try:
        hashes = source_hashes()
        cached = None
        cache_path = args.reuse_synthesis.resolve() if args.reuse_synthesis else synth_manifest
        if cache_path.is_file():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                # Synthesis consumes RTL only; P&R applies the current constraints.
                cached_rtl = {name: digest for name, digest in cache["sources"].items()
                              if name.startswith("rtl/")}
                current_rtl = {name: digest for name, digest in hashes.items() if name.startswith("rtl/")}
                if (cache["rpc"] != args.rpc or cache["scratch_style"] != args.scratch_style
                        or cached_rtl != current_rtl):
                    raise ValueError("cached synthesis configuration or RTL hashes differ")
                netlist_data = (cache_path.parent / cache["synthesis_file"]).read_bytes()
                verilog_data = (cache_path.parent / cache["verilog_file"]).read_bytes()
                if (hashlib.sha256(netlist_data).hexdigest() != cache["synthesis_sha256"]
                        or hashlib.sha256(verilog_data).hexdigest() != cache["verilog_sha256"]):
                    raise ValueError("cached synthesis output checksum mismatch")
                cached = (netlist_data, verilog_data)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                if args.reuse_synthesis:
                    raise
                print(f"synthesis: cache miss at {cache_path}; rebuilding", flush=True)
        # A failed rebuild must not leave an older image looking current.
        for output in (synjson, pnrjson, report, bit, manifest, synth_manifest):
            output.unlink(missing_ok=True)
        if cached is not None:
            synjson.write_bytes(cached[0])
            vfile.write_bytes(cached[1])
            print(f"synthesis: reused verified outputs from {cache_path}", flush=True)
            synthesis_source = str(cache_path)
        else:
            local_sv2v = ROOT / ".tools/sv2v/sv2v-Windows/sv2v.exe"
            sv2v = tool("SV2V", str(local_sv2v) if local_sv2v.is_file() else "sv2v")
            run("sv2v", [sv2v, "-DPQ_GOWIN_LUT4", *[str(ROOT / "rtl" / name) for name in RTL]], vfile)
            commands = (f'read_verilog "{vfile.as_posix()}"; '
                        f"chparam -set RPC {args.rpc} -set SCRATCH_STYLE {args.scratch_style} top_tn20k; "
                        f'synth_gowin -family gw2a -top top_tn20k -json "{synjson.as_posix()}"; check; stat')
            run("yosys", [tool("YOSYS", "yosys"), "-Q", "-p", commands])
            synthesis_source = "rebuilt"
        if source_hashes() != hashes:
            raise RuntimeError("RTL or constraints changed during synthesis; rerun for current outputs")
        synth_manifest.write_text(json.dumps(synthesis_manifest(
            build, tag, args.rpc, args.scratch_style, hashes), indent=2) + "\n", encoding="utf-8")
        if args.mode in ("pnr", "bit"):
            # The global 50.143 MHz target covers the 50.142857 MHz PLL clock
            # and conservatively constrains the 27 MHz lock/reset domain.
            # nextpnr's generic SDC reader does not accept create_generated_clock.
            run("pnr", [tool("NEXTPNR", "nextpnr-himbaechel"), "--json", str(synjson),
                        "--device", "GW2AR-LV18QN88C8/I7", "--vopt", "family=GW2A-18C",
                        "--vopt", "cst=syn/tn20k.cst", "--freq", "50.143", "--write", str(pnrjson),
                        "--report", str(report), "--detailed-timing-report",
                        "--placer-heap-beta", str(args.placer_density), "--router", args.router])
        if args.mode == "bit":
            run("pack", [tool("GOWIN_PACK", "gowin_pack"), "-d", "GW2AR-18C", "-o", str(bit), str(pnrjson)])
        if source_hashes() != hashes:
            bit.unlink(missing_ok=True)
            raise RuntimeError("RTL or constraints changed during the build; rerun for a current image")
        data = {"mode": args.mode, "rpc": args.rpc, "scratch_style": args.scratch_style,
                "device": "GW2AR-LV18QN88C8/I7", "target_mhz": 50.143,
                "placer_density": args.placer_density, "router": args.router, "sources": hashes,
                "commands": commands_used, "synthesis_manifest": synth_manifest.name,
                "synthesis_source": synthesis_source, "stage_seconds": stage_seconds}
        if bit.exists():
            data["bitstream_sha256"] = hashlib.sha256(bit.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        bit.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
