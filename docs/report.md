# SLH-DSA-SHAKE-128s verifier report

## Design

The verifier processes H_msg, FORS, and the seven-layer hypertree in sequence.
Each stage has its own controller FSM; H_msg and tweakable hashing share one
iterative SHAKE-256 engine. The Keccak round unit reuses one 1,600-bit state
bank. Signature bytes come from synchronous RAM; intermediate nodes and tree
roots use scratch RAM.

The core run starts with four signature words for R, streams context/message
bytes into H_msg, then verifies FORS and the hypertree before comparing the
recovered root with PK.root. The UART controller stages the public key and
signature, and streams the message into the core while receiving the VERIFY
request.

The current tweakable-hash frontend packs request-local F/H node pairs directly
from its 256-bit register into 64-bit SHAKE lanes. This removes byte-at-a-time
FEED/READ_SOURCE work for WOTS chains and FORS/XMSS node pairs; memory-backed
T_k and T_len inputs keep their synchronous read path.

WOTS overlaps another memory operation with Keccak work: on a chain's final F
permutation it reads the following chain's 16 signature bytes into a 128-bit
buffer. The next chain consumes one cached byte per cycle instead of issuing a
RAM request and waiting for each byte. This removes 16 controller cycles per
prefetched chain without changing the hash sequence or RAM contents.

## Sharing and resource tradeoffs

Sharing the Keccak state and SHAKE engine cuts duplicated state storage and
hash logic. The shared design serializes H_msg and all F/H/T_k/T_len operations;
its area benefit costs verify throughput. RPC1 performs one Keccak round per
cycle and has the only complete full-verifier RPC board results so far; its
block and distributed scratch variants both fit.

