#!/usr/bin/env python3
"""Check the lane-seeded Keccak timing wrapper against the Python oracle."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.keccak_ref import keccak_f1600  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment, write_hex  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", type=int, nargs="+", choices=(1, 2, 3, 4), default=[1, 2, 4])
    args = parser.parse_args()
    state = [0] * 25
    seed = 0xD1B54A32D192ED03
    expected = []
    for _ in range(16):
        state[0] ^= seed
        state = list(keccak_f1600(state))
        expected.append(sum(word << (64 * lane) for lane, word in enumerate(state)))
        feedback = ((seed >> 63) ^ (seed >> 62) ^ (seed >> 60) ^ (seed >> 59)) & 1
        seed = ((seed << 1) & ((1 << 64) - 1)) | feedback
    sources = [ROOT / name for name in (
        "rtl/keccak/keccak_round.sv", "rtl/keccak/keccak_f1600.sv",
        "rtl/top/keccak_ooc_top.sv", "sim/keccak/tb_keccak_ooc.sv")]
    env = tool_environment()
    try:
        for rpc in args.rpc:
            directory = ROOT / "build/sim_keccak_ooc" / f"rpc{rpc}"
            directory.mkdir(parents=True, exist_ok=True)
            vectors = directory / "expected.hex"
            write_hex(vectors, expected, 400)
            image = build_binary(ROOT, "tb_keccak_ooc", {"RPC": rpc, "CASES": len(expected)},
                                 sources, directory, env)
            run_logged([str(image), f"+expected_file={vectors.as_posix()}"],
                       directory / "run.log", env, timeout=120, require_pass=True)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
