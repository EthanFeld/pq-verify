"""UART command-controller protocol checks using host/proto.py frames."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))
from proto import (  # noqa: E402
    CMD_LOAD_PK,
    CMD_LOAD_SIG,
    CMD_PING,
    CMD_VERIFY,
    STATUS_BAD_CRC,
    STATUS_BAD_LENGTH,
    STATUS_BUSY,
    STATUS_OK,
    decode_response,
    decode_verify_response,
    encode_request,
    encode_verify,
)

CLKS_PER_BIT = 4


async def send_frame(dut, frame: bytes) -> None:
    for byte in frame:
        for bit in (0, *(byte >> index & 1 for index in range(8)), 1):
            await FallingEdge(dut.clk)
            dut.uart_rx_pin.value = bit
            await ClockCycles(dut.clk, CLKS_PER_BIT)
    await FallingEdge(dut.clk)
    dut.uart_rx_pin.value = 1


async def receive_byte(dut) -> int:
    await FallingEdge(dut.uart_tx_pin)
    await ClockCycles(dut.clk, CLKS_PER_BIT // 2)
    assert int(dut.uart_tx_pin.value) == 0, "UART TX start bit missing"
    value = 0
    for index in range(8):
        await ClockCycles(dut.clk, CLKS_PER_BIT)
        value |= int(dut.uart_tx_pin.value) << index
    await ClockCycles(dut.clk, CLKS_PER_BIT)
    assert int(dut.uart_tx_pin.value) == 1, "UART TX stop bit missing"
    return value


async def receive_response(dut, length: int) -> bytes:
    return bytes([await receive_byte(dut) for _ in range(length)])


async def transact(dut, frame: bytes, response_length: int) -> bytes:
    receiver = cocotb.start_soon(receive_response(dut, response_length))
    await send_frame(dut, frame)
    return await receiver


def assert_status(frame: bytes, command: int, status: int) -> None:
    response = decode_response(frame, command)
    assert response.payload[0] == status, (
        f"command 0x{command:02x}: status 0x{response.payload[0]:02x}, "
        f"expected 0x{status:02x}"
    )


@cocotb.test()
async def protocol_commands_crc_length_and_busy(dut) -> None:
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.uart_rx_pin.value = 1
    dut.verify_start_ready.value = 1
    dut.ctx_ready.value = 1
    dut.msg_ready.value = 1
    dut.sig_load_ready.value = 1
    dut.verify_done.value = 0
    dut.verify_valid.value = 1
    dut.verify_cycles.value = 0x12345678
    dut.verify_perms.value = 0x2345
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await ClockCycles(dut.clk, 8)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 8)

    ping = decode_response(
        await transact(dut, encode_request(CMD_PING), 7), CMD_PING
    )
    assert ping.payload == b"SLHV\x01"

    bad_crc = bytearray(encode_request(CMD_PING))
    bad_crc[-1] ^= 1
    assert_status(await transact(dut, bytes(bad_crc), 3), CMD_PING, STATUS_BAD_CRC)

    bad_pk = encode_request(CMD_LOAD_PK, bytes(31))
    assert_status(
        await transact(dut, bad_pk, 3), CMD_LOAD_PK, STATUS_BAD_LENGTH
    )
    pk = bytes(range(32))
    assert_status(
        await transact(dut, encode_request(CMD_LOAD_PK, pk), 3),
        CMD_LOAD_PK,
        STATUS_OK,
    )

    signature = bytes(7856)
    assert_status(
        await transact(dut, encode_request(CMD_LOAD_SIG, signature), 3),
        CMD_LOAD_SIG,
        STATUS_OK,
    )

    verify = encode_verify(0, b"", b"")
    await send_frame(dut, verify)
    await send_frame(dut, encode_request(CMD_PING))
    assert_status(
        await receive_response(dut, 3), CMD_PING, STATUS_BUSY
    )

    verify_receiver = cocotb.start_soon(receive_response(dut, 10))
    await FallingEdge(dut.clk)
    dut.verify_done.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.verify_done.value = 0
    verify_response = decode_response(await verify_receiver, CMD_VERIFY)
    status, valid, cycles, perms = decode_verify_response(verify_response)
    assert (status, valid, cycles, perms) == (
        STATUS_OK,
        True,
        0x12345678,
        0x2345,
    )
