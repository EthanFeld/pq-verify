"""Framing helpers for the SLH-DSA verifier UART protocol."""

from __future__ import annotations

from dataclasses import dataclass
import struct

SYNC_REQUEST = 0xA5
SYNC_RESPONSE = 0x5A
VERSION = 1

CMD_PING = 0x01
CMD_LOAD_PK = 0x02
CMD_LOAD_SIG = 0x03
CMD_VERIFY = 0x04

STATUS_OK = 0x00
STATUS_BAD_CRC = 0x01
STATUS_BAD_LENGTH = 0x02
STATUS_BUSY = 0x03

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 7856


def crc8(data: bytes, initial: int = 0) -> int:
    """CRC-8/ATM: polynomial 0x07, MSB first, no reflection or final XOR."""
    if not 0 <= initial <= 0xFF:
        raise ValueError("initial CRC must fit one byte")
    value = initial
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xFF if value & 0x80 else (value << 1) & 0xFF
    return value


def encode_request(command: int, payload: bytes = b"") -> bytes:
    if not 0 <= command <= 0xFF:
        raise ValueError("command must fit one byte")
    if len(payload) > 0xFFFFFFFF:
        raise ValueError("payload exceeds protocol length field")
    header = bytes((command,)) + struct.pack("<I", len(payload))
    body = header + payload
    return bytes((SYNC_REQUEST,)) + body + bytes((crc8(body),))


def encode_verify(mode: int, context: bytes, message: bytes) -> bytes:
    if mode not in (0, 1):
        raise ValueError("mode must be 0 (internal) or 1 (pure)")
    if len(context) > 255:
        raise ValueError("context exceeds 255 bytes")
    if mode == 0 and context:
        raise ValueError("internal mode does not accept a context")
    payload = bytes((mode, len(context))) + context + struct.pack("<I", len(message)) + message
    return encode_request(CMD_VERIFY, payload)


@dataclass(frozen=True)
class Response:
    command: int
    payload: bytes


def decode_response(data: bytes, expected_command: int | None = None) -> Response:
    if len(data) < 2 or data[0] != SYNC_RESPONSE:
        raise ValueError("invalid response sync or truncated response")
    command = data[1]
    if expected_command is not None and command != expected_command:
        raise ValueError(f"unexpected response command 0x{command:02x}")
    if command not in (CMD_PING, CMD_LOAD_PK, CMD_LOAD_SIG, CMD_VERIFY):
        raise ValueError(f"unknown response command 0x{command:02x}")
    if command == CMD_PING:
        allowed_lengths = (3, 7)
    elif command == CMD_VERIFY:
        allowed_lengths = (10,)
    else:
        allowed_lengths = (3,)
    if len(data) not in allowed_lengths:
        raise ValueError("response has incorrect length")
    return Response(command=command, payload=data[2:])


def decode_verify_response(response: Response) -> tuple[int, bool, int, int]:
    if response.command != CMD_VERIFY or len(response.payload) != 8:
        raise ValueError("not a VERIFY response")
    status, verdict = response.payload[:2]
    cycles, perms = struct.unpack("<IH", response.payload[2:])
    return status, bool(verdict), cycles, perms
