"""Pure Python SLH-DSA-SHAKE-128s reference verifier (FIPS 205)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from hashlib import shake_256
from typing import Callable, Iterator


TraceSink = Callable[[dict], None]
_TRACE_SINK: ContextVar[TraceSink | None] = ContextVar("slhdsa_trace_sink", default=None)


@contextmanager
def capture_trace(sink: TraceSink) -> Iterator[None]:
    token: Token = _TRACE_SINK.set(sink)
    try:
        yield
    finally:
        _TRACE_SINK.reset(token)


def _trace_hash(
    kind: str, adrs: ADRS | None, data: bytes, output: bytes
) -> None:
    sink = _TRACE_SINK.get()
    if sink is not None:
        sink(
            {
                "event": "hash",
                "kind": kind,
                "adrs_hex": "" if adrs is None else adrs.to_bytes().hex(),
                "input_hex": data.hex(),
                "output_hex": output.hex(),
                "perms": len(data) // 136 + 1,
            }
        )


def _trace_checkpoint(name: str, value: bytes, adrs: ADRS | None = None) -> None:
    sink = _TRACE_SINK.get()
    if sink is not None:
        address = b"" if adrs is None else adrs.to_bytes()
        sink(
            {
                "event": "checkpoint",
                "kind": name,
                "adrs_hex": address.hex(),
                "output_hex": value.hex(),
            }
        )


@dataclass(frozen=True)
class Parameters:
    name: str
    n: int
    h: int
    d: int
    a: int
    k: int
    lg_w: int
    m: int

    @property
    def hp(self) -> int:
        if self.h % self.d:
            raise ValueError("hypertree height must divide evenly across layers")
        return self.h // self.d

    @property
    def w(self) -> int:
        return 1 << self.lg_w

    @property
    def len1(self) -> int:
        return (8 * self.n + self.lg_w - 1) // self.lg_w

    @property
    def len2(self) -> int:
        return ((self.len1 * (self.w - 1)).bit_length() + self.lg_w - 1) // self.lg_w

    @property
    def length(self) -> int:
        return self.len1 + self.len2

    @property
    def fors_bytes(self) -> int:
        return self.k * (self.a + 1) * self.n

    @property
    def xmss_bytes(self) -> int:
        return (self.hp + self.length) * self.n

    @property
    def hypertree_bytes(self) -> int:
        return self.d * self.xmss_bytes

    @property
    def signature_bytes(self) -> int:
        return self.n + self.fors_bytes + self.hypertree_bytes

    @property
    def public_key_bytes(self) -> int:
        return 2 * self.n

    @property
    def md_bytes(self) -> int:
        return (self.k * self.a + 7) // 8

    @property
    def tree_bytes(self) -> int:
        return (self.h - self.hp + 7) // 8

    @property
    def leaf_bytes(self) -> int:
        return (self.hp + 7) // 8


SHAKE128S = Parameters(
    name="SLH-DSA-SHAKE-128s", n=16, h=63, d=7, a=12, k=14, lg_w=4, m=30
)


def to_int(data: bytes) -> int:
    """Interpret bytes as an unsigned big-endian integer."""
    return int.from_bytes(data, "big")


def to_byte(value: int, length: int) -> bytes:
    """Encode value as a fixed-length unsigned big-endian byte string."""
    if length < 0 or value < 0 or value >= (1 << (8 * length)):
        raise ValueError("integer does not fit requested byte length")
    return value.to_bytes(length, "big")


def base_2b(data: bytes, b: int, out_len: int) -> list[int]:
    """Read out_len consecutive b-bit digits, most-significant bits first."""
    if b <= 0 or out_len < 0:
        raise ValueError("b must be positive and out_len nonnegative")
    if out_len * b > 8 * len(data):
        raise ValueError("input does not contain enough bits")
    value = int.from_bytes(data, "big")
    total_bits = 8 * len(data)
    mask = (1 << b) - 1
    return [
        (value >> (total_bits - (i + 1) * b)) & mask for i in range(out_len)
    ]


class ADRS:
    """FIPS 205 32-byte address, stored as eight big-endian 32-bit words."""

    WOTS_HASH = 0
    WOTS_PK = 1
    TREE = 2
    FORS_TREE = 3
    FORS_ROOTS = 4

    def __init__(self, data: bytes | None = None):
        if data is None:
            self._words = [0] * 8
        else:
            if len(data) != 32:
                raise ValueError("ADRS must be exactly 32 bytes")
            self._words = [int.from_bytes(data[i : i + 4], "big") for i in range(0, 32, 4)]

    def copy(self) -> ADRS:
        return ADRS(self.to_bytes())

    def to_bytes(self) -> bytes:
        return b"".join(word.to_bytes(4, "big") for word in self._words)

    @staticmethod
    def _check_u32(value: int) -> None:
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("ADRS field must fit 32 bits")

    def set_layer_address(self, layer: int) -> None:
        self._check_u32(layer)
        self._words[0] = layer

    def set_tree_address(self, tree: int) -> None:
        if not 0 <= tree < (1 << 96):
            raise ValueError("tree address must fit 96 bits")
        encoded = tree.to_bytes(12, "big")
        self._words[1:4] = [
            int.from_bytes(encoded[i : i + 4], "big") for i in range(0, 12, 4)
        ]

    def set_type_and_clear(self, address_type: int) -> None:
        self._check_u32(address_type)
        self._words[4] = address_type
        self._words[5:8] = [0, 0, 0]

    def set_keypair_address(self, keypair: int) -> None:
        self._check_u32(keypair)
        self._words[5] = keypair

    def get_keypair_address(self) -> int:
        return self._words[5]

    def set_chain_address(self, chain: int) -> None:
        self._check_u32(chain)
        self._words[6] = chain

    def set_tree_height(self, height: int) -> None:
        self._check_u32(height)
        self._words[6] = height

    def set_hash_address(self, address: int) -> None:
        self._check_u32(address)
        self._words[7] = address

    def set_tree_index(self, index: int) -> None:
        self._check_u32(index)
        self._words[7] = index

    def get_tree_index(self) -> int:
        return self._words[7]


def shake256(data: bytes, output_length: int) -> bytes:
    if output_length < 0:
        raise ValueError("output_length must be nonnegative")
    return shake_256(data).digest(output_length)


def _check_node(node: bytes, params: Parameters) -> None:
    if len(node) != params.n:
        raise ValueError(f"node must be {params.n} bytes")


def f(pk_seed: bytes, adrs: ADRS, message: bytes, params: Parameters = SHAKE128S) -> bytes:
    _check_node(pk_seed, params)
    _check_node(message, params)
    data = pk_seed + adrs.to_bytes() + message
    output = shake256(data, params.n)
    _trace_hash("F", adrs, data, output)
    return output


def h(pk_seed: bytes, adrs: ADRS, message: bytes, params: Parameters = SHAKE128S) -> bytes:
    _check_node(pk_seed, params)
    if len(message) != 2 * params.n:
        raise ValueError("H input must contain two n-byte nodes")
    data = pk_seed + adrs.to_bytes() + message
    output = shake256(data, params.n)
    _trace_hash("H", adrs, data, output)
    return output


def t_l(pk_seed: bytes, adrs: ADRS, message: bytes, params: Parameters = SHAKE128S) -> bytes:
    _check_node(pk_seed, params)
    if len(message) % params.n:
        raise ValueError("T_l input must contain whole n-byte nodes")
    data = pk_seed + adrs.to_bytes() + message
    output = shake256(data, params.n)
    kind = "Tk" if len(message) == 14 * params.n else "Tlen"
    _trace_hash(kind, adrs, data, output)
    return output


def h_msg(
    r: bytes, pk_seed: bytes, pk_root: bytes, message: bytes, params: Parameters = SHAKE128S
) -> bytes:
    _check_node(r, params)
    _check_node(pk_seed, params)
    _check_node(pk_root, params)
    data = r + pk_seed + pk_root + message
    output = shake256(data, params.m)
    _trace_hash("Hmsg", None, data, output)
    return output


@dataclass(frozen=True)
class DigestSplit:
    md: bytes
    fors_indices: tuple[int, ...]
    idx_tree: int
    idx_leaf: int


def split_digest(digest: bytes, params: Parameters = SHAKE128S) -> DigestSplit:
    if len(digest) != params.m:
        raise ValueError(f"digest must be {params.m} bytes")
    md = digest[: params.md_bytes]
    fors_indices = tuple(base_2b(md, params.a, params.k))
    tree_start = params.md_bytes
    tree_end = tree_start + params.tree_bytes
    idx_tree = to_int(digest[tree_start:tree_end]) & ((1 << (params.h - params.hp)) - 1)
    idx_leaf = to_int(digest[tree_end : tree_end + params.leaf_bytes]) & (
        (1 << params.hp) - 1
    )
    return DigestSplit(md, fors_indices, idx_tree, idx_leaf)


def wots_digits(message: bytes, params: Parameters = SHAKE128S) -> tuple[int, ...]:
    _check_node(message, params)
    msg_digits = base_2b(message, params.lg_w, params.len1)
    checksum = sum((params.w - 1) - digit for digit in msg_digits)
    shift = (8 - ((params.len2 * params.lg_w) % 8)) % 8
    checksum <<= shift
    checksum_len = (params.len2 * params.lg_w + 7) // 8
    checksum_digits = base_2b(to_byte(checksum, checksum_len), params.lg_w, params.len2)
    return tuple(msg_digits + checksum_digits)


def _chain(
    value: bytes,
    start: int,
    steps: int,
    pk_seed: bytes,
    adrs: ADRS,
    params: Parameters,
) -> bytes:
    _check_node(value, params)
    if start < 0 or steps < 0 or start + steps > params.w - 1:
        raise ValueError("WOTS+ chain range is out of bounds")
    for address in range(start, start + steps):
        adrs.set_hash_address(address)
        value = f(pk_seed, adrs, value, params)
    return value


def wots_pk_from_sig(
    signature: bytes,
    message: bytes,
    pk_seed: bytes,
    adrs: ADRS,
    params: Parameters = SHAKE128S,
) -> bytes:
    if len(signature) != params.length * params.n:
        raise ValueError("WOTS+ signature has incorrect length")
    digits = wots_digits(message, params)
    ends = []
    for i, digit in enumerate(digits):
        adrs.set_chain_address(i)
        start = i * params.n
        ends.append(
            _chain(
                signature[start : start + params.n],
                digit,
                params.w - 1 - digit,
                pk_seed,
                adrs,
                params,
            )
        )
    pk_adrs = adrs.copy()
    pk_adrs.set_type_and_clear(ADRS.WOTS_PK)
    pk_adrs.set_keypair_address(adrs.get_keypair_address())
    result = t_l(pk_seed, pk_adrs, b"".join(ends), params)
    _trace_checkpoint("wots_pk", result, pk_adrs)
    return result


def xmss_pk_from_sig(
    index: int,
    signature: bytes,
    message: bytes,
    pk_seed: bytes,
    adrs: ADRS,
    params: Parameters = SHAKE128S,
) -> bytes:
    if not 0 <= index < (1 << params.hp):
        raise ValueError("XMSS leaf index out of range")
    if len(signature) != params.xmss_bytes:
        raise ValueError("XMSS signature has incorrect length")

    adrs.set_type_and_clear(ADRS.WOTS_HASH)
    adrs.set_keypair_address(index)
    node = wots_pk_from_sig(
        signature[: params.length * params.n], message, pk_seed, adrs, params
    )
    auth = signature[params.length * params.n :]

    adrs.set_type_and_clear(ADRS.TREE)
    adrs.set_tree_index(index)
    for level in range(params.hp):
        sibling = auth[level * params.n : (level + 1) * params.n]
        adrs.set_tree_height(level + 1)
        if ((index >> level) & 1) == 0:
            adrs.set_tree_index(adrs.get_tree_index() // 2)
            node = h(pk_seed, adrs, node + sibling, params)
        else:
            adrs.set_tree_index((adrs.get_tree_index() - 1) // 2)
            node = h(pk_seed, adrs, sibling + node, params)
    _trace_checkpoint("xmss_root", node, adrs)
    return node


def ht_verify(
    message: bytes,
    signature: bytes,
    pk_seed: bytes,
    idx_tree: int,
    idx_leaf: int,
    pk_root: bytes,
    params: Parameters = SHAKE128S,
) -> bool:
    if len(message) != params.n or len(pk_seed) != params.n or len(pk_root) != params.n:
        return False
    if len(signature) != params.hypertree_bytes:
        return False
    if not 0 <= idx_leaf < (1 << params.hp) or idx_tree < 0:
        return False

    adrs = ADRS()
    adrs.set_tree_address(idx_tree)
    node = b""
    for layer in range(params.d):
        if layer:
            idx_leaf = idx_tree & ((1 << params.hp) - 1)
            idx_tree >>= params.hp
            adrs.set_layer_address(layer)
            adrs.set_tree_address(idx_tree)
        start = layer * params.xmss_bytes
        xmss_signature = signature[start : start + params.xmss_bytes]
        layer_message = message if layer == 0 else node
        node = xmss_pk_from_sig(idx_leaf, xmss_signature, layer_message, pk_seed, adrs, params)
    return node == pk_root


def fors_pk_from_sig(
    signature: bytes,
    md: bytes,
    pk_seed: bytes,
    adrs: ADRS,
    params: Parameters = SHAKE128S,
) -> bytes:
    if len(signature) != params.fors_bytes:
        raise ValueError("FORS signature has incorrect length")
    indices = base_2b(md, params.a, params.k)
    roots: list[bytes] = []
    tree_signature_bytes = (params.a + 1) * params.n
    for i, index in enumerate(indices):
        base = i * tree_signature_bytes
        secret = signature[base : base + params.n]
        auth = signature[base + params.n : base + tree_signature_bytes]
        adrs.set_tree_height(0)
        adrs.set_tree_index(i * (1 << params.a) + index)
        node = f(pk_seed, adrs, secret, params)
        for level in range(params.a):
            sibling = auth[level * params.n : (level + 1) * params.n]
            adrs.set_tree_height(level + 1)
            if ((index >> level) & 1) == 0:
                adrs.set_tree_index(adrs.get_tree_index() // 2)
                node = h(pk_seed, adrs, node + sibling, params)
            else:
                adrs.set_tree_index((adrs.get_tree_index() - 1) // 2)
                node = h(pk_seed, adrs, sibling + node, params)
        roots.append(node)

    pk_adrs = adrs.copy()
    pk_adrs.set_type_and_clear(ADRS.FORS_ROOTS)
    pk_adrs.set_keypair_address(adrs.get_keypair_address())
    result = t_l(pk_seed, pk_adrs, b"".join(roots), params)
    _trace_checkpoint("fors_pk", result, pk_adrs)
    return result


def slh_verify_internal(
    message: bytes,
    signature: bytes,
    public_key: bytes,
    params: Parameters = SHAKE128S,
) -> bool:
    if len(public_key) != params.public_key_bytes or len(signature) != params.signature_bytes:
        return False
    pk_seed = public_key[: params.n]
    pk_root = public_key[params.n :]
    r = signature[: params.n]
    fors_start = params.n
    fors_end = fors_start + params.fors_bytes
    digest = h_msg(r, pk_seed, pk_root, message, params)
    split = split_digest(digest, params)
    _trace_checkpoint("digest", digest)

    adrs = ADRS()
    adrs.set_tree_address(split.idx_tree)
    adrs.set_type_and_clear(ADRS.FORS_TREE)
    adrs.set_keypair_address(split.idx_leaf)
    fors_pk = fors_pk_from_sig(
        signature[fors_start:fors_end], split.md, pk_seed, adrs, params
    )
    return ht_verify(
        fors_pk,
        signature[fors_end:],
        pk_seed,
        split.idx_tree,
        split.idx_leaf,
        pk_root,
        params,
    )


def slh_verify(
    message: bytes,
    signature: bytes,
    context: bytes,
    public_key: bytes,
    params: Parameters = SHAKE128S,
) -> bool:
    if len(context) > 255:
        return False
    message_prime = b"\x00" + bytes((len(context),)) + context + message
    return slh_verify_internal(message_prime, signature, public_key, params)
