#!/usr/bin/env python3
"""Map and route isolated Keccak variants with native Yosys and nextpnr."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
from tools import resolve_nextpnr, resolve_sv2v, resolve_yosys, tool_environment
RTL = ("rtl/keccak/keccak_round.sv", "rtl/keccak/keccak_f1600.sv", "rtl/top/keccak_ooc_top.sv")
SOURCES = (*RTL, "syn/keccak_ooc.cst", "syn/keccak_ooc.sdc")
DEFINE = "PQ_GOWIN_LUT4"
TIMING_PROFILES = {"all_lut4_v1", "all_lut4_v2", "all_lut4_v3", "all_lut4_v4"}
CONGESTION_SETTINGS = {
    "router2/initCurrCongWeight": "10.000000", "router2/histCongWeight": "1.000000",
    "router2/currCongWeightMult": "2.000000", "router2/estimateWeight": "1.000000",
    "router2/bwdMaxIter": "200", "router2/glbBwdMaxIter": "800",
    "router2/bbMargin/x": "6", "router2/bbMargin/y": "6",
}


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    return {name: checksum(ROOT / name) for name in SOURCES}


def tool_environment(executable: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [executable.parent, executable.parent.parent / "lib"]
    env["PATH"] = os.pathsep.join((*map(str, paths), env.get("PATH", "")))
    return env


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def version(executable: Path) -> str:
    result = subprocess.run([str(executable), "--version"], cwd=ROOT,
                            env=tool_environment(executable), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=20, check=True)
    return result.stdout.strip().splitlines()[0]


def run(command: list[str], log: Path, timeout: int, output: Path | None = None) -> float:
    started = time.perf_counter()
    env = tool_environment(Path(command[0]))
    with log.open("wb") as stream:
        if output is None:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        else:
            with output.open("wb") as converted:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=converted,
                                        stderr=stream, timeout=timeout)
    if result.returncode:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}):\n" + "\n".join(tail))
    return round(time.perf_counter() - started, 3)


def mapped_resources(path: Path, *, require_full_timing: bool = False) -> dict[str, int]:
    modules = json.loads(path.read_text(encoding="utf-8"))["modules"]
    if "keccak_ooc_top" in modules:
        module = modules["keccak_ooc_top"]
    elif len(modules) == 1:
        module = next(iter(modules.values()))
    else:
        raise ValueError(f"missing isolated Keccak top module: {path}")
    cells = module["cells"]
    types = [cell["type"] for cell in cells.values()]
    if any(kind.startswith("MUX2_LUT") for kind in types):
        raise ValueError("unexpected wide LUT mux in the compact Keccak mapping")
    if require_full_timing and any(kind in {"LUT1", "LUT2", "LUT3"} for kind in types):
        raise ValueError(f"small LUT cells lack timing arcs: {path}")
    return {"lut4": sum(kind in {"LUT1", "LUT2", "LUT3", "LUT4"} for kind in types),
            "ff": sum(kind.startswith("DFF") for kind in types)}


def share_theta_parities(module: dict) -> int:
    """Restore common column differences to reduce routing demand."""
    cells = module["cells"]
    groups = defaultdict(list)
    for name, cell in cells.items():
        if (".u_theta." in name and cell["type"] == "LUT3"
                and cell["parameters"]["INIT"] == "10010110"):
            key = (tuple(cell["connections"]["I0"]), tuple(cell["connections"]["I1"]))
            groups[key].append(name)
    numbers = [bit for cell in cells.values() for bits in cell["connections"].values()
               for bit in bits if isinstance(bit, int)]
    numbers += [bit for net in module["netnames"].values() for bit in net["bits"] if isinstance(bit, int)]
    next_bit = max(numbers) + 1
    added = 0
    for pair, names in sorted(groups.items(), key=lambda item: str(item[0])):
        if len(names) < 3:
            continue
        name = f"$pq_theta_shared${added}"
        if name in cells:
            raise ValueError("Theta sharing name collision")
        cells[name] = {"hide_name": 0, "type": "LUT2", "parameters": {"INIT": "0110"},
                       "attributes": {}, "port_directions": {"I0": "input", "I1": "input", "F": "output"},
                       "connections": {"I0": list(pair[0]), "I1": list(pair[1]), "F": [next_bit]}}
        module["netnames"][name] = {"hide_name": 0, "bits": [next_bit], "attributes": {}}
        for original_name in names:
            cell = cells[original_name]
            old_truth = int(cell["parameters"]["INIT"], 2)
            for address in range(8):
                parity = (6 >> (address & 3)) & 1
                result = (6 >> (((address >> 2) & 1) | (parity << 1))) & 1
                if result != ((old_truth >> address) & 1):
                    raise ValueError("Theta factoring changed its function")
            a, output = cell["connections"]["I2"], cell["connections"]["F"]
            cell["type"] = "LUT2"
            cell["parameters"]["INIT"] = "0110"
            cell["connections"] = {"I0": a, "I1": [next_bit], "F": output}
            cell["port_directions"] = {"I0": "input", "I1": "input", "F": "output"}
        next_bit += 1
        added += 1
    if not added:
        raise ValueError("no shared Theta groups found")
    return added


def normalize_timing_luts(source: Path, output: Path, *, balance_pins: bool = False,
                          share_theta: bool = False, routing_settings: dict | None = None) -> int:
    """Use the Gowin database's LUT4 timing model for every physical LUT.

    The backend's database has LUT4 arcs but no LUT1/2/3 variants. Repeating
    the smaller truth table preserves its function for every unused input.
    """
    design = json.loads(source.read_text(encoding="utf-8"))
    if share_theta:
        shared = share_theta_parities(design["modules"]["keccak_ooc_top"])
        print(f"Shared {shared} Theta column differences", flush=True)
    changed = 0
    for name, cell in design["modules"]["keccak_ooc_top"]["cells"].items():
        if cell["type"] not in ("LUT1", "LUT2", "LUT3", "LUT4"):
            continue
        if cell["type"] == "LUT4" and not balance_pins:
            continue
        inputs = int(cell["type"][3:])
        truth = cell["parameters"]["INIT"]
        if len(truth) != 1 << inputs or set(truth) - {"0", "1"}:
            raise ValueError("unexpected LUT truth-table encoding")
        expanded = truth * (16 // len(truth))
        cell["type"] = "LUT4"
        cell["parameters"]["INIT"] = expanded
        # Unused inputs remain absent, as for the original LUT1/2/3 cell.
        # Repeated INIT halves make their value irrelevant. Grounding these
        # pins creates thousands of unnecessary routes at higher RPC.
        if balance_pins:
            rotation = hashlib.sha256(name.encode("utf-8")).digest()[0] & 3
            before = int(expanded, 2)
            after = 0
            for address in range(16):
                original_address = sum(((address >> ((bit + rotation) & 3)) & 1) << bit
                                       for bit in range(4))
                after |= ((before >> original_address) & 1) << address
            cell["parameters"]["INIT"] = f"{after:016b}"
            connections = cell["connections"]
            directions = cell["port_directions"]
            old_inputs = {port: value for port, value in connections.items()
                          if port in {"I0", "I1", "I2", "I3"}}
            for port in old_inputs:
                del connections[port]
                del directions[port]
            for port, value in old_inputs.items():
                new_port = f"I{(int(port[1]) + rotation) & 3}"
                connections[new_port] = value
                directions[new_port] = "input"
            # Prove the pin/truth-table permutation for all binary addresses.
            for address in range(16):
                new_address = sum(((address >> bit) & 1) << ((bit + rotation) & 3)
                                  for bit in range(4))
                if ((before >> address) & 1) != ((after >> new_address) & 1):
                    raise ValueError(f"LUT pin permutation changed its function: {name}")
        changed += inputs < 4
    if routing_settings:
        design["modules"]["keccak_ooc_top"].setdefault("settings", {}).update(routing_settings)
    write_json(output, design)
    return changed


def fit_result(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    clocks = report.get("fmax", {})
    if len(clocks) != 1:
        raise ValueError(f"expected one Keccak clock, found {list(clocks)}")
    clock_name, clock = next(iter(clocks.items()))
    frequency = float(clock["achieved"])
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("nextpnr reported an invalid achieved frequency")
    usage = report["utilization"]
    return {"lut4": int(usage["LUT4"]["used"]), "ff": int(usage["DFF"]["used"]),
            "bsram": int(usage["BSRAM"]["used"]), "lutram": int(usage["RAM16SDP4"]["used"]),
            "fmax_mhz": frequency, "clock_name": clock_name,
            "clock_constraint_mhz": float(clock["constraint"])}


def export_rows(build: Path, output: Path, hashes: dict[str, str]) -> list[dict]:
    rows = []
    for path in sorted(build.glob("rpc*/manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("sources") != hashes or data.get("lut_timing") not in TIMING_PROFILES:
            continue
        for name, digest in data["outputs"].items():
            if checksum(path.parent / name) != digest:
                raise ValueError(f"completed Keccak output checksum mismatch: {path.parent / name}")
        implementation = mapped_resources(path.parent / "timing_netlist.json", require_full_timing=True)
        mapped_resources(path.parent / "routed.json", require_full_timing=True)
        fit = fit_result(path.parent / "pnr_report.json")
        rpc = data["rpc"]
        rows.append({"config": f"keccak_ooc_rpc{rpc}", "rpc": rpc, **fit,
                     "timing_met": fit["fmax_mhz"] >= fit["clock_constraint_mhz"],
                     "permutation_cycles": 24 // rpc,
                     "permutation_latency_at_fmax_us": (24 // rpc) / fit["fmax_mhz"],
                     "synthesis_lut4": data["synthesis"]["lut4"],
                     "implementation_lut4": implementation["lut4"],
                     "synthesis_ff": data["synthesis"]["ff"],
                     "pnr_seconds": data["seconds"]["pnr"],
                     "manifest": str(path.relative_to(ROOT)).replace("\\", "/")})
    if not rows:
        raise ValueError("no source-matched completed Keccak routes")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", type=int, nargs="+", choices=(1, 2, 3, 4), default=[1, 2, 4])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/keccak_seeded_final")
    parser.add_argument("--output", type=Path, default=ROOT / "bench/keccak_measurements.csv")
    parser.add_argument("--timeout", type=int, default=1200, help="maximum seconds per tool invocation")
    parser.add_argument("--router", choices=("auto", "router1", "router2"), default="auto")
    parser.add_argument("--placer-density", type=float)
    parser.add_argument("--timing-driven", action=argparse.BooleanOptionalAction, default=None,
                        help="optimize placement/routing for timing (default: RPC1/2/3 on, RPC4 off)")
    parser.add_argument("--no-tmdriv", dest="timing_driven", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--placer", choices=("heap", "sa"), default="heap")
    parser.add_argument("--router2-alt-weights", action="store_true")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--balance-lut-pins", action=argparse.BooleanOptionalAction, default=None,
                        help="balance physical LUT pins (default: RPC4)")
    parser.add_argument("--share-theta", action=argparse.BooleanOptionalAction, default=None,
                        help="share Theta column differences to reduce fanout (default: RPC4)")
    parser.add_argument("--congestion-first", action="store_true", help="use stronger router2 history and a wider search")
    parser.add_argument("--congestion-maps", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or (args.placer_density is not None and not 0 < args.placer_density <= 1):
        parser.error("timeout must be positive and placement density must be in (0, 1]")
    build = args.build_dir.resolve()
    hashes = source_hashes()
    try:
        if not args.collect_only:
            env = tool_environment()
            yosys = Path(resolve_yosys(env))
            nextpnr = Path(resolve_nextpnr(env))
            sv2v = Path(resolve_sv2v(env))
            tools = {name: {"path": str(executable), "version": version(executable)}
                     for name, executable in (("yosys", yosys), ("nextpnr", nextpnr), ("sv2v", sv2v))}
            for rpc in dict.fromkeys(args.rpc):
                balance_pins = args.balance_lut_pins if args.balance_lut_pins is not None else rpc == 4
                share_theta = args.share_theta if args.share_theta is not None else rpc == 4
                timing_driven = args.timing_driven if args.timing_driven is not None else rpc != 4
                if share_theta and not balance_pins:
                    raise ValueError("Theta sharing requires balanced pins; use --balance-lut-pins or --no-share-theta")
                directory = build / f"rpc{rpc}"
                directory.mkdir(parents=True, exist_ok=True)
                density = args.placer_density or 0.65
                router = ("router1" if rpc <= 2 else "router2") if args.router == "auto" else args.router
                configuration = {"rpc": rpc, "sources": hashes, "defines": [DEFINE],
                                 "family": "gw2a", "wide_luts": False,
                                 "lut_timing": "all_lut4_v4" if share_theta else
                                               "all_lut4_v3" if balance_pins else "all_lut4_v2",
                                 "router": router, "placer_density": density,
                                 "clock_constraint_mhz": 27.0,
                                 # This option also controls timing-driven routing.
                                 "timing_driven_placement": timing_driven,
                                 "placer": args.placer, "router2_alternate_weights": args.router2_alt_weights,
                                 "seed": args.seed,
                                 "router_settings": CONGESTION_SETTINGS if args.congestion_first else {}}
                manifest = directory / "manifest.json"
                if manifest.is_file():
                    previous = json.loads(manifest.read_text(encoding="utf-8"))
                    for key, default in {"timing_driven_placement": True, "placer": "heap",
                                         "router2_alternate_weights": False, "seed": 1,
                                         "router_settings": {}}.items():
                        previous.setdefault(key, default)
                    if any(previous.get(key) != value for key, value in configuration.items()):
                        raise ValueError(f"completed route preserved; use a new --build-dir: {directory}")
                    print(f"RPC{rpc}: reusing completed source-matched route", flush=True)
                    continue
                netlist = directory / "synthesis.json"
                converted = directory / "keccak.v"
                synth_manifest = directory / "synthesis_manifest.json"
                seconds = {}
                if synth_manifest.is_file():
                    cache = json.loads(synth_manifest.read_text(encoding="utf-8"))
                    if (cache.get("rpc") != rpc or cache.get("sources") != hashes
                            or cache.get("defines") != [DEFINE]
                            or cache.get("yosys_version") != tools["yosys"]["version"]
                            or cache["netlist_sha256"] != checksum(netlist)
                            or cache["verilog_sha256"] != checksum(converted)):
                        raise ValueError(f"cached synthesis differs; use a new --build-dir: {directory}")
                    print(f"RPC{rpc}: reusing checked synthesis", flush=True)
                else:
                    print(f"RPC{rpc}: converting RTL", flush=True)
                    seconds["sv2v"] = run([str(sv2v), f"-D{DEFINE}", *[str(ROOT / name) for name in RTL]],
                                          directory / "sv2v.log", args.timeout, converted)
                    script = (f'read_verilog "{converted.as_posix()}"; '
                              f"chparam -set RPC {rpc} keccak_ooc_top; "
                              "synth_gowin -family gw2a -nowidelut -top keccak_ooc_top "
                              f'-json "{netlist.as_posix()}"; check; stat')
                    print(f"RPC{rpc}: mapping four-input LUTs", flush=True)
                    seconds["yosys"] = run([str(yosys), "-Q", "-p", script], directory / "yosys.log", args.timeout)
                    write_json(synth_manifest, {"rpc": rpc, "sources": hashes, "defines": [DEFINE],
                        "yosys_version": tools["yosys"]["version"],
                        "netlist_sha256": checksum(netlist), "verilog_sha256": checksum(converted)})
                resources = mapped_resources(netlist)
                timing_netlist = directory / "timing_netlist.json"
                promoted = normalize_timing_luts(netlist, timing_netlist, balance_pins=balance_pins,
                                                 share_theta=share_theta,
                                                 routing_settings=CONGESTION_SETTINGS if args.congestion_first else None)
                implementation = mapped_resources(timing_netlist, require_full_timing=True)
                print(f"RPC{rpc}: promoted {promoted} LUTs for complete timing arcs", flush=True)
                print(f"RPC{rpc}: mapped {resources['lut4']} LUT4 / {resources['ff']} FF; "
                      f"implementation {implementation['lut4']} LUT4; routing", flush=True)
                routed = directory / "routed.json"
                report = directory / "pnr_report.json"
                routed.unlink(missing_ok=True)
                report.unlink(missing_ok=True)
                command = [str(nextpnr), "--json", str(timing_netlist), "--device", "GW2AR-LV18QN88C8/I7",
                           "--vopt", "family=GW2A-18C", "--vopt", "cst=syn/keccak_ooc.cst",
                           "--router", router, "--placer-heap-beta", str(density), "--freq", "27",
                           "--timing-allow-fail", "--write", str(routed), "--report", str(report)]
                if not timing_driven:
                    command.append("--no-tmdriv")
                command.extend(("--placer", args.placer))
                if args.router2_alt_weights:
                    command.append("--router2-alt-weights")
                command.extend(("--seed", str(args.seed)))
                if args.congestion_maps:
                    command.extend(("--router2-heatmap", str(directory / "congestion")))
                seconds["pnr"] = run(command, directory / "pnr.log", args.timeout)
                if source_hashes() != hashes:
                    raise ValueError("Keccak source changed during implementation")
                fit = fit_result(report)
                write_json(manifest, {**configuration, "synthesis": resources, "implementation": implementation,
                    "fit": fit, "tools": tools,
                    "seconds": seconds, "commands": {"pnr": command},
                    "outputs": {path.name: checksum(path) for path in
                                (netlist, converted, timing_netlist, routed, report)}})
                export_rows(build, args.output, hashes)
                print(f"PASS RPC{rpc}: {fit['lut4']} LUT4, {fit['ff']} FF, {fit['fmax_mhz']:.3f} MHz; "
                      f"P&R {seconds['pnr']:.1f} s", flush=True)
                if fit["fmax_mhz"] < fit["clock_constraint_mhz"]:
                    print(f"WARNING RPC{rpc}: legal route misses {fit['clock_constraint_mhz']:.3f} MHz; "
                          "recorded achieved Fmax only", flush=True)
        rows = export_rows(build, args.output, hashes)
        if not set(args.rpc).issubset({row["rpc"] for row in rows}):
            raise ValueError("missing requested RPC fit rows")
        print(f"Exported {len(rows)} source-matched Keccak results to {args.output}", flush=True)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"keccak-build: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
