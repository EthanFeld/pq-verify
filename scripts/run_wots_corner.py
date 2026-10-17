#!/usr/bin/env python3
"""Exercise WOTS+ digit, checksum and chain-count boundary cases."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402


def main() -> int:
    env = tool_environment()
    compiler = shutil.which(env.get("IVERILOG", "iverilog"), path=env["PATH"])
    runtime = shutil.which(env.get("VVP", "vvp"), path=env["PATH"])
    if not compiler or not runtime:
        print("Icarus Verilog is required", file=sys.stderr)
        return 1

    directory = ROOT / "build/sim_wots_corner"
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "tb_wots_corner.vvp"
    sources = [ROOT / "rtl/slh/wots_verify.sv", ROOT / "sim/verify/tb_wots_corner.sv"]
    try:
        run_logged([compiler, "-g2012", "-s", "tb_wots_corner", "-o", str(image),
                    *(str(source) for source in sources)], directory / "compile.log", env,
                   allow_output_on_crash=image)
        run_logged([runtime, str(image)], directory / "run.log", env, require_pass=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