The signature and scratch memories map to five block RAMs in the baseline
candidate. Gowin uses `syn_ramstyle` constraints to select block RAM, SSRAM, or
register storage for scratch; the [Gowin Synthesis User Guide (SUG550)](https://cdn.gowinsemi.com.cn/SUG550E.pdf)
documents `block_ram`, `distributed_ram`, and `registers` as the supported
values. WOTS chain ends are written to scratch before T_len reads them,
preserving the synchronous read/write behavior in each style.

## Scratch-memory fit comparison (previous source version)

These rows use the source before inline-pair lane packing. All use RPC1, the
same pins, 37.125 MHz core clock, and Gowin's default placer/router. Each
successful row is source-matched and has its own 20-vector core simulation and
stage/cycle logs. The register row reports synthesis resources; placement
failed before a fit report was available. The updated source has only been
re-fit with block scratch so far.

| Scratch style | Logic cells | FF | BSRAM | SSRAM (RAM16) | Fmax | Mean cycles | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Block (0) | 11,942 | 6,639 | 5 | 0 | 52.479 MHz | 201,513.75 | Fit |
| Distributed (1) | 12,752 | 6,671 | 4 | 128 | 54.971 MHz | 201,513.75 | Fit |
| Registers (2) | 15,845 synthesized LUTs | 14,864 | 4 | 0 | — | 201,513.75 | Placement failed: 3,411 registers unplaced |

Distributed scratch saves one BSRAM at the cost of 810 logic cells and 32 FF;
its routed Fmax is 2.492 MHz higher. Both fitted bitstreams are 907,418 bytes.
Register mapping consumes 95.6% of the available logic FF before placement and
does not fit this device. The complete fit rows are in
`bench/gowin_measurements.csv`; the failed configuration and synthesis counts
are in `bench/gowin_failures.csv`.

## Full-verifier RPC sweep (previous source version)

Each row below passed all 20 core vectors before inline-pair lane packing.
Fitter results use block scratch, the same board constraints, and Gowin's
default placer/router. The updated source passes all 20 core vectors at RPC1–4;
its current mean cycle counts are listed in the baseline section below. Only
RPC1 has a new source-matched board fit.

| RPC | Mean core cycles | Logic cells / 20,736 | FF / 15,552 | BSRAM | Board result |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 201,513.75 | 11,942 (58%) | 6,639 (43%) | 5 | Fit, 52.479 MHz |
| 2 | 175,536.35 | 16,271 (79%) | 6,638 (43%) | 5 | Router failed: DesRoute failure, 0 unrouted nets |
| 3 | 166,896.55 | 20,152 (98%) | 6,639 (43%) | 5 | Router failed: DesRoute failure, 0 unrouted nets |
| 4 | 162,576.65 | 23,721 synthesized logic units, over the 20,736 limit | — | — | Synthesis stopped: resource limit |

RPC4 cuts mean simulated core cycles by 19.3% versus RPC1, but requires
2,985 more logic units than the device provides. RPC2 and RPC3 fit placement;
the vendor router did not complete. Full build times, synthesized counts and
failure messages are retained in `bench/gowin_failures.csv`.

## Current measured baseline

The table below is generated from `bench/results.csv`. LUT4 and FF counts come
from current Yosys mapping; the Fmax field comes from the source-checked Gowin
fit. The core runs at the configured frequency shown in the same row.

| Configuration | LUT4 | FF | BSRAM | Fmax | Run clock | Mean cycles | Mean latency | Mean throughput | Keccak busy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rpc1_scratch0 | 14,384 | 6,970 | 5 | 47.032 MHz | 37.125 MHz | 127,234.85 | 3,427.20 µs | 291.78 verifies/s | 41.29% |

LUT counts are physical LUT4 slots: LUT1–4 cell counts are summed. The current
Yosys run contains 624 LUT1, 1,472 LUT2, 2,485 LUT3 and 9,803 LUT4 cells.
Earlier reports counted only the LUT4-named cells and understated physical
area. Gowin's 12,339 logic-cell result is from a separate synthesis flow.

The source-matched Gowin fit uses 12,339/20,736 logic cells, 6,786 logic FF,
five BSRAMs, and reaches 47.032 MHz with zero timing violations and 5.674 ns
worst setup slack. The image is 907,418 bytes with 870 bytes of uncompressed
configuration headroom. H_msg averages 4,037.5 cycles, FORS 15,512, and
hypertree 107,677.35; the remaining eight cycles load R. This exact ledger is
asserted for all 80 core runs across RPC1–4. The trace model's maximum error is
0.94% or less. WOTS read-ahead saves 3,546.4 mean cycles (2.71%) over the
previous inline-pair source at RPC1. Vector-level data and plots are in `bench/`
and are regenerated by the documented benchmark flow.

The fresh current-source Gowin build is `build/gowin_lut4_final_rpc1/`.
Its binary configuration SHA256 is
`d8357dba3b8f6f5f377aa14fa8962fa5cdd1f6debb6946765a3618792834d9e3`,
identical to the previously programmed RPC1 image. No reflash was needed.
A standalone PING and a fresh 28-vector hardware regression pass; all counters
match the UART-top simulation. `hardware_identity.json` and
`hardware_comparison.json` record the connection to the prior SRAM program.

## Tradeoffs and open measurements

The current RPC1 block-scratch image meets the candidate clock and has 21.1%
clock margin. The previous scratch comparison showed distributed RAM fits and
is slightly faster, while register mapping does not place. Previous RPC2/3
full-board routes and RPC4 resource results predate the current source and need
fresh higher-RPC retries. Current isolated nextpnr results are listed below;
older Gowin OOC trials are retained as routing history.

## Compact Keccak mapping

Higher-RPC implementations use explicit four-input LUT truth tables instead
of allowing the mapper to build large wide-LUT mux clusters. Column parity
uses XOR4 followed by XOR2; theta combines the state bit and two column
parities in one LUT; chi includes the round-constant bit in the same LUT.
Rho and pi remain wiring. RPC1 retains the board-validated generic logic.
The `LUT4_MAP` parameter can select either implementation.

With the current lane-seeded wrapper and the same Yosys
`synth_gowin -family gw2a -nowidelut` flow, generic RPC4 maps to 17,778 LUTs
and compact RPC4 to 15,573: 2,205 fewer LUTs, a 12.4% reduction, with the same
1,672 FF. This comparison selects `LUT4_MAP=0` or `1` for the same function;
inputs and output hashes are recorded in
`build/keccak_seeded_final/logic_comparison.json`. Counts sum LUT1–4 cells;
routed counts also include fitter-inserted cells.

The previous full-load wrapper measured 19,915 generic LUTs and 17,106 compact
LUTs. Combining compact round logic with the lane-seeded wrapper cuts the
complete OOC design from 19,915 to 15,573 mapped LUTs (21.8%). The initial
comparison log is `build/keccak_mapcompare/rpc4_lut4_abc9.log`; current
manifests are under `build/keccak_seeded_final/`.

For RPC4, the routing transform restores 1,280 shared Theta column
differences. This adds 1,280 LUTs but removes 3,840 input connections and
reduces each column-parity fanout from ten to two. Implementation area is
16,853 LUTs before fitter additions, versus 17,778 for the generic seeded
design (5.2% less) and 19,915 for the original generic wrapper (15.4% less).
Deterministic LUT input rotations balance demand across the four physical
input pins. Exhaustive local truth-table and actual-connection checks cover
197,968 combinations; all 1,672 state/control FF connections are preserved.

Timing requires one additional normalization: the upstream
[Gowin timing database generator](https://github.com/YosysHQ/nextpnr/blob/main/himbaechel/uarch/gowin/gowin_arch_gen.py)
defines combinational arcs for LUT4, while mapped netlists also contain
LUT1–3 cells. Leaving those smaller types in the netlist cuts timing paths;
an initial RPC2 result of 903 MHz was therefore rejected. The runner repeats
each smaller truth table to 16 entries and routes equivalent LUT4 cells.
Unused input ports stay absent; the repeated table is independent of their
value. Omitting them removes 15,412 unnecessary pin connections at RPC4 and
avoids the routing congestion seen with ground-tied padding. Physical LUT
counts are unchanged, and complete round
paths now participate in timing. Manifests and benchmark imports require the
normalization marker; earlier incomplete reports are excluded.

Generic and compact rounds each pass 10,000 oracle comparisons; another
10,000 comparisons exercise the compact round with Yosys's actual Gowin LUT
simulation model. The hash suite passes 8,016 complete permutation checks
across RPC1–4 and both state-loading modes, plus 77 SHAKE/hashlib cases at each
RPC. All 80 full-verifier cases pass with unchanged cycle/permutation counts
and exact stage ledgers. Strict lint passes both the board baseline and the
RPC4 permutation engine.
The timing normalization also passes all 4,416 input combinations across the
276 possible one-, two- and three-input truth tables.

## Isolated Keccak fit

The previous LFSR-driven full-load wrapper exposes the SHAKE digest prefix through one
reduced output pin, avoiding a 1,600-bit output parity tree. Its source-checked
RPC1 Gowin fit uses 5,242 logic cells and 1,671 FF, reaches 85.814 MHz from a
27 MHz input clock, and has zero setup/hold violations. RPC2 and RPC3 route
trials have not produced fit reports. RPC4 synthesis completed, but route
options 0/1/2 stalled at 70%; placer-option 1 retries for RPC3 and RPC4
stalled during placement. The RPC4 source-checked synthesis manifest is
retained for future retries.
Successful rows are collected in `bench/keccak_gowin_measurements.csv`.

The current wrapper uses the same in-place state interface as the shared
SHAKE engine. An accepted request XORs one LFSR word into lane zero, then
starts the permutation on the following clock. The other 24 lanes retain
their previous state. This removes 1,536 bulk-load selectors and avoids
repeating the LFSR fanout across all lanes. Every 1,600-bit round/state path
remains present. The full-state oracle regression passes 17 states at each
RPC1/2/4, including busy-request rejection, reset recovery and the exact
24/RPC + 1 wrapper latency. Reported permutation latency excludes that one
preparation clock.

Current source-bound nextpnr results (complete LUT4 timing arcs):

| RPC | Routed LUT4 | FF | Fmax | Core cycles | Core latency at Fmax | Meets 27 MHz |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 4,485 | 1,673 | 132.363 MHz | 24 | 0.18132 us | Yes |
| 2 | 7,964 | 1,673 | 76.051 MHz | 12 | 0.15779 us | Yes |
| 4 | 16,917 | 1,672 | 23.255 MHz | 6 | 0.25801 us | No |

RPC2 reduces isolated permutation latency by 13.0% at each implementation's
measured maximum frequency, at the cost of 77.6% more routed LUTs. These
figures describe the isolated permutation; they do not change the board clock
or claim a full-verifier speedup. RPC1 remains the board baseline because it
has the smallest area and a complete source-matched hardware regression.
RPC4 fits the device and has complete register-to-register timing, but misses
the 27 MHz request. Its six-cycle latency does not compensate for its lower
Fmax; it is slower than RPC1/2 at each implementation's maximum frequency.
The CSV retains `clock_constraint_mhz=27` and `timing_met=False`, so a legal
route cannot be mistaken for timing closure. RPC4 was not programmed onto
the board. `bench/results.csv` contains all three OOC rows.

## Fit runtime and reproducibility

The full-design nextpnr log reached 222,000 router iterations and about 32
minutes before the run was stopped without a fit. Repeating P&R also reran
Yosys, so `scripts/board_build.py` now reuses synthesis only after checking the
RPC/style, RTL hashes and both synthesis-output checksums. The Gowin runner
supports placement and routing choices, writes per-stage durations, and keeps a
source/config/checksum-bound `.vg` manifest after synthesis so another route
attempt starts from the same netlist. This avoids repeating synthesis when a
route choice needs to change. `scripts/collect_gowin.py` correlates current fit
manifests with all 20 passing core vectors and their stage counters; its CSV
remains separate from the Yosys-mapped baseline because the resource counters
come from different synthesis flows.

`scripts/verilator_build.py` also caches the compiled C++ timing model when
source hashes, top parameters, tool versions and the binary checksum match, so
repeated vector sweeps skip model generation and compilation.
The round and hash runners now use the same cache. Icarus remains available
for hash checks through `--simulator icarus`.

The isolated nextpnr runner uses `-nowidelut`, router1 for RPC1/2 and router2
for RPC3/4. RPC4 uses shared Theta nodes, balanced LUT pins and wire-length
optimization for placement/routing; final static timing remains enabled.
This combination finishes RPC4 in 123.1 seconds, while earlier timing-driven
attempts stalled beyond their tool timeouts. A second placement seed also
routes successfully (16,917 LUT4, 22.798 MHz), corroborating routability.
The runner records tool versions
and commands, preserves checked synthesis for retries, and exports only
completed source-matched routes. `make pnr-keccak` runs RPC1/2/4. Completed
routes are checksum-checked and reused; changing source or route settings
requires a fresh build directory. Its per-tool timeout is 20 minutes.
The benchmark aggregator checks each route manifest before adding a
`scope=keccak_ooc` row. Verifier cycle/latency fields stay empty in these rows;
only permutation cycles and estimated latency at the reported Fmax are filled.

## ASIC notes

The functional datapath is portable SystemVerilog, but BSRAM inference, Gowin
PLL generation, I/O pin constraints, and UART baud divisors are FPGA-specific.
An ASIC flow should replace the two inferred memories with characterized SRAM
macros, replace the PLL and pin-level UART wrapper with the SoC clock and
interface, and close timing against the target process libraries. The iterative
round engine and shared state remain synthesizable; area, timing and power need
fresh standard-cell reports rather than FPGA LUT counts.
