# Current benchmark

Current candidate: `rpc1_scratch0`, the source-bound Tang Nano 20K image with
packed inline F/H tails and WOTS signature read-ahead. Cycle results cover all
20 well-formed ACVP vectors.
Resource counts come from Yosys; Fmax comes from the matching Gowin fit
manifest. CSVs and plots are generated with `scripts/export_bench_inputs.py`
and `scripts/build_bench.py`.

| Measure | Result |
| --- | ---: |
| Physical LUT4 slots (Yosys LUT1–4 sum) | 14,384 |
| FF (Yosys mapped) | 6,970 |
| BSRAM | 5 |
| Gowin logic cells | 12,339 / 20,736 (59.51%) |
| Routed Fmax | 47.032 MHz |
| Run clock | 37.125 MHz |
| Verify cycles, min / mean / max | 118,719 / 127,234.85 / 139,607 |
| Mean verify latency | 3,427.20 µs |
| Mean throughput | 291.78 verifies/s |
| Mean Keccak permutations | 2,188.95 |
| Keccak busy fraction | 41.29% |

Mean stage intervals are 4,037.5 H_msg cycles, 15,512 FORS cycles and
107,677.35 hypertree cycles. They sum to the measured total minus eight
top-level R-load cycles. The testbench asserts this exact ledger on all 80
RPC1–4 core runs. The trace predictor stays within 0.94%, 0.90%, 0.86%, and
0.84% at RPC1–4 respectively (2% limit).

The inline F/H tail lane pack removes per-byte FEED/READ_SOURCE cycles for
request-local node pairs. WOTS also reads the next chain's signature during
the current chain's final permutation, then consumes the cached 16 bytes in
16 cycles instead of 32. This saves 3,546.4 mean cycles (2.71%) over the
previous inline-pair source at RPC1. The current image is 907,418 bytes with
870 bytes of uncompressed configuration headroom, zero timing violations,
5.674 ns setup slack, and 21.1% clock margin. It was programmed to volatile
SRAM and passed all 28 hardware vectors on COM6 at 115200 baud. The fresh
current-source binary is byte-identical to that SRAM payload, so it was checked
again without reflashing; all 28 vectors pass. Current fit, binary identity and
regression evidence are under `build/gowin_lut4_final_rpc1/`; the original
programmer report remains under `build/gowin_wotsprefetch_rpc1/`.

## Current isolated Keccak comparison

These source-bound nextpnr measurements use the same lane-seeded wrapper
and complete LUT4 timing arcs. Every 1,600-bit permutation path is retained.

| RPC | Routed LUT4 | FF | Fmax | Permutation cycles | Latency at Fmax | Meets 27 MHz |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 4,485 | 1,673 | 132.363 MHz | 24 | 0.18132 us | Yes |
| 2 | 7,964 | 1,673 | 76.051 MHz | 12 | 0.15779 us | Yes |
| 4 | 16,917 | 1,672 | 23.255 MHz | 6 | 0.25801 us | No |

RPC2 reduces isolated latency by 13.0% versus RPC1 at their measured Fmax.
RPC4 is legally routed but slower at Fmax and misses the requested 27 MHz;
the CSV marks `timing_met=False`. The wrapper adds one seed-preparation clock
to each request, excluded from the core permutation latency above.

RPC4's compact round mapping uses 15,573 LUTs before the routing transform,
versus 17,778 for generic rounds with the same wrapper (12.4% less). Shared
Theta nodes add 1,280 LUTs to cut routing demand; final implementation area
before fitter additions is 16,853 LUTs, 15.4% below the original 19,915-LUT
generic full-load design. All 51 wrapper oracle cases and 197,968 local
mapping-equivalence combinations pass.

RPC1 remains the baseline: smallest area, timing margin and complete
full-verifier hardware validation. OOC rows in `bench/results.csv` have
`scope=keccak_ooc` and leave verifier latency/throughput empty. Source hashes,
the timing model profile and output checksums are validated during collection.

## Previous source-version comparisons

These fit results were collected before the inline F/H tail optimization.
They remain useful as measured scratch and routing history; the updated RTL
has only been fit with block scratch at RPC1 so far.

| Scratch style | Logic cells | FF | BSRAM | SSRAM (RAM16) | Fmax | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Block (0) | 11,942 | 6,639 | 5 | 0 | 52.479 MHz | Fit |
| Distributed (1) | 12,752 | 6,671 | 4 | 128 | 54.971 MHz | Fit |
| Registers (2) | 15,845 synthesized LUTs | 14,864 | 4 | 0 | — | Failed placement: 3,411 registers unplaced |

The previous distributed-scratch fit saved one BSRAM at the cost of 810 logic
cells and 32 FF. Register mapping used 95.6% of available logic FF and did not
place. Full source-matched records are in `bench/gowin_measurements.csv` and
`bench/gowin_failures.csv`.

The current source passes all 20 core vectors at RPC1–4; the updated mean cycle
counts, including WOTS prefetch, are:

| RPC | Mean cycles |
| ---: | ---: |
| 1 | 127,234.85 |
| 2 | 101,257.45 |
| 3 | 92,617.65 |
| 4 | 88,297.75 |

Older full-board fits were measured on the previous source: RPC2 and RPC3
reached placement but Gowin routing failed with zero unrouted nets, while RPC4
exceeded the device synthesis limit. The new RTL needs current-source retries
at RPC2–4 before those fit outcomes can be reused as current candidate results.

Generated CSV inputs and SVG plots are ignored build products under `bench/`.
