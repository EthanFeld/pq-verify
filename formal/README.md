# Formal verification

Formal targets check control and protocol properties with SymbiYosys. Data-path
correctness for the complete SLH-DSA verifier remains covered by simulation.

## Current targets

| Target | Mode | Parameters | Properties | Limits |
| --- | --- | --- | --- | --- |
| `smoke` | prove + cover | — | Formal flow runs assertions and reaches a cover | Infrastructure check only |
| `keccak_control` | prove + cover | RPC 1/2/3/4, `IN_PLACE` 0/1 | Reset outputs, exact busy/done latency, one-cycle `done`, ignored busy starts | Uses the formal-only `FORMAL_CONTROL_ONLY` state-data abstraction; Keccak state data is not checked |
| `keccak_round` | Yosys SAT + cover | Generic vs LUT4 for RPC 1/2/4; portable vs Gowin LUT4 cell for RPC1 | Full-state output equivalence for every legal starting round | Combinational equivalence only; SHAKE and end-to-end data flow are separate |
| `shake256` | BMC + cover | RPC1/4; two consecutive 0, 135, 136, 137 or 272-byte messages; bulk F/H 64/80 bytes at depth 128 | Input backpressure, bulk accept, one permutation/response for bulk, final-word accounting, permutation count, bounded response | Keccak data is abstracted to identity; empty message uses a zero-byte final beat; bulk data correctness is checked by full RTL simulation |
| `thash` | BMC + cover | F/H/T_k(14 nodes)/T_len(35 nodes) | One response per request, bulk/stream backpressure, held bulk or lane payload, one final lane, byte accounting, source bounds, bounded response | SHAKE is a deterministic fair environment; req_count is encoded in bytes (224/560 for T_k/T_len) |
| `stages` | BMC + cover | WOTS/FORS/HT prefix: 128 formal steps (64 DUT cycles); XMSS: 640 steps (320 DUT cycles); top reset/restart: 80 steps (40 DUT cycles) | Hash request stability, signature/scratch address bounds, start/done pairing where reached, `start_ready` while active, top reset recovery, `valid` only with `done` | WOTS/FORS/HT full completion is not covered; top uses formal-only identity Keccak data; memory/hash responses return in one cycle; scratch depth is 256 words in `scratch_ram.sv`, not 64 |
| `uart` | BMC + cover | TX/RX clocks 4/4: 128 formal steps; 33/32 and 32/33: 768 steps each; idle glitch: 64 steps | Free-byte TX→RX equality at nominal and ±1-clock skew, no framing error, idle-high TX, one receive per transmit, false-start rejection | Covers one byte; does not prove `cmd_ctrl` frame/CRC behavior. The requested 5/4 case fails because it imposes a 20–25% bit-period mismatch; practical ±1-clock checks use 32/33 clocks (about 3.1%). |
| `cmd_ctrl` | BMC + cover | 144 formal steps (72 DUT cycles); formal key/signature lengths 1/4 B | VERIFY start follows parsed command/length/mode/context-length header and loaded key/signature; bad CRC cannot return OK; busy VERIFY returns BUSY; simultaneous completion preserves both replies | Free-byte interface bypasses UART timing and abstracts ready signals high; formal payload lengths are reduced. Host pauses while response/deferred-response channel is occupied. UART framing and practical clock-skew checks are separate. |

Each control configuration has a 64-step proof/cover bound. A transaction takes
at most 24 permutation cycles, plus the monitor's sampling cycle. The wrapper
holds reset for the first two sampled cycles, then releases it for the run.
For `IN_PLACE=1`, `state_load` is assumed low while `busy`; this follows the
allowed environment contract in the project checklist. Starts remain
unconstrained, including pulses while busy.

Run `make formal` for the CI-sized smoke, Keccak control and RPC1 round proofs,
SHAKE boundary, F/H thash, WOTS/FORS/top-reset, UART, command-controller,
and mutation targets.
`make formal-long` runs the higher-cost RPC2/RPC4, T_k/T_len, XMSS, and HT
proofs. GitHub runs the long set on a weekly schedule and on manual dispatch.
`make formal-keccak-control`, `make formal-keccak-round`, `make formal-shake256`,
`make formal-stages`, `make formal-uart`, or `make formal-cmd-ctrl` runs one group. Results and solver work directories
are written under ignored `build/formal/`.

