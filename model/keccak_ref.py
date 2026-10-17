"""Small, readable Keccak-f[1600] and SHAKE-256 reference implementation."""

from __future__ import annotations


MASK64 = (1 << 64) - 1
RATE_SHAKE256 = 136
ROUND_CONSTANTS = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)
RHO = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)


def _rol64(value: int, amount: int) -> int:
    if amount == 0:
        return value & MASK64
    return ((value << amount) | (value >> (64 - amount))) & MASK64


def keccak_round(state: tuple[int, ...] | list[int], round_index: int) -> tuple[int, ...]:
    """Apply one Keccak-f[1600] round to 25 little-endian 64-bit lanes."""
    if len(state) != 25:
        raise ValueError("Keccak state must contain 25 lanes")
    if not 0 <= round_index < 24:
        raise ValueError("round_index must be in [0, 23]")

    a = [lane & MASK64 for lane in state]
    c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
    d = [c[(x - 1) % 5] ^ _rol64(c[(x + 1) % 5], 1) for x in range(5)]
    a = [lane ^ d[index % 5] for index, lane in enumerate(a)]

    b = [0] * 25
    for y in range(5):
        for x in range(5):
            new_x = y
            new_y = (2 * x + 3 * y) % 5
            b[new_x + 5 * new_y] = _rol64(a[x + 5 * y], RHO[x][y])

    a = [
        b[x + 5 * y]
        ^ ((~b[((x + 1) % 5) + 5 * y]) & b[((x + 2) % 5) + 5 * y])
        for y in range(5)
        for x in range(5)
    ]
    a[0] ^= ROUND_CONSTANTS[round_index]
    return tuple(lane & MASK64 for lane in a)


def keccak_f1600(state: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    if len(state) != 25:
        raise ValueError("Keccak state must contain 25 lanes")
    result = tuple(state)
    for round_index in range(24):
        result = keccak_round(result, round_index)
    return result


def _state_bytes(state: tuple[int, ...]) -> bytes:
    return b"".join(lane.to_bytes(8, "little") for lane in state)


def shake256(data: bytes, output_length: int) -> bytes:
    """SHAKE-256 with the FIPS 202 136-byte rate and 0x1F domain suffix."""
    if output_length < 0:
        raise ValueError("output_length must be nonnegative")
    padded = bytearray(data)
    padded.append(0x1F)
    padded.extend(b"\x00" * ((RATE_SHAKE256 - len(padded) % RATE_SHAKE256) % RATE_SHAKE256))
    padded[-1] |= 0x80

    state = (0,) * 25
    for offset in range(0, len(padded), RATE_SHAKE256):
        block = padded[offset : offset + RATE_SHAKE256]
        lanes = list(state)
        for lane_index in range(RATE_SHAKE256 // 8):
            lanes[lane_index] ^= int.from_bytes(
                block[lane_index * 8 : lane_index * 8 + 8], "little"
            )
        state = keccak_f1600(lanes)

    output = bytearray()
    while len(output) < output_length:
        output.extend(_state_bytes(state)[:RATE_SHAKE256])
        if len(output) < output_length:
            state = keccak_f1600(state)
    return bytes(output[:output_length])
