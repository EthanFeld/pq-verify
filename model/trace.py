"""Emit FIPS hash-call and stage-checkpoint traces for filtered ACVP cases."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .slhdsa_ref import SHAKE128S, capture_trace, slh_verify, slh_verify_internal
except ImportError:  # Support `python model/trace.py` as well as package imports.
    from slhdsa_ref import SHAKE128S, capture_trace, slh_verify, slh_verify_internal


def trace_case(vector: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []

    def collect(record: dict[str, Any]) -> None:
        records.append(
            {
                "seq": len(records),
                "tcId": vector["tcId"],
                "mode": vector["mode"],
                **record,
            }
        )

    message = bytes.fromhex(vector["message"])
    signature = bytes.fromhex(vector["signature"])
    public_key = bytes.fromhex(vector["pk"])
    context = bytes.fromhex(vector.get("context", ""))
    with capture_trace(collect):
        if vector["mode"] == "internal":
            valid = slh_verify_internal(message, signature, public_key, SHAKE128S)
        elif vector["mode"] == "pure":
            valid = slh_verify(message, signature, context, public_key, SHAKE128S)
        else:
            raise ValueError(f"unsupported mode {vector['mode']!r}")
    return records, valid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vectors",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "vectors"
        / "shake128s"
        / "sigver.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "vectors"
        / "shake128s"
        / "traces",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")

    vectors = json.loads(args.vectors.read_text(encoding="utf-8"))[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    failures = 0
    for vector in vectors:
        records, result = trace_case(vector)
        name = f"tc-{vector['tcId']}-{vector['mode']}.jsonl"
        trace_path = args.output / name
        trace_path.write_text(
            "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
            encoding="utf-8",
        )
        hash_calls = [record for record in records if record["event"] == "hash"]
        by_kind = Counter(record["kind"] for record in hash_calls)
        perms_by_kind: Counter[str] = Counter()
        by_stage: Counter[str] = Counter()
        for record in hash_calls:
            perms_by_kind[record["kind"]] += record["perms"]
            if record["kind"] == "Hmsg":
                stage = "Hmsg"
            else:
                address = bytes.fromhex(record["adrs_hex"])
                address_type = int.from_bytes(address[16:20], "big")
                stage = "FORS" if address_type in (3, 4) else "HT"
            by_stage[stage] += record["perms"]
        summary = {
            "tcId": vector["tcId"],
            "mode": vector["mode"],
            "testPassed": vector["testPassed"],
            "result": result,
            "matches": result == vector["testPassed"],
            "hash_calls": len(hash_calls),
            "perms": sum(record["perms"] for record in hash_calls),
            "calls_by_kind": dict(sorted(by_kind.items())),
            "perms_by_kind": dict(sorted(perms_by_kind.items())),
            "perms_by_stage": dict(sorted(by_stage.items())),
            "trace": name,
        }
        summaries.append(summary)
        failures += not summary["matches"]

    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    print(f"Traced {len(summaries)} vectors; summary: {summary_path}")
    print(f"Model mismatches: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
