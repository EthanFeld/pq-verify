# UART protocol

UART uses 8N1. Default baud is 115200; board integration may select another rate.
All multibyte integers are little-endian unless stated otherwise.
The board PLL produces 37.125 MHz from the 27 MHz oscillator (PLL divisors
11/8). The board UART divisor is 322 clocks per bit, approximately 115.3 kbaud.
Simulation bypasses the PLL at 27 MHz and uses a 234-cycle UART divisor for
the same baud rate.

## Request frame

```text
0xA5 | CMD | LEN:u32 | PAYLOAD:LEN bytes | CRC8
```

CRC-8 uses polynomial `0x07`, initial value `0x00`, no reflection, and no final
XOR. It covers `CMD`, all four `LEN` bytes, and `PAYLOAD`; the sync byte and CRC
byte are excluded.

| CMD | Request | Payload | Response payload |
| --- | --- | --- | --- |
| `0x01` | PING | empty | ASCII `SLHV` followed by protocol version byte |
| `0x02` | LOAD_PK | 32 public-key bytes | status byte |
| `0x03` | LOAD_SIG | 7,856 signature bytes | status byte |
| `0x04` | VERIFY | mode, context length, context, message length, message | status, verdict, cycles:u32, permutations:u16 |

Every response starts with `0x5A | CMD`. VERIFY payload layout is:

```text
mode:u8 | ctx_len:u8 | ctx:ctx_len bytes | msg_len:u32 | msg:msg_len bytes
```

Mode `0` verifies internal mode and requires zero context length. Mode `1`
verifies pure mode. The message length counts only message bytes. The message is
streamed to H_msg while the frame arrives; it is not stored.

## Status and response framing

Status `0x00` means success. Nonzero values indicate bad CRC (`0x01`), bad
length or command (`0x02`), or busy (`0x03`). A VERIFY CRC error returns status
`0x01` and invalid verdict `0x00`.

Response has no length or CRC field. A successful PING response is 7 bytes total;
an error PING response is 3 bytes. LOAD_PK and LOAD_SIG responses are 3 bytes
total. VERIFY responses are 10 bytes total, including for status errors. Verdict
is `0x01` for valid, `0x00` for invalid.

LOAD_SIG stores bytes in signature order. The RTL memory adapter packs each
consecutive group of four bytes as a big-endian 32-bit word so byte address zero
maps to bits 31:24.
