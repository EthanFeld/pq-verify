#!/usr/bin/env python3
"""Print versions for tools used by the SLH-DSA FPGA build."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys

from tools import (
    resolve_cxx,
    resolve_gowin_pack,
    resolve_iverilog,
    resolve_nextpnr,
    resolve_openfpgaloader,
    resolve_sv2v,
    resolve_verilator,
    resolve_vvp,
    resolve_yosys,
    tool_environment,
)


TOOLS = (
    ("verilator", resolve_verilator, ("--version",)),
    ("iverilog", resolve_iverilog, ("-V",)),
    ("vvp", resolve_vvp, ("-V",)),
    ("sv2v", resolve_sv2v, ("--version",)),
    ("yosys", resolve_yosys, ("-V",)),
    ("nextpnr-himbaechel", resolve_nextpnr, ("--version",)),
    ("gowin_pack", resolve_gowin_pack, ("-h",)),
    ("openFPGALoader", resolve_openfpgaloader, ("--version",)),
    ("C++ compiler", resolve_cxx, ("--version",)),
)


def main() -> int:
    missing: list[str] = []
    env = tool_environment()
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    try:
        print(f"cocotb: {importlib.metadata.version('cocotb')}")
    except importlib.metadata.PackageNotFoundError:
        print("cocotb: MISSING")
        missing.append("cocotb")

    for name, resolver, args in TOOLS:
        try:
            executable = resolver(env)
            result = subprocess.run([executable, *args], capture_output=True, text=True,
                                    timeout=15, env=env)
        except FileNotFoundError as exc:
            print(f"{name}: MISSING ({exc})")
            missing.append(name)
            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"{name}: ERROR ({exc})")
            missing.append(name)
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        detail = output[0] if output else f"exit {result.returncode}, no version output"
        print(f"{name}: {detail}")
        if result.returncode != 0 and name != "gowin_pack":
            missing.append(name)

    if missing:
        print("Missing or failing: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
