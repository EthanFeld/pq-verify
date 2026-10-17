#!/usr/bin/env python3
"""Replay tweakable-hash calls from ACVP traces through the RTL datapath."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.trace import trace_case  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


VECTOR_WIDTH_HEX = 1253


def select_calls(vectors: list[dict]) -> tuple[list[dict], int, int]:
    well_formed = [vector for vector in vectors if len(vector["signature"]) == 7856 * 2
                   and len(vector["pk"]) == 32 * 2
                   and (vector["mode"] == "internal"
                        or len(vector.get("context", "")) <= 255 * 2)]
    fh_calls: list[dict] = []
    t_calls: list[dict] = []
    for vector in well_formed:
        records, result = trace_case(vector)
        if result != vector["testPassed"]:
            raise ValueError(f"Python verifier disagrees with tc{vector['tcId']}")
        for record in records:
            if record["event"] != "hash":
                continue
            kind = record["kind"]
            if kind in {"F", "H"} and len(fh_calls) < 500:
                fh_calls.append(record)
            elif kind in {"Tk", "Tlen"}:
                t_calls.append(record)
    if len(fh_calls) != 500:
        raise ValueError(f"trace set contains only {len(fh_calls)} F/H calls; need 500")
    return fh_calls + t_calls, len(fh_calls), len(t_calls)


def encode_record(record: dict) -> int:
    kind_code = {"F": 0, "H": 1, "Tk": 2, "Tlen": 3}[record["kind"]]
    payload = bytes.fromhex(record["input_hex"])
    address = bytes.fromhex(record["adrs_hex"])
    expected = bytes.fromhex(record["output_hex"])
    if len(payload) < 48 or len(address) != 32 or len(expected) != 16:
        raise ValueError("malformed tweakable-hash trace record")
    message = payload[48:]
    if len(message) > 560:
        raise ValueError("trace message exceeds T_len capacity")
    packed_message = int.from_bytes(message.ljust(560, b"\x00"), "big")
    value = int.from_bytes(expected, "big")
    value |= packed_message << 128
    value |= int.from_bytes(payload[:16], "big") << 4608
    value |= int.from_bytes(address, "big") << 4736
    value |= len(message) << 4992
    value |= kind_code << 5008
    if value.bit_length() > VECTOR_WIDTH_HEX * 4:
        raise ValueError("packed trace record overflow")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    args = parser.parse_args()
    try:
        vectors = json.loads(args.vectors.read_text(encoding="utf-8"))
        calls, fh_count, t_count = select_calls(vectors)
        if not t_count:
            raise ValueError("trace set contains no T_k or T_len calls")

        directory = ROOT / "build/sim_thash_replay"
        directory.mkdir(parents=True, exist_ok=True)
        vector_file = directory / "thash_vectors.hex"
        with vector_file.open("w", encoding="ascii", newline="\n") as stream:
            for call in calls:
                stream.write(f"{encode_record(call):0{VECTOR_WIDTH_HEX}x}\n")

        env = tool_environment()
        sources = [ROOT / "rtl/keccak/keccak_round.sv", ROOT / "rtl/keccak/keccak_f1600.sv",
                   ROOT / "rtl/keccak/shake256.sv", ROOT / "rtl/slh/thash.sv",
                   ROOT / "sim/verify/tb_thash_replay.sv"]
        simulator = build_binary(ROOT, "tb_thash_replay", {"CASES": len(calls)},
                                 sources, directory, env)
        run_logged([str(simulator), f"+vectors_file={vector_file.as_posix()}"],
                   directory / "run.log", env, timeout=1800, require_pass=True)
        print(f"PASS T3.4 replay: F/H={fh_count}; T_k/T_len={t_count}", flush=True)
    except (OSError, StopIteration, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
