#!/usr/bin/env python3
"""Compare trace-based cycle predictions against core regression logs."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.perf_model import predict_cycles  # noqa: E402
from model.trace import trace_case  # noqa: E402
from model.vector_corpus import load_vector_cases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    parser.add_argument("--tolerance", type=float, default=0.02)
    args = parser.parse_args()
    if not 0 < args.tolerance < 1:
        parser.error("--tolerance must be between 0 and 1")

    vectors = load_vector_cases(args.vectors)
    if not isinstance(vectors, list):
        print("vector file must contain a list or a header/tests document", file=sys.stderr)
        return 1
    selected = [vector for vector in vectors if len(vector["signature"]) == 7856 * 2
                and len(vector["pk"]) == 32 * 2
                and (vector["mode"] == "internal"
                     or len(vector.get("context", "")) <= 255 * 2)]
    if not selected:
        print("no well-formed core vectors found", file=sys.stderr)
        return 1

    worst = 0.0
    for vector in selected:
        records, result = trace_case(vector)
        if result != vector["testPassed"]:
            print(f"Python reference mismatch for tc{vector['tcId']}", file=sys.stderr)
            return 1
        log = ROOT / "build/sim_verify" / f"tc{vector['tcId']}_rpc{args.rpc}" / "run.log"
        if not log.is_file():
            print(f"missing core simulation log: {log}", file=sys.stderr)
            return 1
        match = re.search(r"PASS verify tc=\d+ RPC=\d+ valid=\d+ cycles=(\d+) perms=(\d+)",
                          log.read_text(encoding="utf-8", errors="replace"))
        if not match:
            print(f"missing PASS cycle marker: {log}", file=sys.stderr)
            return 1
        measured, measured_perms = map(int, match.groups())
        predicted = predict_cycles(records, rpc=args.rpc, lane_bytes=1, load_cycles=0,
                                   overlap=False, permute_overhead=0, call_overhead=14)
        trace_perms = sum(int(record["perms"]) for record in records
                          if record.get("event") == "hash")
        if trace_perms != measured_perms:
            print(f"tc{vector['tcId']}: model/log permutation mismatch {trace_perms}!={measured_perms}",
                  file=sys.stderr)
            return 1
        error = abs(predicted - measured) / measured
        worst = max(worst, error)
        if error > args.tolerance:
            print(f"tc{vector['tcId']}: predicted {predicted}, measured {measured}, "
                  f"error {error:.2%} > {args.tolerance:.2%}", file=sys.stderr)
            return 1
    print(f"PASS cycle model RPC={args.rpc}: {len(selected)} vectors, max error {worst:.2%} "
          f"(limit {args.tolerance:.2%})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
