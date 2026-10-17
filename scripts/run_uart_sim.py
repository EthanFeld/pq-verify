#!/usr/bin/env python3
"""Run TX-to-RX UART loopback at fast and standard baud divisors."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402
from scripts.tools import resolve_iverilog, resolve_vvp  # noqa: E402


def main() -> int:
    env = tool_environment()
    try:
        compiler = resolve_iverilog(env)
        runtime = resolve_vvp(env)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    directory = ROOT / "build/sim_uart"
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "tb_uart_loopback.vvp"
    image.unlink(missing_ok=True)
    sources = [ROOT / "rtl/io/uart_tx.sv", ROOT / "rtl/io/uart_rx.sv",
               ROOT / "sim/io/tb_uart_loopback.sv"]
    try:
        run_logged([compiler, "-g2012", "-s", "tb_uart_loopback", "-o", str(image),
                    *(str(source) for source in sources)], directory / "compile.log", env,
                   allow_output_on_crash=image)
        run_logged([runtime, str(image)], directory / "run.log", env,
                   timeout=120, require_pass=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
