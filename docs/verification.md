# Verification

## Functional coverage

The Python reference model covers the ACVP SHAKE-128s signature-verification
vectors. The RTL core regression covers well-formed vectors at RPC1–4; the
UART-path run covers valid, invalid, and malformed requests. Current board
results are in [`hardware_results.csv`](../bench/evidence/gowin_c6_board_rpc1/hardware_results.csv)
and [`hardware_generated_results.csv`](../bench/evidence/gowin_c6_board_rpc1/hardware_generated_results.csv).

Run the local regression set with:

```sh
make lint
make test-verify
make test-protocol
make test-robust
make test-system
make formal
```

`make test-system` runs the UART top at the board's 335-cycle divisor with
Verilator's timing model. Use `--simulator icarus` for an alternate simulator;
long UART frames take much longer there.

`make test-system-full` regenerates core logs for all ACVP and generated
vectors, runs the full UART-top simulation with four simulated clocks per UART
bit, then compares verdict, cycle, and permutation counters with C6 board
results. Accelerated UART timing shortens simulator frame time; the Tang Nano
image runs UART at 115,200 baud. Per-vector comparisons are in
[`hardware_sim_parity.csv`](../bench/evidence/gowin_c6_board_rpc1/hardware_sim_parity.csv).

`make formal` runs the CI-sized proof set. `make formal-long` runs higher-cost
RPC, T_k/T_len, XMSS, and hypertree targets; the weekly
[formal workflow](../.github/workflows/formal-nightly.yml) runs that set.

## Formal scope

SymbiYosys checks reset, control, backpressure, and bounded response properties.
`formal/README.md` lists parameters, modes, depths, assumptions, and limits for
each current target. The checked targets cover Keccak permutation control,
generic/LUT4 round equivalence, SHAKE message boundaries, the tweakable-hash
request frontend, stage-controller prefixes, XMSS completion, top reset
recovery, UART transmit/receive behavior, and command-controller protocol.

Formal does not prove the complete SLH-DSA digest path. SHAKE's formal wrapper
abstracts permutation data, while separate equivalence proofs compare the round
implementations. Whole-signature data correctness remains an RTL simulation
and reference-model check.

WOTS, FORS, and hypertree proofs stop at a prefix; they do not prove full-stage
completion. A separate command-controller BMC covers free-byte framing, VERIFY
start gating, CRC rejection, busy replies, and simultaneous completion/reply
queuing. It abstracts UART timing and uses short key/signature lengths. Mutation
testing kills two Keccak-round truth-table bugs, two Keccak-control bugs, two
command-controller bugs, two UART bugs, two SHAKE bugs, two handshake bugs
each in WOTS/FORS/XMSS/HT, and two thash bugs. UART round trips pass at the
nominal divider and at 32/33 clocks in both directions (about 3.1% skew). The
requested 5/4 case remains open: a 20–25% bit-period mismatch exceeds practical
UART tolerance and produces a counterexample.
Passing the current formal targets must not be read as a proof of those
unimplemented properties.

The independent OpenSSL-generated corpus contains 200 valid signatures and 200
one-bit invalid mutations. Invalid cases store a compact field/offset/mask delta
against their valid base case; `model.vector_corpus` expands them for reference
and RTL checks. This keeps the JSON below 5 MB without reducing coverage.
`scripts/gen_vectors.py` checks each case against the Python verifier before
writing the corpus; `make test-verify-ext` exercises it in RTL and the cycle
model.

## Reproduction and limitations

Install tools from [building](building.md). Build and solver outputs go under
ignored `build/`; rerun the commands above to reproduce them. Source-matched
measurement records use manifests under [`bench/evidence/`](../bench/evidence/)
and are checked by `make check-evidence`.
