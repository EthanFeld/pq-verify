#!/usr/bin/env python3
"""Run filtered SLH-DSA-SHAKE-128s vectors against the verifier over UART."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import time
from typing import Any

from proto import (
    CMD_LOAD_PK,
    CMD_LOAD_SIG,
    CMD_PING,
    CMD_VERIFY,
    SIGNATURE_BYTES,
    STATUS_OK,
    decode_response,
    decode_verify_response,
    encode_request,
    encode_verify,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.vector_corpus import load_vector_cases  # noqa: E402


def parse_bytes(value: str, field: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"vector field {field!r} is not valid hex") from exc


def load_vectors(path: Path, tc_id: int | None) -> list[dict[str, Any]]:
    raw = load_vector_cases(path)
    vectors = [row for row in raw if tc_id is None or row.get("tcId") == tc_id]
    if not vectors:
        raise ValueError(f"no vector found for tcId {tc_id}" if tc_id else "no vectors found")
    return vectors


def frame_sequence(vector: dict[str, Any]) -> list[tuple[int, bytes]]:
    pk = parse_bytes(vector["pk"], "pk")
    signature = parse_bytes(vector["signature"], "signature")
    message = parse_bytes(vector["message"], "message")
    context = parse_bytes(vector.get("context", ""), "context")
    if vector["mode"] == "internal":
        mode = 0
    elif vector["mode"] == "pure":
        mode = 1
    else:
        raise ValueError(f"tcId {vector.get('tcId')}: unsupported mode {vector['mode']!r}")
    return [
        (CMD_PING, encode_request(CMD_PING)),
        (CMD_LOAD_PK, encode_request(CMD_LOAD_PK, pk)),
        (CMD_LOAD_SIG, encode_request(CMD_LOAD_SIG, signature)),
        (CMD_VERIFY, encode_verify(mode, context, message)),
    ]


def response_size(command: int) -> int:
    if command == CMD_PING:
        return 7
    if command in (CMD_LOAD_PK, CMD_LOAD_SIG):
        return 3
    if command == CMD_VERIFY:
        return 10
    raise ValueError(f"unsupported command 0x{command:02x}")


def read_response(serial_port: Any, command: int) -> bytes:
    data = bytearray()
    deadline = time.monotonic() + 30
    expected = 3 if command == CMD_PING else response_size(command)
    while len(data) < expected:
        chunk = serial_port.read(expected - len(data))
        if chunk:
            data.extend(chunk)
        elif time.monotonic() >= deadline:
            raise TimeoutError(f"timeout waiting for command 0x{command:02x} response")

    # Successful PING has a five-byte identity payload. Error PING has only
    # the three-byte sync/command/status response.
    if command == CMD_PING and data[2] == ord("S"):
        while len(data) < 7:
            chunk = serial_port.read(7 - len(data))
            if chunk:
                data.extend(chunk)
            elif time.monotonic() >= deadline:
                raise TimeoutError(f"timeout waiting for command 0x{command:02x} response")
    return bytes(data)


def append_result(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--vectors", type=Path, default=repo / "vectors" / "shake128s" / "sigver.json"
    )
    parser.add_argument("--tc", type=int, help="run one ACVP tcId")
    parser.add_argument("--dry-run", action="store_true", help="print exact request frames as hex")
    parser.add_argument(
        "--output", type=Path, default=repo / "bench" / "hw_results.csv"
    )
    args = parser.parse_args()
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if not args.dry_run and not args.port:
        try:
            from serial.tools import list_ports  # type: ignore[import-not-found]
        except ImportError:
            parser.error("--port is required; install pyserial to list available ports")
        candidates = [f"{port.device} ({port.description})" for port in list_ports.comports()]
        available = "; ".join(candidates) if candidates else "none detected"
        parser.error(f"--port is required; available serial ports: {available}")

    try:
        vectors = load_vectors(args.vectors, args.tc)
        if args.dry_run:
            for vector in vectors:
                for command, frame in frame_sequence(vector):
                    print(f"{vector['tcId']} {command:02x} {frame.hex()}")
            return 0

        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("pyserial required; install requirements-dev.txt") from exc

        with serial.Serial(args.port, args.baud, timeout=1) as port:
            for vector in vectors:
                commands = frame_sequence(vector)
                for command, frame in commands:
                    port.write(frame)
                    port.flush()
                    raw_response = read_response(port, command)
                    response = decode_response(raw_response, command)
                    if command in (CMD_LOAD_PK, CMD_LOAD_SIG):
                        expected_size = 32 if command == CMD_LOAD_PK else SIGNATURE_BYTES
                        payload = parse_bytes(
                            vector["pk"] if command == CMD_LOAD_PK else vector["signature"],
                            "pk" if command == CMD_LOAD_PK else "signature",
                        )
                        expected_load_status = 0x02 if len(payload) != expected_size else STATUS_OK
                        if response.payload != bytes((expected_load_status,)):
                            raise RuntimeError(
                                f"tcId {vector['tcId']}: load command {command:02x} "
                                f"status {response.payload[0]:02x}, "
                                f"expected {expected_load_status:02x}"
                            )
                    elif command == CMD_PING:
                        if response.payload != b"SLHV\x01":
                            raise RuntimeError("device returned unexpected PING identity")
                    else:
                        status, actual, cycles, perms = decode_verify_response(response)
                        expected = bool(vector["testPassed"])
                        malformed_size = (
                            len(parse_bytes(vector["pk"], "pk")) != 32
                            or len(parse_bytes(vector["signature"], "signature"))
                            != SIGNATURE_BYTES
                        )
                        expected_status = 0x02 if malformed_size else STATUS_OK
                        passed = (
                            status == expected_status
                            and actual == expected
                            and (not malformed_size or (cycles == 0 and perms == 0))
                        )
                        append_result(
                            args.output,
                            {
                                "tcId": vector["tcId"],
                                "mode": vector["mode"],
                                "expected": int(expected),
                                "actual": int(actual),
                                "status": f"0x{status:02x}",
                                "cycles": cycles,
                                "perms": perms,
                                "baud": args.baud,
                                "passed": int(passed),
                            },
                        )
                        print(
                            f"tcId={vector['tcId']} expected={int(expected)} "
                            f"actual={int(actual)} cycles={cycles} perms={perms} "
                            f"{'PASS' if passed else 'FAIL'}"
                        )
                        if not passed:
                            return 1
        return 0
    except (OSError, KeyError, TypeError, ValueError, TimeoutError, RuntimeError) as exc:
        print(f"slhv: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
