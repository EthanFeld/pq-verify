#!/usr/bin/env python3
"""Check H_msg digest/split boundaries, including empty input and context."""

from __future__ import annotations

import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.slhdsa_ref import SHAKE128S, h_msg, split_digest  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment, write_hex  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


def main() -> int:
    try:
        directory = ROOT / "build/sim_hmsg_boundaries"
        directory.mkdir(parents=True, exist_ok=True)
        rng = random.Random(0x484D5347)
        lengths = [0, 1, 135, 136, 137, 271, 272, 273, 607, 608, 609]
        cases = [(False, b"", 0), (True, b"", 0), (True, b"\x53", 0),
                 (True, bytes((i * 17 + 3) & 0xFF for i in range(255)), 1)]
        cases.extend((True, b"", length) for length in lengths[1:])
        for test_id, (pure, context, message_length) in enumerate(cases):
            randomizer, pk_seed, pk_root = (rng.randbytes(16) for _ in range(3))
            message = rng.randbytes(message_length)
            reference_message = (b"\x00" + bytes((len(context),)) + context + message
                                 if pure else message)
            digest = h_msg(randomizer, pk_seed, pk_root, reference_message)
            split = split_digest(digest)
            expected_md_idx = sum(value << (12 * index)
                                  for index, value in enumerate(split.fors_indices))

            case_dir = directory / f"case{test_id:02d}"
            case_dir.mkdir(parents=True, exist_ok=True)
            context_file = case_dir / "context.hex"
            message_file = case_dir / "message.hex"
            write_hex(context_file, list(context) + [0] * (255 - len(context)) or [0], 2)
            write_hex(message_file, list(message) + [0] * (609 - len(message)) or [0], 2)
            args = [f"+context_file={context_file.as_posix()}",
                    f"+message_file={message_file.as_posix()}",
                    f"+message_length={len(message)}", f"+context_length={len(context)}",
                    f"+pure={int(pure)}", f"+test_id={test_id}",
                    f"+randomizer={randomizer.hex()}", f"+pk_seed={pk_seed.hex()}",
                    f"+pk_root={pk_root.hex()}",
                    f"+expected_digest={int.from_bytes(digest, 'little'):060x}",
                    f"+expected_md_idx={expected_md_idx:042x}",
                    f"+expected_tree={split.idx_tree:014x}",
                    f"+expected_leaf={split.idx_leaf:03x}"]
            cases[test_id] = (case_dir, args)

        env = tool_environment()
        local_msys_bin = Path(r"C:\msys64\mingw64\bin")
        if local_msys_bin.is_dir():
            env["PATH"] = str(local_msys_bin) + os.pathsep + env.get("PATH", "")
        simulator = build_binary(ROOT, "tb_hmsg_boundaries",
                                 {"MSG_BYTES": 609, "CTX_BYTES": 255},
                                 [ROOT / "rtl/keccak/keccak_round.sv",
                                  ROOT / "rtl/keccak/keccak_f1600.sv",
                                  ROOT / "rtl/keccak/shake256.sv",
                                  ROOT / "rtl/slh/hmsg.sv",
                                  ROOT / "sim/verify/tb_hmsg_boundaries.sv"],
                                 directory, env)

        def run_case(case: tuple[Path, list[str]]) -> None:
            case_dir, args = case
            run_logged([str(simulator), *args], case_dir / "run.log", env,
                       timeout=300, require_pass=True)

        for case in cases:
            run_case(case)
        print(f"PASS H_msg standalone boundaries: {len(cases)} cases", flush=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
