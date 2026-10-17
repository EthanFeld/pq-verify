#!/usr/bin/env python3
"""Collect source-matched RPC and scratch-style Gowin fit measurements."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from board_build import source_hashes


def current_sources() -> dict[str, str]:
    repo = Path(__file__).resolve().parents[1]
    hashes = source_hashes()
    hashes["syn/gowin_build.tcl"] = hashlib.sha256(
        (repo / "syn/gowin_build.tcl").read_bytes()
    ).hexdigest()
    return hashes


def row(path: Path, expected_sources: dict[str, str]) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sources") != expected_sources:
        raise ValueError(f"{path}: RTL, constraints, or Gowin flow differs from this checkout")
    rpc = data.get("rpc")
    style = data.get("scratch_style")
    if rpc not in (1, 2, 3, 4) or style not in (0, 1, 2):
        raise ValueError(f"{path}: invalid RPC/scratch-style metadata")
    fit = data["fit"]
    resources = fit["resources"]
    pnr_report = path.parent / "pq_verify/impl/pnr/pq_verify.rpt.txt"
    report_text = pnr_report.read_text(encoding="utf-8", errors="replace")
    ssram = re.search(r"^\s*--SSRAM\(RAM16\)\s*\|\s*(\d+)", report_text, re.M)
    if not ssram:
        raise ValueError(f"{pnr_report}: missing SSRAM usage")
    clock = fit["clocks"]["core_clk"]
    bitstream = fit["configuration_bitstream"]
    stages = data.get("stage_seconds", {})
    cycles: list[int] = []
    perms: list[int] = []
    stage_cycles: dict[str, list[int]] = {"hmsg": [], "fors": [], "hypertree": []}
    sim_dir = path.parents[1] / "sim_verify"
    suffix = f"_scratch{style}" if style else ""
    logs = sorted(sim_dir.glob(f"tc*_rpc{rpc}{suffix}/run.log"))
    verify_pattern = re.compile(
        rf"PASS verify tc=(\d+) RPC={rpc} valid=[01] cycles=(\d+) perms=(\d+)"
    )
    for log_path in logs:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        found = verify_pattern.findall(text)
        if len(found) != 1:
            continue
        _, cycle_count, perm_count = found[0]
        cycles.append(int(cycle_count))
        perms.append(int(perm_count))
        for name, count in re.findall(r"STAGE tc=\d+ name=([a-z_]+) cycles=(\d+)", text):
            if name in stage_cycles:
                stage_cycles[name].append(int(count))
    expected_vectors = json.loads(
        (Path(__file__).resolve().parents[1] / "vectors/shake128s/sigver.json")
        .read_text(encoding="utf-8")
    )
    expected_ids = {
        str(vector["tcId"]) for vector in expected_vectors
        if len(vector["signature"]) == 15712
        and len(vector["pk"]) == 64
        and (vector["mode"] == "internal" or len(vector.get("context", "")) <= 510)
    }
    actual_ids = set()
    for log_path in logs:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        found = verify_pattern.findall(text)
        if len(found) == 1:
            actual_ids.add(found[0][0])
    if actual_ids != expected_ids or len(cycles) != 20 or any(len(values) != 20 for values in stage_cycles.values()):
        raise ValueError(f"RPC{rpc}/scratch{style}: expected 20 passing core/stage logs, found {len(actual_ids)}")
    core_mhz = clock["constraint_mhz"]
    mean_cycles = sum(cycles) / len(cycles)
    mean_latency_us = mean_cycles / core_mhz
    return {
        "config": f"rpc{rpc}_scratch{style}",
        "rpc": rpc,
        "scratch_style": style,
        "place_option": data.get("place_option", 0),
        "route_option": data.get("route_option", 0),
        "logic_cells": resources["logic"]["used"],
        "ff": resources["ff"]["used"],
        "bsram": resources["bsram"]["used"],
        "ssram": int(ssram[1]),
        "dsp": resources["dsp"]["used"],
        "fmax_mhz": clock["fmax_mhz"],
        "f_run_mhz": clock["constraint_mhz"],
        "bitstream_bytes": bitstream["binary_bytes"],
        "sv2v_seconds": stages.get("sv2v", ""),
        "gowin_fit_pack_seconds": stages.get("gowin_fit_pack", ""),
        "cycles_min": min(cycles),
        "cycles_mean": round(mean_cycles, 2),
        "cycles_max": max(cycles),
        "perms_mean": round(sum(perms) / len(perms), 2),
        "latency_us_mean": round(mean_latency_us, 3),
        "throughput_verifies_s": round(1_000_000 / mean_latency_us, 3),
        "hmsg_mean_cycles": round(sum(stage_cycles["hmsg"]) / 20, 2),
        "fors_mean_cycles": round(sum(stage_cycles["fors"]) / 20, 2),
        "hypertree_mean_cycles": round(sum(stage_cycles["hypertree"]) / 20, 2),
    }


def failure_row(path: Path, expected_sources: dict[str, str]) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sources") != expected_sources:
        raise ValueError(f"{path}: RTL, constraints, or Gowin flow differs from this checkout")
    error = data.get("error", "")
    failure = re.search(r"ERROR\s+\(([^)]+)\)\s*:\s*(.+)", error)
    desroute = re.search(r"Error:\s*(DesRoute failed\.)", error, re.I)
    synth = {"T_Lut": "", "T_Register": "", "T_Bsram": "", "T_Ssram": ""}
    resource_xml = path.parent / "pq_verify/impl/gwsynthesis/pq_verify_syn_rsc.xml"
    if resource_xml.is_file():
        attributes = ET.parse(resource_xml).getroot().attrib
        for name in synth:
            match = re.match(r"(\d+)", attributes.get(name, ""))
            if match:
                synth[name] = int(match[1])
    resource_overflow = re.search(
        r"The number\((\d+)\((\d+) LUTs,\s*(\d+) ALUs.*?resource limit\((\d+)\)",
        error,
        re.S,
    )
    failure_text = failure[2].strip() if failure else error.strip().splitlines()[-1]
    if desroute:
        failure_text = f"{desroute[1]} {failure_text}"
    return {
        "config": f"rpc{data['rpc']}_scratch{data['scratch_style']}",
        "rpc": data["rpc"],
        "scratch_style": data["scratch_style"],
        "place_option": data.get("place_option", 0),
        "route_option": data.get("route_option", 0),
        "failure_code": failure[1] if failure else "unknown",
        "failure": failure_text,
        "gowin_fit_pack_seconds": data.get("stage_seconds", {}).get("gowin_fit_pack", ""),
        "synth_lut": synth["T_Lut"],
        "synth_registers": synth["T_Register"],
        "synth_bsram": synth["T_Bsram"],
        "synth_ssram": synth["T_Ssram"],
        "reported_logic": int(resource_overflow[1]) if resource_overflow else "",
        "logic_limit": int(resource_overflow[4]) if resource_overflow else "",
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=repo / "build")
    parser.add_argument("--output", type=Path, default=repo / "bench/gowin_measurements.csv")
    parser.add_argument("--failures-output", type=Path, default=repo / "bench/gowin_failures.csv")
    args = parser.parse_args()
    manifests = sorted(args.build_root.glob("gowin_rpc*_scratch*/build_manifest.json"))
    if not manifests:
        parser.error(f"no Gowin sweep manifests found in {args.build_root}")
    try:
        expected_sources = current_sources()
        latest_rows: dict[tuple[int, int, int, int], tuple[Path, dict[str, object]]] = {}
        for path in sorted(manifests, key=lambda item: item.stat().st_mtime, reverse=True):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if metadata.get("sources") != expected_sources:
                print(f"Skipping stale Gowin build: {path}")
                continue
            collected = row(path, expected_sources)
            key = (collected["rpc"], collected["scratch_style"],
                   collected["place_option"], collected["route_option"])
            if key in latest_rows:
                print(f"Skipping older duplicate Gowin configuration: {path}")
                continue
            latest_rows[key] = (path, collected)
        rows = [value[1] for _, value in sorted(latest_rows.items())]
        if not rows:
            raise ValueError("no source-matched Gowin build manifests remain")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        columns = (
            "config", "rpc", "scratch_style", "place_option", "route_option",
            "logic_cells", "ff", "bsram", "ssram", "dsp",
            "fmax_mhz", "f_run_mhz", "bitstream_bytes", "sv2v_seconds",
            "gowin_fit_pack_seconds", "cycles_min", "cycles_mean", "cycles_max",
            "perms_mean", "latency_us_mean", "throughput_verifies_s",
            "hmsg_mean_cycles", "fors_mean_cycles", "hypertree_mean_cycles",
        )
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        failed_rows = []
        for path in sorted(args.build_root.glob("gowin_rpc*_scratch*/gowin_failure_manifest.json")):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if metadata.get("sources") != expected_sources:
                continue
            failed_rows.append(failure_row(path, expected_sources))
        failure_columns = (
            "config", "rpc", "scratch_style", "place_option", "route_option",
            "failure_code", "failure", "gowin_fit_pack_seconds",
            "synth_lut", "synth_registers", "synth_bsram", "synth_ssram",
            "reported_logic", "logic_limit",
        )
        args.failures_output.parent.mkdir(parents=True, exist_ok=True)
        with args.failures_output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=failure_columns)
            writer.writeheader()
            writer.writerows(failed_rows)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Collected {len(rows)} source-matched Gowin configurations into {args.output}")
    print(f"Collected {len(failed_rows)} source-matched Gowin failures into {args.failures_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
