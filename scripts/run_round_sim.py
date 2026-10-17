#!/usr/bin/env python3
"""Compare 10,000 random RTL Keccak round evaluations with the Python oracle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.keccak_ref import keccak_round  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=10_000)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0x2051600)
    parser.add_argument("--lut4-map", type=int, nargs="+", choices=(0, 1), default=[0, 1])
    parser.add_argument("--native-luts", action="store_true", help="exercise the synthesis branch with Gowin's LUT simulation model")
    args = parser.parse_args()
    if args.cases != 10_000:
        parser.error("T2.1 acceptance requires exactly 10,000 pairs")

    try:
        directory = ROOT / "build/sim_keccak_round"
        directory.mkdir(parents=True, exist_ok=True)
        vectors_file = directory / "round_vectors.hex"
        rng = random.Random(args.seed)
        with vectors_file.open("w", encoding="ascii", newline="\n") as stream:
            for index in range(args.cases):
                state_value = rng.getrandbits(1600)
                round_index = index % 24
                lanes = [(state_value >> (lane * 64)) & ((1 << 64) - 1)
                         for lane in range(25)]
                result_lanes = keccak_round(lanes, round_index)
                result_value = sum(lane << (index * 64)
                                   for index, lane in enumerate(result_lanes))
                stream.write(f"{state_value:0400x}{round_index:02x}{result_value:0400x}\n")

        env = tool_environment()
        local_msys_bin = Path(r"C:\msys64\mingw64\bin")
        if local_msys_bin.is_dir():
            env["PATH"] = str(local_msys_bin) + os.pathsep + env.get("PATH", "")
        sources = [ROOT / "rtl/keccak/keccak_round.sv", ROOT / "sim/keccak/tb_keccak_round.sv"]
        if args.native_luts:
            suite = Path(env.get("YOSYSHQ_ROOT", r"C:\oss-cad-suite\oss-cad-suite"))
            library = suite / "share/yosys/gowin/cells_sim.v"
            copied_library = directory / "gowin_cells_sim.v"
            copied_library.write_bytes(library.read_bytes())
            defines = directory / "native_defines.sv"
            defines.write_text("`define PQ_GOWIN_LUT4\n", encoding="ascii")
            sources = [defines, *sources, copied_library]
        for lut4_map in args.lut4_map:
            model_directory = directory / f"map{lut4_map}{'_native' if args.native_luts else ''}"
            model_directory.mkdir(exist_ok=True)
            simulator = build_binary(ROOT, "tb_keccak_round", {"CASES": args.cases, "LUT4_MAP": lut4_map},
                                 sources, model_directory, env)
            run_logged([str(simulator), f"+vectors_file={vectors_file.as_posix()}"],
                       model_directory / "run.log", env, timeout=900, require_pass=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
