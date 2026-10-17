"""Unit checks for SHAKE-128s parameters and primitive encodings."""

from __future__ import annotations

from hashlib import shake_256

import pytest

from model.slhdsa_ref import (
    ADRS,
    SHAKE128S,
    base_2b,
    f,
    h,
    h_msg,
    shake256,
    split_digest,
    t_l,
    to_byte,
    to_int,
)


def test_shake128s_derived_parameters_and_signature_layout() -> None:
    params = SHAKE128S
    assert (params.n, params.h, params.d, params.hp) == (16, 63, 7, 9)
    assert (params.a, params.k, params.lg_w, params.w) == (12, 14, 4, 16)
    assert (params.len1, params.len2, params.length, params.m) == (32, 3, 35, 30)
    assert (params.fors_bytes, params.xmss_bytes, params.hypertree_bytes) == (2912, 704, 4928)
    assert params.signature_bytes == 7856


def test_integer_byte_conversions_are_big_endian_and_bounded() -> None:
    assert to_int(bytes.fromhex("0123456789abcdef")) == 0x0123456789ABCDEF
    assert to_byte(0x0123456789ABCDEF, 8) == bytes.fromhex("0123456789abcdef")
    assert to_byte(0, 0) == b""
    with pytest.raises(ValueError):
        to_byte(-1, 1)
    with pytest.raises(ValueError):
        to_byte(256, 1)
    with pytest.raises(ValueError):
        to_byte(0, -1)


def test_base_2b_examples_and_bounds() -> None:
    assert base_2b(bytes.fromhex("abcd"), 4, 4) == [10, 11, 12, 13]
    assert base_2b(bytes.fromhex("abcd"), 2, 8) == [2, 2, 2, 3, 3, 0, 3, 1]
    assert base_2b(b"", 1, 0) == []
    with pytest.raises(ValueError):
        base_2b(b"\x00", 0, 1)
    with pytest.raises(ValueError):
        base_2b(b"\x00", 1, -1)
    with pytest.raises(ValueError):
        base_2b(b"\x00", 2, 5)


def test_adrs_fips_field_layout_aliases_and_clear() -> None:
    address = ADRS()
    address.set_layer_address(0x01020304)
    address.set_tree_address(0x1112131415161718191A1B1C)
    address.set_type_and_clear(3)
    address.set_keypair_address(0x21222324)
    address.set_chain_address(0x31323334)
    address.set_hash_address(0x41424344)
    expected = bytes.fromhex(
        "01020304 11121314 15161718 191a1b1c 00000003 21222324 31323334 41424344"
    )
    assert address.to_bytes() == expected
    assert address.get_keypair_address() == 0x21222324
    address.set_tree_height(0x51525354)
    address.set_tree_index(0x61626364)
    assert address.to_bytes() == bytes.fromhex(
        "01020304 11121314 15161718 191a1b1c 00000003 21222324 51525354 61626364"
    )
    address.set_type_and_clear(4)
    assert address.to_bytes()[16:] == bytes.fromhex("00000004 00000000 00000000 00000000")
    assert ADRS(address.to_bytes()).copy().to_bytes() == address.to_bytes()
    with pytest.raises(ValueError):
        address.set_tree_address(1 << 96)
    with pytest.raises(ValueError):
        ADRS(bytes(31))


def test_shake_f_h_t_and_hmsg_hash_prefixes() -> None:
    seed = bytes(range(16))
    address = ADRS(bytes(range(32)))
    node = bytes(reversed(range(16)))
    pair = node + bytes((i * 3) & 0xFF for i in range(16))
    assert shake256(b"abc", 32) == shake_256(b"abc").digest(32)
    assert f(seed, address, node) == shake_256(seed + address.to_bytes() + node).digest(16)
    assert h(seed, address, pair) == shake_256(seed + address.to_bytes() + pair).digest(16)
    for length in (14 * 16, 35 * 16):
        data = bytes(i & 0xFF for i in range(length))
        assert t_l(seed, address, data) == shake_256(seed + address.to_bytes() + data).digest(16)
    r, pk_seed, pk_root, message = (bytes([value]) * 16 for value in (1, 2, 3, 4))
    assert h_msg(r, pk_seed, pk_root, message) == shake_256(
        r + pk_seed + pk_root + message
    ).digest(30)
    with pytest.raises(ValueError):
        f(seed, address, b"short")
    with pytest.raises(ValueError):
        h(seed, address, node)
    with pytest.raises(ValueError):
        t_l(seed, address, b"not-a-whole-nod")


def test_digest_split_matches_msb_fields() -> None:
    digest = bytes(range(SHAKE128S.m))
    split = split_digest(digest)
    assert split.md == digest[:21]
    assert split.fors_indices == tuple(base_2b(digest[:21], 12, 14))
    tree_value = int.from_bytes(digest[21:28], "big")
    leaf_value = int.from_bytes(digest[28:30], "big")
    assert split.idx_tree == tree_value & ((1 << 54) - 1)
    assert split.idx_leaf == leaf_value & ((1 << 9) - 1)
    with pytest.raises(ValueError):
        split_digest(digest[:-1])
