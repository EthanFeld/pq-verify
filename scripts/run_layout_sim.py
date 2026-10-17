#!/usr/bin/env python3
"""Check SHAKE-128s parameter layout and ADRS field updates."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402
from model.trace import trace_case  # noqa: E402


def main() -> int:
    env = tool_environment()
    compiler = shutil.which(env.get("IVERILOG", "iverilog"), path=env["PATH"])
    runtime = shutil.which(env.get("VVP", "vvp"), path=env["PATH"])
    if not compiler or not runtime:
        print("Icarus Verilog is required", file=sys.stderr)
        return 1

    directory = ROOT / "build/sim_layout"
    directory.mkdir(parents=True, exist_ok=True)
    suites = {
        "params": [ROOT / "rtl/pkg/slh_params_pkg.sv", ROOT / "sim/verify/tb_params.sv"],
        "adrs": [ROOT / "rtl/slh/adrs.sv", ROOT / "sim/verify/tb_adrs.sv"],
    }
    vectors = json.loads((ROOT / "vectors/shake128s/sigver.json").read_text(encoding="utf-8"))
    vector = next(item for item in vectors if item["mode"] == "pure" and item["testPassed"])
    records, result = trace_case(vector)
    if result != vector["testPassed"]:
        raise ValueError("Python verifier disagrees with selected ADRS trace vector")
    trace_by_type: dict[int, str] = {}
    trace_order: list[str] = []
    for record in records:
        if record["event"] == "hash" and record.get("adrs_hex"):
            address = record["adrs_hex"]
            trace_by_type.setdefault(int(address[32:40], 16), address)
            trace_order.append(address)
    if set(trace_by_type) != set(range(5)):
        raise ValueError("selected Python trace does not cover all five ADRS types")
    trace_values = [trace_by_type[kind] for kind in sorted(trace_by_type)]
    for address in trace_order:
        if address not in trace_values:
            trace_values.append(address)
        if len(trace_values) == 50:
            break
    if len(trace_values) != 50:
        raise ValueError("selected Python trace contains fewer than 50 unique ADRS values")
    trace_file = directory / f"tc{vector['tcId']}_adrs.hex"
    trace_file.write_text("".join(f"{address}\n" for address in trace_values), encoding="ascii")
    try:
        for top, sources in suites.items():
            image = directory / f"tb_{top}.vvp"
            image.unlink(missing_ok=True)
            run_logged([compiler, "-g2012", "-s", f"tb_{top}", "-o", str(image),
                        *(str(source) for source in sources)],
                       directory / f"{top}_compile.log", env, allow_output_on_crash=image)
            arguments = ([f"+trace_file={trace_file.as_posix()}",
                          f"+trace_count={len(trace_values)}"] if top == "adrs" else [])
            run_logged([runtime, str(image), *arguments], directory / f"{top}_run.log", env,
                       require_pass=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
