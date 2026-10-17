#!/usr/bin/env python3
"""Run ACVP vectors through the Tang Nano UART top in RTL simulation."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "host"))
from slhv import frame_sequence  # noqa: E402
from proto import CMD_LOAD_SIG, SIGNATURE_BYTES, encode_request  # noqa: E402
from model.vector_corpus import load_vector_cases  # noqa: E402
from scripts.board_build import RTL  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402
from scripts.tools import resolve_iverilog, resolve_verilator, resolve_vvp  # noqa: E402

DEFAULT_TC_IDS = (337, 338, 342, 343, 464)
PASS_LINE = re.compile(
    r"PASS verify tc=(\d+) RPC=1 valid=(\d+) cycles=(\d+) perms=(\d+)"
)


def write_hex(path: Path, data: bytes) -> None:
    path.write_text("".join(f"{value:02x}\n" for value in data), encoding="ascii")


def read_core_result(tc_id: int) -> tuple[int, int, int]:
    log = ROOT / "build" / "sim_verify" / f"tc{tc_id}_rpc1" / "run.log"
    output = log.read_text(encoding="utf-8", errors="replace")
    match = PASS_LINE.search(output)
    if not match:
        raise RuntimeError(f"core simulation result missing from {log}")
    _, valid, cycles, perms = match.groups()
    return int(valid), int(cycles), int(perms)


def run_system_case(vector: dict, build: Path, image: Path, runtime: str,
                    env: dict[str, str], expected: tuple[int, int, int] | None,
                    simulator: str) -> None:
    tc_id = int(vector["tcId"])
    malformed = (
        len(bytes.fromhex(vector["pk"])) != 32
        or len(bytes.fromhex(vector["signature"])) != SIGNATURE_BYTES
    )
    expected_valid = int(bool(vector["testPassed"]))
    expected_cycles, expected_perms = (0, 0) if malformed else (0, 0)
    if expected is not None:
        core_valid, expected_cycles, expected_perms = expected
        if core_valid != expected_valid:
            raise RuntimeError(f"tc {tc_id}: core RTL disagrees with ACVP expectation")

    directory = build / f"tc{tc_id}"
    directory.mkdir(parents=True, exist_ok=True)
    requests = [frame for _, frame in frame_sequence(vector)]
    names = ("ping", "pk", "sig", "verify")
    frame_paths: dict[str, Path] = {}
    for name, frame in zip(names, requests, strict=True):
        path = directory / f"{name}.hex"
        write_hex(path, frame)
        frame_paths[name] = path

    signature = bytes.fromhex(vector["signature"])
    stale_check = int(not malformed and len(signature) == SIGNATURE_BYTES)
    stale_frame = (
        encode_request(CMD_LOAD_SIG, signature[:-1])
        if stale_check else requests[2]
    )
    stale_sig_path = directory / "stale_sig.hex"
    write_hex(stale_sig_path, stale_frame)

    plusargs = [
        f"+{name}_file={frame_paths[name].as_posix()}"
        for name in names
    ]
    plusargs.append(f"+stale_sig_file={stale_sig_path.as_posix()}")
    plusargs.extend(
        f"+{name}_len={len(frame)}" for name, frame in zip(names, requests, strict=True)
    )
    plusargs.extend((
        f"+stale_sig_len={len(stale_frame) if stale_check else 0}",
        f"+stale_check={stale_check}",
    ))
    plusargs.extend((
        f"+test_id={tc_id}",
        f"+expected_valid={expected_valid}",
        f"+expected_pk_status={2 if len(bytes.fromhex(vector['pk'])) != 32 else 0}",
        f"+expected_sig_status={2 if len(signature) != SIGNATURE_BYTES else 0}",
        f"+expected_verify_status={2 if malformed else 0}",
        f"+expected_cycles={expected_cycles}",
        f"+expected_perms={expected_perms}",
    ))
    command = [runtime]
    if simulator == "iverilog":
        command.append(str(image))
    run_logged([*command, *plusargs], directory / "run.log", env,
               timeout=900, require_pass=True)
    print(f"PASS system tc={tc_id}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tc", type=int, nargs="+", help="selected vector tcIds")
    selection.add_argument("--all", action="store_true", help="all vectors in the selected corpus")
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4), default=2,
                        help="parallel core and system-vector jobs")
    parser.add_argument("--clks-per-bit", type=int, default=335,
                        help="UART clocks per bit (board clock default: 335)")
    parser.add_argument("--simulator", choices=("verilator", "icarus"), default="verilator",
                        help="Verilator is faster for full-rate UART system tests")
    parser.add_argument("--reuse-core-results", action="store_true",
                        help="reuse existing passing core logs instead of rerunning the references")
    args = parser.parse_args()
    if args.clks_per_bit < 4:
        parser.error("--clks-per-bit must be at least 4 for the two-flop RX synchronizer")

    try:
        vectors = load_vector_cases(args.vectors)
        if not isinstance(vectors, list):
            raise ValueError("vector file must contain a list or a header/tests document")
        ids = [int(row["tcId"]) for row in vectors] if args.all else (args.tc or DEFAULT_TC_IDS)
        selected = [next(row for row in vectors if row["tcId"] == tc_id) for tc_id in ids]
        is_malformed = lambda row: (
            len(bytes.fromhex(row["pk"])) != 32
            or len(bytes.fromhex(row["signature"])) != SIGNATURE_BYTES
        )
        core_selected = [row for row in selected if not is_malformed(row)]
        if args.tc is None and core_selected and sum(bool(row["testPassed"]) for row in selected) == 0:
            raise ValueError("system regression must include a valid vector")
        if args.tc is None and core_selected and sum(not bool(row["testPassed"]) for row in selected) < 2:
            raise ValueError("system regression must include at least two invalid vectors")

        env = tool_environment()
        if args.simulator == "iverilog":
            compiler = resolve_iverilog(env)
            runtime = resolve_vvp(env)
        else:
            compiler = ""
            runtime = resolve_verilator(env)

        # Core-only results are the cycle-count reference for UART integration.
        if args.reuse_core_results and core_selected:
            print("Reusing existing core PASS logs", flush=True)
            for vector in core_selected:
                tc_id = int(vector["tcId"])
                core_valid, _, _ = read_core_result(tc_id)
                if core_valid != int(bool(vector["testPassed"])):
                    raise RuntimeError(f"tc {tc_id}: core RTL disagrees with ACVP expectation")
        elif core_selected:
            core_log = ROOT / "build" / "sim_system" / "core_regression.log"
            core_log.parent.mkdir(parents=True, exist_ok=True)
            core_command = [sys.executable, str(ROOT / "scripts/run_verify_sim.py"),
                            "--tc", *[str(row["tcId"]) for row in core_selected], "--jobs", str(args.jobs)]
            with core_log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(core_command, cwd=ROOT, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=1800)
            if result.returncode:
                output = core_log.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"core reference regression failed:\n{output[-6000:]}")

        build = ROOT / "build" / "sim_system"
        build.mkdir(parents=True, exist_ok=True)
        rtl = [str(ROOT / "rtl" / name) for name in RTL]
        if args.simulator == "verilator":
            from scripts.verilator_build import build_binary
            image = build_binary(
                ROOT, "tb_system_uart", {"CLKS_PER_BIT": args.clks_per_bit},
                [Path(path) for path in rtl] + [ROOT / "sim/system/tb_system_uart.sv"],
                build / f"verilator_cpb{args.clks_per_bit}", env, defines=("SIM",),
            )
            runtime = str(image)
        else:
            image = build / "system_uart.vvp"
            compile_command = [compiler, "-g2012", "-DSIM", "-s", "tb_system_uart",
                               f"-Ptb_system_uart.CLKS_PER_BIT={args.clks_per_bit}",
                               "-o", str(image), *rtl,
                               str(ROOT / "sim/system/tb_system_uart.sv")]
            run_logged(compile_command, build / "compile.log", env, allow_output_on_crash=image)

        cases = []
        for vector in selected:
            tc_id = int(vector["tcId"])
            expected = None if is_malformed(vector) else read_core_result(tc_id)
            cases.append((vector, build, image, runtime, env, expected, args.simulator))
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            list(executor.map(lambda case: run_system_case(*case), cases))

        return 0
    except (OSError, KeyError, StopIteration, ValueError, RuntimeError,
            subprocess.TimeoutExpired) as exc:
        print(f"system-sim: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
