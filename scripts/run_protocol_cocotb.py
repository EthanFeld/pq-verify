#!/usr/bin/env python3
"""Run UART command-controller protocol tests with Icarus and cocotb."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_hash_sim import tool_environment  # noqa: E402
from scripts.tools import resolve_iverilog  # noqa: E402


def main() -> int:
    env = tool_environment()
    os.environ["PATH"] = env["PATH"]
    try:
        resolve_iverilog(env)
    except FileNotFoundError as exc:
        print(f"protocol-cocotb: {exc}", file=sys.stderr)
        return 2

    runner = get_runner("icarus")
    build_dir = ROOT / "build/sim_protocol"
    image = build_dir / "sim.vvp"
    if image.exists():
        image.unlink()
    sources = [
        ROOT / "rtl/io/uart_rx.sv",
        ROOT / "rtl/io/uart_tx.sv",
        ROOT / "rtl/io/cmd_ctrl.sv",
        ROOT / "sim/io/cmd_ctrl_cocotb_top.sv",
    ]
    try:
        try:
            runner.build(
                sources=sources,
                hdl_toplevel="cmd_ctrl_cocotb_top",
                # A short, word-aligned signature keeps the UART protocol test
                # focused on parser/control behavior; hardware checks use 7,856 bytes.
                parameters={"CLKS_PER_BIT": 4, "SIG_BYTES": 16},
                build_args=["-g2012"],
                build_dir=build_dir,
                always=True,
                timescale=("1ns", "1ps"),
            )
        except Exception as exc:
            compiler_crash = (
                "return code: 3221225477" in str(exc)
                or "return code: -1073741819" in str(exc)
            )
            if not compiler_crash or not image.is_file() or not image.stat().st_size:
                raise
            print(f"WARN Icarus exited after writing {image.name}; using simulator: {exc}", flush=True)
        runner.test(
            test_module="test_cmd_ctrl_protocol",
            hdl_toplevel="cmd_ctrl_cocotb_top",
            test_dir=ROOT / "sim/io",
            build_dir=build_dir,
            extra_env={"PATH": env["PATH"]},
        )
    except Exception as exc:  # runner reports full compiler/simulator diagnostics
        print(f"protocol-cocotb: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
