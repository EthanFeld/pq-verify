#!/usr/bin/env python3
"""Run selected ACVP cases through one reusable Verilator model."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.trace import trace_case  # noqa: E402
from model.vector_corpus import load_vector_cases  # noqa: E402
from scripts.board_build import RTL  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment, write_hex  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


def prepare_case(vector: dict, rpc: int, scratch_style: int, message_capacity: int,
                 context_capacity: int) -> tuple[Path, list[str]]:
    signature = bytes.fromhex(vector["signature"])
    pk = bytes.fromhex(vector["pk"])
    message = bytes.fromhex(vector["message"])
    context = bytes.fromhex(vector.get("context", "")) if vector["mode"] == "pure" else b""
    if len(signature) != 7856 or len(pk) != 32 or len(context) > 255:
        raise ValueError(f"tc {vector['tcId']}: malformed frame must be tested through cmd_ctrl")
    if vector["mode"] not in {"pure", "internal"}:
        raise ValueError("unsupported verification mode")
    records, result = trace_case(vector)
    if result != vector["testPassed"]:
        raise ValueError("Python oracle disagrees with the ACVP result")
    checkpoints = [record for record in records if record["event"] == "checkpoint"]
    fors_pk = next(record["output_hex"] for record in checkpoints if record["kind"] == "fors_pk")
    digest = next(record["output_hex"] for record in checkpoints if record["kind"] == "digest")
    wots = [int(record["output_hex"], 16) for record in checkpoints if record["kind"] == "wots_pk"]
    roots = [int(record["output_hex"], 16) for record in checkpoints if record["kind"] == "xmss_root"]
    expected_perms = sum(record["perms"] for record in records if record["event"] == "hash")

    suffix = f"_scratch{scratch_style}" if scratch_style else ""
    directory = ROOT / "build/sim_verify" / f"tc{vector['tcId']}_rpc{rpc}{suffix}"
    directory.mkdir(parents=True, exist_ok=True)
    files = {name + "_file": directory / (name + ".hex")
             for name in ("signature", "message", "context", "wots", "roots")}
    write_hex(files["signature_file"], [int.from_bytes(signature[start:start + 4], "big")
                                        for start in range(0, len(signature), 4)], 8)
    padded_message = list(message) + [0] * (max(1, message_capacity) - len(message))
    padded_context = list(context) + [0] * (max(1, context_capacity) - len(context))
    write_hex(files["message_file"], padded_message, 2)
    write_hex(files["context_file"], padded_context, 2)
    write_hex(files["wots_file"], wots, 32)
    write_hex(files["roots_file"], roots, 32)

    arguments = [f"+{key}={value.as_posix()}" for key, value in files.items()]
    arguments += [f"+test_id={vector['tcId']}", f"+pure={int(vector['mode'] == 'pure')}",
                  f"+pk_seed={pk[:16].hex()}", f"+pk_root={pk[16:].hex()}",
                  f"+expected_fors={fors_pk}",
                  f"+expected_digest={int.from_bytes(bytes.fromhex(digest), 'little'):060x}",
                  f"+expected_valid={int(result)}", f"+expected_perms={expected_perms}",
                  f"+message_length={len(message)}", f"+context_length={len(context)}"]
    return directory, arguments


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tc", type=int, nargs="+")
    selection.add_argument("--all", action="store_true", help="all cases with well-formed core inputs")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--scratch-style", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    args = parser.parse_args()
    try:
        vectors = load_vector_cases(args.vectors)
        if not isinstance(vectors, list):
            raise ValueError("vector file must contain a list or a header/tests document")
        if args.all:
            selected = [vector for vector in vectors if len(vector["signature"]) == 7856 * 2
                        and len(vector["pk"]) == 32 * 2
                        and (vector["mode"] == "internal"
                             or len(vector.get("context", "")) <= 255 * 2)]
            print(f"Checking {len(selected)} core cases; {len(vectors) - len(selected)} malformed-input cases "
                  "require cmd_ctrl/system tests", flush=True)
        else:
            selected = [next(vector for vector in vectors if vector["tcId"] == tc)
                        for tc in (args.tc or [343, 464, 338])]
        if not selected:
            raise ValueError("no verification vectors selected")

        message_capacity = max(len(bytes.fromhex(vector["message"])) for vector in selected)
        context_capacity = max((len(bytes.fromhex(vector.get("context", "")))
                                if vector["mode"] == "pure" else 0) for vector in selected)
        cases = [prepare_case(vector, args.rpc, args.scratch_style,
                              message_capacity, context_capacity)
                 for vector in selected]
        env = tool_environment()
        suffix = f"_scratch{args.scratch_style}" if args.scratch_style else ""
        build_directory = ROOT / "build/sim_verify" / f"shared_rpc{args.rpc}{suffix}"
        sources = [ROOT / "rtl" / name for name in RTL
                   if not name.startswith(("io/", "top/"))]
        sources.append(ROOT / "sim/verify/tb_verify.sv")
        simulator = build_binary(ROOT, "tb_verify",
                                 {"RPC": args.rpc, "SCRATCH_STYLE": args.scratch_style,
                                  "MSG_BYTES": message_capacity,
                                  "CTX_BYTES": context_capacity},
                                 sources, build_directory, env)

        def run_case(case: tuple[Path, list[str]]) -> None:
            directory, arguments = case
            print(f"Running {directory.name}", flush=True)
            run_logged([str(simulator), *arguments], directory / "run.log", env,
                       timeout=900, require_pass=True)

        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            results = [executor.submit(run_case, case) for case in cases]
            for result in results:
                result.result()
    except (OSError, StopIteration, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
