#!/usr/bin/env python3
"""Run batched full-verifier mutation and recovery checks."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.board_build import RTL  # noqa: E402
from scripts.run_hash_sim import run_logged, tool_environment, write_hex  # noqa: E402
from scripts.verilator_build import build_binary  # noqa: E402


def create_mutations(message_size: int, context_size: int, count: int) -> list[int]:
    if count != 200:
        raise ValueError("T4.6 acceptance requires exactly 200 mutations")
    if context_size == 0:
        raise ValueError("T4.6 must exercise nonempty context")
    rng = random.Random(0x4F4B5EED)
    sizes = {1: 7856, 2: 32, 3: message_size, 4: context_size}
    descriptors = []
    for kind in range(1, 5):
        choices = [(offset, bit) for offset in range(sizes[kind]) for bit in range(8)]
        for offset, bit in rng.sample(choices, 50):
            descriptors.append((kind << 24) | (offset << 8) | bit)
    rng.shuffle(descriptors)
    return descriptors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tc", type=int, default=342, help="valid pure-mode vector with context")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=4)
    parser.add_argument("--mutations", type=int, default=200)
    parser.add_argument("--vectors", type=Path, default=ROOT / "vectors/shake128s/sigver.json")
    args = parser.parse_args()
    try:
        vectors = json.loads(args.vectors.read_text(encoding="utf-8"))
        vector = next(item for item in vectors if item["tcId"] == args.tc)
        signature = bytes.fromhex(vector["signature"])
        public_key = bytes.fromhex(vector["pk"])
        message = bytes.fromhex(vector["message"])
        context = bytes.fromhex(vector["context"])
        if not vector["testPassed"] or vector["mode"] != "pure":
            raise ValueError("selected case must be a valid pure-mode ACVP vector")
        if len(signature) != 7856 or len(public_key) != 32:
            raise ValueError("selected case has malformed signature or public key")
        if args.mutations != 200 or args.mutations % args.workers:
            raise ValueError("200 mutations must divide evenly among workers")
        mutations = create_mutations(len(message), len(context), args.mutations)

        env = tool_environment()
        directory = ROOT / "build/sim_robust" / f"tc{args.tc}_rpc{args.rpc}"
        directory.mkdir(parents=True, exist_ok=True)
        files = {
            "signature_file": directory / "signature.hex",
            "message_file": directory / "message.hex",
            "context_file": directory / "context.hex",
            "mutation_file": directory / "mutations.hex",
        }
        write_hex(files["signature_file"], [int.from_bytes(signature[i:i + 4], "big")
                                             for i in range(0, len(signature), 4)], 8)
        write_hex(files["message_file"], list(message), 2)
        write_hex(files["context_file"], list(context), 2)
        write_hex(files["mutation_file"], mutations, 8)

        sources = [ROOT / "rtl" / name for name in RTL
                   if not name.startswith(("io/", "top/"))]
        sources.append(ROOT / "sim/verify/tb_verify_robust.sv")
        simulator = build_binary(ROOT, "tb_verify_robust",
                                 {"RPC": args.rpc, "MSG_BYTES": len(message),
                                  "CTX_BYTES": len(context), "MUTATION_COUNT": args.mutations},
                                 sources, directory, env)

        worker_count = args.mutations // args.workers

        def run_worker(worker: int) -> None:
            start = worker * worker_count
            worker_dir = directory / f"worker{worker:02d}"
            worker_dir.mkdir(exist_ok=True)
            arguments = [f"+{key}={value.as_posix()}" for key, value in files.items()]
            arguments += [f"+pk_seed={public_key[:16].hex()}",
                          f"+pk_root={public_key[16:].hex()}",
                          f"+first_mutation={start}", f"+mutation_count={worker_count}"]
            print(f"Starting worker {worker + 1}/{args.workers}: mutations {start}..{start + worker_count - 1}",
                  flush=True)
            run_logged([str(simulator), *arguments], worker_dir / "run.log", env,
                       timeout=1800, require_pass=True)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_worker, worker) for worker in range(args.workers)]
            for future in as_completed(futures):
                future.result()
        print(f"PASS T4.6: {args.mutations} unique one-bit mutations across signature/PK/message/context; "
              f"{args.workers} workers; back-to-back verifies; mid-run reset recovery", flush=True)
    except (OSError, StopIteration, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
