"""Resolve HDL tools consistently across PATH, bundles, and platforms."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
_SUITE_DIRS = (
    ROOT / ".tools/oss-cad-suite/oss-cad-suite",
    ROOT / ".tools/oss-cad-20261016/oss-cad-suite",
    ROOT / ".tools/oss-cad-suite",
)
_ENV = {
    "verilator": "VERILATOR",
    "iverilog": "IVERILOG",
    "vvp": "VVP",
    "sv2v": "SV2V",
    "yosys": "YOSYS",
    "nextpnr": "NEXTPNR",
    "gowin_pack": "GOWIN_PACK",
    "openFPGALoader": "OPENFPGALOADER",
    "cxx": "CXX",
    "gw_sh": "GW_SH",
    "programmer_cli": "GOWIN_PROGRAMMER",
    "sby": "SBY",
    "boolector": "BOOLECTOR",
    "openssl": "OPENSSL",
}
_COMMANDS = {
    # Windows bundles include a shell shim named `verilator` as well as the
    # native binary. Prefer the .exe there; POSIX still falls through to `verilator`.
    "verilator": ("verilator_bin", "verilator"),
    "iverilog": ("iverilog",),
    "vvp": ("vvp",),
    "sv2v": ("sv2v",),
    "yosys": ("yosys",),
    "nextpnr": ("nextpnr-himbaechel",),
    "gowin_pack": ("gowin_pack",),
    "openFPGALoader": ("openFPGALoader", "openfpgaloader"),
    "cxx": ("g++", "clang++", "c++"),
    "gw_sh": ("gw_sh",),
    "programmer_cli": ("programmer_cli",),
    "sby": ("sby",),
    "boolector": ("boolector",),
    "openssl": ("openssl",),
}


def _roots(env: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    if env.get("YOSYSHQ_ROOT"):
        roots.append(Path(env["YOSYSHQ_ROOT"]).expanduser())
    roots.extend(_SUITE_DIRS)
    if os.name == "nt":
        roots.append(Path(r"C:\oss-cad-suite\oss-cad-suite"))
    return roots


def _executable(path: Path) -> Path | None:
    if path.is_file():
        return path.resolve()
    if os.name == "nt" and path.suffix.lower() not in {".exe", ".bat", ".cmd"}:
        candidate = path.with_suffix(path.suffix + ".exe")
        if candidate.is_file():
            return candidate.resolve()
    return None


def _bundle_candidates(name: str, env: Mapping[str, str]) -> list[Path]:
    commands = _COMMANDS[name]
    suffixes = (".exe", "") if os.name == "nt" else ("",)
    candidates: list[Path] = []

    if name in {"iverilog", "vvp"}:
        local_bin = ROOT / ".tools/iverilog/bin"
        candidates.extend(local_bin / f"{command}{suffix}"
                          for command in commands for suffix in suffixes)

    for suite in _roots(env):
        candidates.extend(suite / "bin" / f"{command}{suffix}"
                          for command in commands for suffix in suffixes)
        candidates.extend(suite / f"{command}{suffix}"
                          for command in commands for suffix in suffixes)

    if name == "sv2v":
        candidates.extend((ROOT / ".tools/sv2v/sv2v-Windows/sv2v.exe",
                           ROOT / ".tools/sv2v/bin/sv2v"))
    elif name == "cxx" and os.name == "nt":
        candidates.append(Path(r"C:\msys64\mingw64\bin\g++.exe"))
    elif name == "openssl" and os.name == "nt":
        candidates.append(Path(r"C:\msys64\mingw64\bin\openssl.exe"))
    elif name in {"gw_sh", "programmer_cli"}:
        if env.get("GOWIN_HOME"):
            subpath = "IDE/bin/gw_sh.exe" if name == "gw_sh" else "Programmer/bin/programmer_cli.exe"
            candidates.append(Path(env["GOWIN_HOME"]) / subpath)
        if os.name == "nt":
            install = Path(r"C:\Gowin\Gowin_V1.9.11.03_Education_x64")
            subpath = "IDE/bin/gw_sh.exe" if name == "gw_sh" else "Programmer/bin/programmer_cli.exe"
            candidates.append(install / subpath)
    elif name == "verilator":
        for suite in _roots(env):
            candidates.extend(suite / "bin" / f"{command}{suffix}"
                              for command in ("verilator", "verilator_bin")
                              for suffix in suffixes)

    return candidates


def resolve_tool(name: str, env: Mapping[str, str] | None = None) -> str:
    """Find a tool by explicit override, PATH, then known bundle locations."""
    if name not in _COMMANDS:
        raise ValueError(f"unknown tool {name!r}")
    env = os.environ if env is None else env
    variable = _ENV[name]
    explicit = env.get(variable)
    explicit_error = None
    if explicit:
        found = shutil.which(explicit, path=env.get("PATH"))
        if found:
            return str(Path(found).resolve())
        candidate = _executable(Path(explicit).expanduser())
        if candidate:
            return str(candidate)
        explicit_error = f"{variable}={explicit!r} did not resolve"

    for command in _COMMANDS[name]:
        found = shutil.which(command, path=env.get("PATH"))
        if found:
            return str(Path(found).resolve())

    for candidate in _bundle_candidates(name, env):
        found = _executable(candidate)
        if found:
            return str(found)

    raise FileNotFoundError(
        f"required tool {name} was not found ({explicit_error or 'no PATH or bundle match'}); "
        f"install it or set {variable} to its executable path"
    )


def resolve_verilator(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("verilator", env)


def resolve_iverilog(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("iverilog", env)


def resolve_vvp(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("vvp", env)


def resolve_sv2v(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("sv2v", env)


def resolve_yosys(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("yosys", env)


def resolve_nextpnr(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("nextpnr", env)


def resolve_gowin_pack(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("gowin_pack", env)


def resolve_openfpgaloader(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("openFPGALoader", env)


def resolve_cxx(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("cxx", env)


def resolve_gw_sh(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("gw_sh", env)


def resolve_programmer_cli(env: Mapping[str, str] | None = None) -> str:
    return resolve_tool("programmer_cli", env)


def resolve_verilator_root(env: Mapping[str, str] | None = None) -> Path:
    """Get Verilator's runtime root from an explicit setting or the binary."""
    env = os.environ if env is None else env
    explicit = env.get("VERILATOR_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if (root / "include" / "verilated.h").is_file():
            return root
        raise FileNotFoundError(
            f"VERILATOR_ROOT does not contain include/verilated.h ({explicit}); set VERILATOR_ROOT correctly"
        )

    executable = resolve_verilator(env)
    result = subprocess.run([executable, "--getenv", "VERILATOR_ROOT"],
                            env=dict(env), capture_output=True, text=True, timeout=20)
    value = result.stdout.strip()
    if os.name == "nt" and value.startswith("/yosyshq/share/"):
        suite_root = Path(executable).parent.parent
        value = str(suite_root / "share" / value.removeprefix("/yosyshq/share/"))
    root = Path(value).expanduser() if value else Path()
    if result.returncode == 0 and value and (root / "include" / "verilated.h").is_file():
        return root.resolve()
    raise FileNotFoundError(
        "could not determine Verilator runtime root; set VERILATOR_ROOT to the directory containing include/verilated.h"
    )


def yosys_data_file(relative: str, env: Mapping[str, str] | None = None) -> Path:
    """Locate a data file installed beside the resolved Yosys executable."""
    env = os.environ if env is None else env
    candidates: list[Path] = []
    for suite in _roots(env):
        candidates.append(suite / "share/yosys" / relative)
    executable = Path(resolve_yosys(env))
    candidates.append(executable.parent.parent / "share/yosys" / relative)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Yosys data file {relative!r} not found; set YOSYSHQ_ROOT to the Yosys installation root"
    )


def tool_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy environment and prioritize known bundles and their runtime DLLs."""
    result = dict(os.environ if env is None else env)
    path_parts = result.get("PATH", "").split(os.pathsep)
    additions: list[str] = []
    roots: list[Path] = []
    # Match runtime DLLs to the Yosys selected by the caller's environment/PATH
    # before adding fallback bundles, which may carry incompatible DLL versions.
    try:
        selected_yosys = Path(resolve_tool("yosys", result))
        selected_root = selected_yosys.parent.parent
        if (selected_root / "share/yosys").is_dir():
            roots.append(selected_root)
    except FileNotFoundError:
        pass
    roots.extend(root for root in _roots(result) if root not in roots)
    for suite in roots:
        for directory in (suite / "bin", suite / "lib"):
            if directory.is_dir() and str(directory) not in path_parts + additions:
                additions.append(str(directory))
    local_icarus = ROOT / ".tools/iverilog/bin"
    if local_icarus.is_dir() and str(local_icarus) not in path_parts + additions:
        additions.append(str(local_icarus))
    # Keep each bundle's DLLs ahead of unrelated runtimes already on PATH.
    result["PATH"] = os.pathsep.join(additions + path_parts)
    return result