The SHAKE wrapper offers the next message as soon as it accepts the prior
message's final word; the DUT must hold `in_ready` low until `out_valid` has
been observed. For a message of `L` bytes, `P = floor(L/136) + 1` and the
response bound is `N = ceil(L/8) + P * (24/RPC + 4) + 8` clock cycles (with one
input beat for the empty message). The terms count input beats, Keccak round
cycles, per-permutation handshake cycles and fixed controller slack. BMC depth
640 covers two back-to-back messages through 272 bytes at RPC1, plus reset;
same depth covers RPC4.

The `thash` environment returns each source byte one cycle after a read request,
stalls SHAKE input on a fixed one-in-four schedule, and returns SHAKE output two
cycles after the final accepted lane. The wrapper bounds response latency using
`3*TOTAL_LANES+24` cycles for F/H and
`3*COUNT+2*TOTAL_LANES+24` for T_k/T_len. The runner uses a conservative bound
and doubles it for the formal clock, then adds reset slack. Current SBY depths
are 128 (F), 144 (H), 1,544 (T_k), and 3,728 (T_len). These results cover the
documented fixed environment schedule; they do not quantify response latency
under every fair ready/valid schedule.

## What is not proven yet

WOTS/FORS/HT full-stage completion remains open. Mutation testing covers two
Keccak-round truth-table bugs, two Keccak-control bugs, two command-controller
bugs, two UART bugs, two SHAKE bugs, two handshake bugs each in WOTS/FORS/XMSS/HT,
and two thash bugs. UART nominal timing and both practical ±1-clock cases pass;
the original 5/4 divider request remains open because its 20–25% mismatch is
outside practical UART tolerance. SHAKE's control proof does not prove its
absorbed state or digest values; Keccak round data correctness is covered by
the separate equivalence targets.

## Mutation checks

`make formal-mutants` injects 20 bugs into isolated build copies and requires
each proof to find a counterexample. The false-start mutant uses a 128-step
bound so the erroneous receiver has time to emit a complete byte. The
production RTL is never edited by the runner.

| Target | Mutant | Expected detection |
| --- | --- | --- |
| Keccak round | LUT4 parity truth table has one wrong entry | Full-state generic/LUT4 equivalence |
| Keccak round | LUT4 chi truth table has one wrong entry | Full-state generic/LUT4 equivalence |
| Keccak control | Completion count off by one | Round counter bound or exact done latency |
| Keccak control | `done` sticks high | Single-cycle `done` assertion |
| `cmd_ctrl` | Bad CRC accepted | Bad-CRC response assertion |
| `cmd_ctrl` | Busy status dropped | Busy VERIFY response assertion |
| UART TX | Data bits sent in reverse order | TX/RX byte equality |
| UART RX | False start accepted | Idle-glitch no-byte assertion (128-step mutation bound) |
| SHAKE-256 | Input accepted during permutation | `in_ready` low during permutation assertion |
| SHAKE-256 | Response-valid sticks high | One response per message assertion |
| WOTS+ | Hash payload changes with `ready` | Valid/payload hold checker |
| WOTS+ | Hash address changes with `ready` | Valid/payload hold checker |
| FORS | Hash payload changes with `ready` | Valid/payload hold checker |
| FORS | Hash address changes with `ready` | Valid/payload hold checker |
| XMSS | Hash payload changes with `ready` | Valid/payload hold checker |
| XMSS | Hash address changes with `ready` | Valid/payload hold checker |
| HT | Forwarded WOTS payload changes with `ready` | Valid/payload hold checker |
| HT | Forwarded WOTS address changes with `ready` | Valid/payload hold checker |
| `thash` | Final marker asserted on every lane | Single final-lane and total-byte assertions |
| `thash` | `req_ready` reasserts while a response is pending | No new request accepted while outstanding |

Rerun selected entries with `python scripts/run_formal_mutants.py --only <name>`.
The runner accepts multiple names and still creates isolated build copies.
