#!/usr/bin/env python3
"""Check RTL Keccak against the Python oracle and SHAKE against hashlib."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.keccak_ref import keccak_f1600  # noqa: E402
from scripts.tools import resolve_cxx, resolve_iverilog, resolve_vvp, tool_environment as _tool_environment  # noqa: E402


def tool_environment() -> dict[str, str]:
    return _tool_environment()


def write_hex(path: Path, values: list[int], digits: int) -> None:
    path.write_text("".join(f"{value:0{digits}x}\n" for value in values), encoding="ascii")


def keccak_vectors(directory: Path, count: int) -> dict[str, Path]:
    rng = random.Random(0x1600128)
    states = [0, (1 << 1600) - 1] + [rng.getrandbits(1600) for _ in range(max(0, count - 2))]
    states = states[:count]
    results = []
    for value in states:
        lanes = [(value >> (64 * lane)) & ((1 << 64) - 1) for lane in range(25)]
        results.append(sum(word << (64 * lane) for lane, word in enumerate(keccak_f1600(lanes))))
    files = {"input_file": directory / "input.hex", "expected_file": directory / "expected.hex"}
    write_hex(files["input_file"], states, 400)
    write_hex(files["expected_file"], results, 400)
    return files


def shake_vectors(directory: Path) -> tuple[dict[str, Path], int, int]:
    rng = random.Random(0x5A4E256)
    lengths = [0, 1, 2, 7, 8, 9, 15, 16, 47, 48, 49, 63, 64, 127, 128, 129,
               134, 135, 136, 137, 143, 144, 271, 272, 273, 607, 608, 609, 1000, 4096]
    lengths += [rng.randrange(0, 2049) for _ in range(32)]
    beats: list[int] = []
    cases: list[int] = []
    for length in lengths:
        data = rng.randbytes(length)
        # Exercise both a final data lane and a separate zero-byte terminator.
        for empty_terminator in (False, True):
            if empty_terminator and length % 8:
                continue
            offset = len(beats)
            for start in range(0, length, 8):
                chunk = data[start:start + 8]
                lane = int.from_bytes(chunk + rng.randbytes(8 - len(chunk)), "little")
                last = start + len(chunk) == length and not empty_terminator
                beats.append(lane | len(chunk) << 64 | int(last) << 68)
            if not length or empty_terminator:
                beats.append(rng.getrandbits(64) | 1 << 68)
            digest = int.from_bytes(hashlib.shake_256(data).digest(32), "little")
            cases.append(length << 320 | offset << 288 | (len(beats) - offset) << 256 | digest)
    files = {"beats_file": directory / "beats.hex", "cases_file": directory / "cases.hex"}
    write_hex(files["beats_file"], beats, 18)
    write_hex(files["cases_file"], cases, 88)
    return files, len(cases), len(beats)


def run_logged(command: list[str], log: Path, env: dict[str, str], timeout: int = 300,
               require_pass: bool = False,
               allow_output_on_crash: Path | None = None) -> None:
    run_env = env
    executable = Path(command[0])
    if executable.parent.name == "verilator_model":
        run_env = dict(env)
        compiler_bin = str(Path(resolve_cxx(run_env)).resolve().parent)
        path_parts = run_env.get("PATH", "").split(os.pathsep)
        run_env["PATH"] = os.pathsep.join(
            [compiler_bin] + [part for part in path_parts if part.casefold() != compiler_bin.casefold()]
        )
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=ROOT, env=run_env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    output = log.read_text(encoding="utf-8", errors="replace")
    if result.returncode:
        # Some bundled Windows Icarus builds fault during process teardown after
        # writing a usable image. The simulator run remains the acceptance check.
        if (result.returncode in (3221225477, -1073741819)
                and allow_output_on_crash is not None
                and allow_output_on_crash.is_file()
                and allow_output_on_crash.stat().st_size > 0):
            print(f"WARN compiler exited after writing {allow_output_on_crash.name}; validating with simulator",
                  flush=True)
        else:
            raise RuntimeError(f"{command[0]} exited {result.returncode}:\n{output[-6000:]}")
    passed = False
    for line in output.splitlines():
        if line.startswith("PASS"):
            passed = True
            print(line, flush=True)
    if require_pass and not passed:
        raise RuntimeError(f"simulation exited without its completion marker: {log}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("keccak", "shake", "all"), default="all")
    parser.add_argument("--rpc", nargs="+", type=int, choices=(1, 2, 3, 4), default=[1, 2, 3, 4])
    parser.add_argument("--cases", type=int, default=1002,
                        help="permutation states, including zero and all-ones (default: 1000 random + 2 corners)")
    parser.add_argument("--simulator", choices=("verilator", "icarus"), default="verilator")
    args = parser.parse_args()
    if args.cases < 1:
        parser.error("--cases must be positive")
    env = tool_environment()
    try:
        compiler = resolve_iverilog(env)
        runtime = resolve_vvp(env)
    except FileNotFoundError as exc:
        if args.simulator == "icarus":
            parser.error(str(exc))
        compiler, runtime = "", ""
    rtl = [str(ROOT / "rtl/keccak" / name) for name in ("keccak_round.sv", "keccak_f1600.sv", "shake256.sv")]
    try:
        for suite in ("keccak", "shake"):
            if args.suite not in (suite, "all"):
                continue
            directory = ROOT / "build" / f"sim_{suite}"
            directory.mkdir(parents=True, exist_ok=True)
            count, beat_count = args.cases, 0
            if suite == "keccak":
                files = keccak_vectors(directory, count)
            else:
                files, count, beat_count = shake_vectors(directory)
            top = f"tb_{suite}"
            for rpc in args.rpc:
                for in_place in ((0, 1) if suite == "keccak" else (1,)):
                    tag = f"rpc{rpc}_inplace{in_place}"
                    parameter_values = {"RPC": rpc, "CASES": count}
                    parameter_values.update({"IN_PLACE": in_place} if suite == "keccak" else {"BEATS": beat_count})
                    if args.simulator == "verilator":
                        from scripts.verilator_build import build_binary
                        image = build_binary(ROOT, top, parameter_values,
                                             [Path(path) for path in rtl] + [ROOT / "sim" / suite / f"{top}.sv"],
                                             directory / tag, env)
                        command = [str(image)]
                    else:
                        image = directory / f"{tag}.vvp"
                        image.unlink(missing_ok=True)
                        parameters = [f"-P{top}.{key}={value}" for key, value in parameter_values.items()]
                        command = [compiler, "-g2012", "-s", top, *parameters, "-o", str(image),
                                   *rtl, str(ROOT / "sim" / suite / f"{top}.sv")]
                        run_logged(command, directory / f"{tag}_compile.log", env,
                                   allow_output_on_crash=image)
                        command = [runtime, str(image)]
                    run_logged([*command, *[f"+{key}={value.as_posix()}" for key, value in files.items()]],
                               directory / f"{tag}_run.log", env, require_pass=True)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
