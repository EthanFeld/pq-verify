"""Estimate verifier cycles from a Python hash-call trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

SHAKE256_RATE_BYTES = 136
FIXED_HASH_PREFIX_BYTES = 48
HASH_LANE_BYTES = 8


def predict_cycles(
    records: Iterable[dict[str, Any]],
    *,
    rpc: int,
    lane_bytes: int,
    load_cycles: int,
    overlap: bool,
    permute_overhead: int = 0,
    call_overhead: int = 14,
    stage_overhead_cycles: int = 18_851,
    inline_f_overhead: int = 5,
    wots_prefetch_saving: int = 16,
    thash_response_saving: int = 1,
    wots_chain_overlap_saving: int = 1,
    wots_word_read_saving: int = 17,
    thash_tk_word_read_saving: int = 621,
    thash_tlen_word_read_saving: int = 1_518,
    auth_word_read_saving: int = 24,
    fors_secret_word_read_saving: int = 24,
) -> int:
    if rpc not in {1, 2, 3, 4, 6, 8, 12, 24}:
        raise ValueError("rpc must be one of 1, 2, 3, 4, 6, 8, 12, 24")
    if lane_bytes <= 0 or min(load_cycles, permute_overhead, call_overhead,
                               stage_overhead_cycles, inline_f_overhead,
                               wots_prefetch_saving, thash_response_saving,
                               wots_chain_overlap_saving, wots_word_read_saving,
                               thash_tk_word_read_saving,
                               thash_tlen_word_read_saving,
                               auth_word_read_saving,
                               fors_secret_word_read_saving) < 0:
        raise ValueError("lane_bytes must be positive and cycle overheads nonnegative")

    records = list(records)
    cycles = stage_overhead_cycles
    one_permutation = 24 // rpc + permute_overhead
    previous_permute_cycles = 0
    for record in records:
        if record.get("event") != "hash":
            continue
        try:
            input_bytes = len(bytes.fromhex(record["input_hex"]))
            permutations = int(record["perms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("hash trace records need valid input_hex and perms") from exc
        expected_permutations = input_bytes // SHAKE256_RATE_BYTES + 1
        if permutations != expected_permutations:
            raise ValueError(
                f"trace says {permutations} permutations for {input_bytes} bytes; "
                f"SHAKE-256 requires {expected_permutations}"
            )
        # F/H now bulk-load their fixed prefix and register-resident pair into
        # SHAKE in one accepted transfer. Request/control handshakes remain in
        # per_call_overhead. H_msg and memory-backed thash keep lane streaming.
        tail_bytes = max(0, input_bytes - FIXED_HASH_PREFIX_BYTES)
        inline_pair = record.get("kind") in {"F", "H"}
        tail_cycles = math.ceil(tail_bytes / (HASH_LANE_BYTES if inline_pair else lane_bytes))
        fixed_prefix_cycles = 2 * (FIXED_HASH_PREFIX_BYTES // HASH_LANE_BYTES)
        if record.get("kind") == "Hmsg":
            tail_send_cycles = math.ceil(tail_bytes / HASH_LANE_BYTES) if tail_bytes else 1
            absorb_cycles = fixed_prefix_cycles + tail_cycles + tail_send_cycles
        elif inline_pair:
            absorb_cycles = 1
        else:
            tail_send_cycles = math.ceil(tail_bytes / HASH_LANE_BYTES)
            absorb_cycles = fixed_prefix_cycles + 2 * tail_cycles + tail_send_cycles
        permute_cycles = permutations * one_permutation
        per_call_overhead = inline_f_overhead if record.get("kind") == "F" else call_overhead
        if overlap:
            # T7.1 hides the next call's setup behind the current call's
            # permutation. Absorption and permutation within one sponge call
            # still share one state and therefore run in sequence.
            setup_cycles = per_call_overhead + max(0, load_cycles - previous_permute_cycles)
        else:
            setup_cycles = per_call_overhead + load_cycles
        cycles += setup_cycles
        cycles += absorb_cycles + permute_cycles
        previous_permute_cycles = permute_cycles

    # A WOTS chain with at least one F call can prefetch the following
    # chain's 16-byte signature while its final permutation is running.
    # The cached chain consumes one byte per cycle instead of request/wait
    # pairs, saving 16 controller cycles. E3 also forwards the next F request
    # on each same-chain response, avoiding one controller cycle per link.
    # thash's combinational response removes one response handoff per call.
    prefetched_chains = set()
    f_calls_by_chain: dict[str, int] = {}
    thash_calls = 0
    memory_word_read_savings = 0
    for record in records:
        if record.get("event") != "hash":
            continue
        if record.get("kind") != "Hmsg":
            thash_calls += 1
        if record.get("kind") != "F":
            if record.get("kind") == "H":
                memory_word_read_savings += auth_word_read_saving
            elif record.get("kind") == "Tk":
                memory_word_read_savings += thash_tk_word_read_saving
            elif record.get("kind") == "Tlen":
                memory_word_read_savings += thash_tlen_word_read_saving
            continue
        address = record.get("adrs_hex", "")
        if len(address) != 64:
            continue
        if address[32:40] == "00000003":
            memory_word_read_savings += fors_secret_word_read_saving
            continue
        if address[32:40] != "00000000":
            continue
        f_calls_by_chain[address[:56]] = f_calls_by_chain.get(address[:56], 0) + 1
        try:
            chain_number = int(address[48:56], 16)
        except ValueError as exc:
            raise ValueError("F trace record has an invalid address") from exc
        if chain_number < 34:
            prefetched_chains.add(address[:56])
    cycles -= len(prefetched_chains) * wots_prefetch_saving
    cycles -= thash_calls * thash_response_saving
    cycles -= sum(max(0, count - 1) for count in f_calls_by_chain.values()) * wots_chain_overlap_saving
    # E4 packs two synchronous 32-bit RAM words into each SHAKE lane and
    # caches each following 16-byte WOTS signature element as four words.
    # The auth-path extension reads FORS/XMSS nodes as four words and FORS
    # secrets likewise. These savings are measured against the validated model.
    cycles -= memory_word_read_savings
    cycles -= len(prefetched_chains) * wots_word_read_saving
    return cycles


def read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def trace_identity(path: Path, records: list[dict[str, Any]]) -> tuple[int, str]:
    if records:
        tcid = records[0].get("tcId")
        mode = next((row.get("mode") for row in records if row.get("mode")), None)
        if tcid is not None and mode in {"internal", "pure"}:
            return int(tcid), str(mode)

    # Early rejects can produce a valid empty trace. Preserve them using the
    # stable filename emitted by model/trace.py rather than dropping the case.
    match = re.fullmatch(r"tc-(\d+)-(internal|pure)", path.stem)
    if not match:
        raise ValueError(f"cannot determine vector identity from empty trace {path}")
    return int(match.group(1)), match.group(2)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, default=repo / "vectors" / "shake128s" / "traces")
    parser.add_argument("--output", type=Path, default=repo / "bench" / "predicted.csv")
    parser.add_argument("--rpc", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument(
        "--lane-bytes",
        type=int,
        default=1,
        help="external tail-stream bytes consumed per cycle (default RTL byte stream: 1; inline F/H pairs use 8)",
    )
    parser.add_argument("--load-cycles", type=int, default=0)
    parser.add_argument("--permute-overhead", type=int, default=0)
    parser.add_argument("--call-overhead", type=int, default=14,
                        help="request/reply and controller cycles per hash call (default: 14)")
    parser.add_argument("--stage-overhead-cycles", type=int, default=18_851,
                        help="fixed measured verifier stage-controller overhead (default: 18851)")
    parser.add_argument("--inline-f-overhead", type=int, default=5,
                        help="request/response cycles for an inline F call (default: 5)")
    parser.add_argument("--wots-prefetch-saving", type=int, default=16,
                        help="cycles saved per prefetched WOTS signature input (default: 16)")
    parser.add_argument(
        "--overlap",
        action="store_true",
        help="hide each call's preload behind the previous call's permutation",
    )
    parser.add_argument("--frequency-mhz", type=float, default=50.143)
    args = parser.parse_args()
    if not math.isfinite(args.frequency_mhz) or args.frequency_mhz <= 0:
        parser.error("--frequency-mhz must be positive")

    trace_paths = sorted(
        path
        for path in args.traces.glob("*.jsonl")
        if path.is_file()
    )
    if not trace_paths:
        parser.error(f"no JSONL traces found in {args.traces}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        columns = ("config", "tcId", "mode", "cycles", "latency_us", "perms")
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for path in trace_paths:
            records = read_trace(path)
            hash_calls = [row for row in records if row.get("event") == "hash"]
            tcid, mode = trace_identity(path, records)
            total_perms = sum(int(row["perms"]) for row in hash_calls)
            for rpc in args.rpc:
                cycles = predict_cycles(
                    records,
                    rpc=rpc,
                    lane_bytes=args.lane_bytes,
                    load_cycles=args.load_cycles,
                    overlap=args.overlap,
                    permute_overhead=args.permute_overhead,
                    call_overhead=args.call_overhead,
                    stage_overhead_cycles=args.stage_overhead_cycles,
                    inline_f_overhead=args.inline_f_overhead,
                    wots_prefetch_saving=args.wots_prefetch_saving,
                )
                writer.writerow(
                    {
                        "config": f"rpc{rpc}{'_overlap' if args.overlap else ''}",
                        "tcId": tcid,
                        "mode": mode,
                        "cycles": cycles,
                        "latency_us": f"{cycles / args.frequency_mhz:.6f}",
                        "perms": total_perms,
                    }
                )
    print(f"Wrote predictions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
