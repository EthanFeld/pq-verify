#!/usr/bin/env python3
"""Print versions for tools used by the SLH-DSA FPGA build."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path


TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("verilator", ("--version",)),
    ("iverilog", ("-V",)),
    ("vvp", ("-V",)),
    ("sv2v", ("--version",)),
    ("yosys", ("-V",)),
    ("nextpnr-himbaechel", ("--version",)),
    ("gowin_pack", ("-h",)),
    ("openFPGALoader", ("--version",)),
)


def main() -> int:
    missing: list[str] = []
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    try:
        print(f"cocotb: {importlib.metadata.version('cocotb')}")
    except importlib.metadata.PackageNotFoundError:
        print("cocotb: MISSING")
        missing.append("cocotb")

    oss_root = Path(
        os.environ.get("YOSYSHQ_ROOT", r"C:\oss-cad-suite\oss-cad-suite")
    )
    env = os.environ.copy()
    oss_lib = oss_root / "lib"
    if oss_lib.is_dir():
        env["PATH"] = str(oss_lib) + os.pathsep + env.get("PATH", "")
    local_icarus = Path(__file__).resolve().parents[1] / ".tools/iverilog/bin"

    for name, args in TOOLS:
        executable = shutil.which(name, path=env.get("PATH"))
        # Keep Icarus DLLs out of the synthesis tools' search path.
        if name in {"iverilog", "vvp"} and (local_icarus / f"{name}.exe").is_file():
            executable = str(local_icarus / f"{name}.exe")
        if name == "verilator" and executable is None:
            executable = shutil.which("verilator_bin.exe", path=env.get("PATH"))
        if name == "sv2v" and executable is None:
            local_sv2v = (
                Path(__file__).resolve().parents[1]
                / ".tools"
                / "sv2v"
                / "sv2v-Windows"
                / "sv2v.exe"
            )
            if local_sv2v.is_file():
                executable = str(local_sv2v)
        if executable is None:
            print(f"{name}: MISSING")
            missing.append(name)
            continue
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"{name}: ERROR ({exc})")
            missing.append(name)
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        detail = output[0] if output else f"exit {result.returncode}, no version output"
        if name == "gowin_pack":
            apycula_version = None
            for metadata_file in oss_lib.glob(
                "python*/site-packages/apycula-*.dist-info/METADATA"
            ):
                for line in metadata_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("Version: "):
                        apycula_version = line.removeprefix("Version: ")
                        break
            detail = f"Apicula {apycula_version or 'installed'} (gowin_pack CLI)"
        print(f"{name}: {detail}")
        if result.returncode != 0 and name != "gowin_pack":
            missing.append(name)

    if missing:
        print("Missing or failing: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
