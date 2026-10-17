# SLH-DSA-SHAKE-128s verifier

SystemVerilog implementation of an SLH-DSA-SHAKE-128s signature verifier for
the Tang Nano 20K. The project includes a Python reference model, one shared
iterative Keccak/SHAKE datapath for H_msg and tweakable hashes, the UART
protocol and client, and build support for the open-source nextpnr flow and
Gowin vendor tools.

## Documentation

- [UART protocol](docs/protocol.md)
- [Architecture, area, and timing report](docs/report.md)
- [Current benchmark summary](docs/benchmark_report.md)
- [Validation summary](docs/validation.md)
- [Contribution guide](CONTRIBUTING.md)

## Setup

Install Python 3.10 or later, Verilator, Icarus Verilog, sv2v, Yosys,
nextpnr-himbaechel, Apicula (`gowin_pack`), and openFPGALoader. Python development
packages are listed in `requirements-dev.txt`. GNU Make provides convenience
targets; the board builder and hash regressions also run directly from Python.
The Windows scripts recognize OSS CAD Suite through `YOSYSHQ_ROOT` and local
bundles under `.tools/sv2v` and `.tools/iverilog`.

Install the Python packages with:

```sh
python -m pip install -r requirements-dev.txt
```

Fetch the filtered NIST vectors with:

```sh
python scripts/get_vectors.py
```

The checked-in filtered vectors record their source SHA in
`vectors/shake128s/source_commit.txt`. Pass that SHA to reproduce the same set;
omit the option to resolve the newest commit. The fetcher pins its raw
projection to the selected commit. If the GitHub REST API is unreachable,
it resolves the file's newest commit from GitHub's per-file Atom history feed.
For a fully manual pin, copy the full 40-character SHA from the file's History
page and pass it with `--source-commit <sha>`.

Generate reference traces (default: first 20 cases):

```sh
python model/trace.py --limit 20
```

Estimate cycles for the generated traces with:

```sh
python model/perf_model.py
```

## Build commands

The native build path works from PowerShell as well as Unix shells:

```sh
python scripts/check_tools.py
python scripts/run_round_sim.py
python scripts/run_hash_sim.py --suite all
python scripts/run_keccak_ooc_sim.py
python scripts/run_memory_sim.py
python scripts/run_layout_sim.py
python scripts/run_uart_sim.py
python scripts/run_thash_replay.py
python scripts/run_hmsg_boundaries.py
python scripts/run_wots_corner.py
python scripts/run_verify_sim.py --tc 343 464 338 --jobs 2
python scripts/run_verify_sim.py --all --jobs 4
python scripts/board_build.py bit --rpc 1 --scratch-style 0
```

The round regression compares 10,000 state/round pairs per mapping with the
Python oracle. It checks both generic logic and the explicit four-input LUT
mapping. Add `--lut4-map 1 --native-luts` to check the actual Gowin LUT model.
The hash regressions compare permutation values and exact latency with the
Python oracle, and SHAKE outputs with `hashlib`. They cover input stalls,
back-to-back messages, byte masks, block boundaries, and permutation counts.
Their default Verilator models are cached; `--simulator icarus` selects the
alternative simulator.
`make test-keccak` and `make test-shake` run the same suites.
`make test-verify-smoke` checks two valid ACVP vectors (pure and internal) and
one invalid vector through the complete verifier, including independent H_msg,
FORS, WOTS and XMSS checkpoints and the total permutation count. UART framing
and malformed-length rejection require the separate system regression.
`make test-verify` checks all 20 ACVP cases with well-formed core inputs; the
eight malformed-input cases are explicitly left to controller/system tests.
It then checks the trace cycle model against measured core cycles (2% limit).
The core regression builds one Verilator C++ model per RPC setting and reuses
it for every selected vector. `make test-memory` checks synchronous signature
RAM behavior and all three scratch-memory mappings. `make test-layout` checks
SHAKE-128s parameter offsets and compares ADRS field updates against Python
reference addresses across all five address types in a valid vector trace
(50 unique setter sequences).
`make test-uart` loops three bytes through TX and RX at both 4 and 434 clocks
per bit.
`make test-thash` replays 500 F/H calls and every T_k/T_len call from the
well-formed ACVP traces through the RTL.
`make test-hmsg` checks 14 standalone empty-message, context and SHAKE boundary
cases against the Python digest and split fields. `make test-wots` checks
checksum extremes, mixed digits, WOTS chain request boundaries, and exact
read-ahead/cache coverage for the following signature element.
`make test-robust` checks 200 unique single-bit flips across signature, public
key, message and context, then checks consecutive verifies and reset recovery.
It builds a Verilator C++ simulation and runs four batches in parallel.

Make equivalents and the Bash-based sweep commands are:

```sh
make help
make lint
make synth
make pnr
make pnr-keccak
make pnr-sweep
make pnr-scratch-sweep
make collect-pnr
make bit
```

`make pnr-keccak` maps and routes the isolated Keccak core at RPC 1, 2 and 4
using the native Python runner on Windows or Unix. It uses four-input LUTs,
nextpnr router1 for RPC1/2 and router2 for RPC3/4, checked synthesis reuse and
a 20-minute limit per tool. Override the router with `--router router1` or
`--router router2`. RPC4 optimizes placement and routing for wire length;
the other settings use timing-driven optimization. `--timing-driven` and
`--no-timing-driven` override that choice. Final static timing is reported
in every case.
RPC4 also balances LUT input pins and restores shared Theta column differences
to reduce fanout. `--no-share-theta --no-balance-lut-pins` selects the smallest
logic-only mapping for comparison.
Current source-bound routes measure 4,485 / 7,964 / 16,917 LUT4 and
132.363 / 76.051 / 23.255 MHz at RPC1/2/4. RPC4 is a legal route that misses
the requested 27 MHz; `timing_met=False` records this explicitly. RPC1 is the
board baseline; RPC2 has the lowest isolated permutation latency at Fmax.
Logs, routed netlists and source/checksum manifests go under
`build/keccak_seeded_final/`; successful rows go to `bench/keccak_measurements.csv`.
The runner promotes LUT1–3 truth tables to equivalent LUT4 cells before routing
so the backend's LUT4 timing arcs cover the entire round network.
Unused LUT inputs remain absent: the repeated truth tables make their value
irrelevant, avoiding 15,412 unnecessary pin connections at RPC4.
The wrapper XORs a 64-bit LFSR seed into the live state bank one clock before
starting each permutation. The other 24 lanes retain their state, removing
1,536 bulk-load input selectors while preserving the full permutation. The
wrapper regression checks 17 full states per RPC1/2/4 against Python, including
busy-request rejection and reset recovery. Core permutation latency remains
24/RPC; the wrapper adds one preparation clock.
Recorded runs use Yosys 0.66+228, nextpnr 0.11.1-63 and sv2v 0.0.13.
`NEXTPNR` can select a matching installed executable; the Windows runner also
recognizes the local `.tools/oss-cad-20261016/oss-cad-suite` bundle.
Use `python scripts/keccak_build.py --rpc 3` for the optional RPC3 setting.
`make pnr-sweep` builds the complete verifier at RPC 1, 2, 3, and 4; use
`make pnr RPC=2` to build one setting. `make pnr-scratch-sweep` compares the
three scratch-memory mappings at RPC 1. Select one mapping with
`make pnr SCRATCH_STYLE=1` (distributed RAM) or `2` (registers). These timing
runs have not been recorded as benchmark results automatically.
Full-design P&R targets collect their reports into `bench/measurements.csv`;
`make collect-pnr` can regenerate it after reports already exist.

Build outputs are written under `build/`. Each successful build records its
configuration and source hashes in a manifest. `make load` checks those hashes,
fit reports and the connected GW2AR-18C before writing volatile SRAM with
Gowin operation 2; it does not program SPI flash. Override the build directory
or cable when needed:

```sh
make GOWIN_BUILD_DIR=build/gowin_run GOWIN_CABLE_INDEX=4 load
```

Use `GOWIN_LOAD_ARGS=--check-only` to validate the image and scan the board
without programming. A failed rebuild removes stale outputs for that
configuration so an older image cannot be mistaken for a current bitstream.

Routing trials can reuse completed synthesis without changing the netlist:

```sh
python scripts/board_build.py bit --rpc 1 --scratch-style 0 \
  --build-dir build/route_trial --router router2 --placer-density 0.8 \
  --reuse-synthesis build/top_tn20k_rpc1_scratch0_synthesis_manifest.json
```

The reuse check requires matching RTL hashes, configuration and output checksums.
P&R applies the current constraints and records their hashes. Set `NEXTPNR` to
select another router executable; each tool uses its
own adjacent `lib` directory for runtime dependencies.

For a Gowin build with any RPC and scratch-memory style:

```sh
python scripts/gowin_build.py --rpc 2 --scratch-style 0 \
  --build-dir build/gowin_rpc2_scratch0
python scripts/gowin_build.py --rpc 2 --scratch-style 0 \
  --build-dir build/gowin_rpc2_scratch0 --inspect-existing
```

Set `GOWIN_HOME` if the installation differs from
`C:\Gowin\Gowin_V1.9.11.03_Education_x64`. `make bit-gowin` uses this path.
The wrapper checks source/image identity, resource limits, pin assignments,
clock frequencies and zero setup/hold violations. Completed images are preserved;
choose a new build directory for another run. `make test-system` exercises the
UART top in simulation; `make load` performs the separately authorized SRAM step.

`make gowin-sweep SCRATCH_STYLE=0` runs the 20-case core regression and Gowin
fit for RPC 1/2/3/4. `make gowin-scratch-sweep RPC=1` covers block,
distributed and register scratch styles. Fit rows, including SSRAM counts,
cycle and stage means go to `bench/gowin_measurements.csv`; source-matched
placement/routing failures and synthesis resources go to
`bench/gowin_failures.csv`. A failed fit does not stop the remaining
configurations from running or being collected. Matching saved failures are
skipped on later sweeps; pass `--retry-failures` to `scripts/run_gowin_sweep.py`
to retry the same route. Router and placer choices are configurable with
`GOWIN_ROUTE_OPTION` and `GOWIN_PLACE_OPTION`. If a fit fails after synthesis,
`gowin_synthesis_manifest.json` retains its checked netlist; reruns reuse it and
skip synthesis. The native Gowin sweep is the preferred
full-board route for this design because the open-source nextpnr router stalled
for tens of minutes on this netlist.

`make gowin-keccak-sweep` fits the isolated Keccak wrapper at RPC 1/2/3/4 and
collects the one-pin timing/resource measurements in
`bench/keccak_gowin_measurements.csv`.

## Area reductions

The sponge absorbs and permutes in one 1,600-bit register bank inside
`keccak_f1600`. Its `IN_PLACE` mode accepts `state_load` while idle; standalone
clients retain the start/state input interface. `state_out` exposes the live
bank and must be sampled with `done` for a completed permutation. Sharing this
bank replaces three separate 1,600-bit state banks with one.

Absorption decodes the 17 rate lanes and writes fixed 64-bit slices. Padding
uses XOR into the existing state, including messages longer than one block.
The verifier counts actual permutation starts, eliminating the 32-bit divider
previously used to estimate H_msg work.

The tweakable-hash frontend also packs request-local F/H pair data directly
from its 256-bit input register into 64-bit SHAKE lanes. WOTS chain outputs and
FORS/XMSS node pairs therefore avoid the byte-at-a-time source loop; signature
and scratch-RAM-backed T_k/T_len inputs retain their synchronous byte path.
During a WOTS chain's final F permutation, the signature RAM reads the next
chain's 16 bytes into a 128-bit buffer. The next chain consumes one cached byte
per cycle, overlapping those reads with Keccak work and saving 16 controller
cycles per eligible chain.

At RPC2–4, each Keccak round uses explicit four-input LUT cuts: column parity
uses two LUTs, theta uses one LUT per state bit, and chi combines iota in one
LUT. `PQ_GOWIN_LUT4` selects native Gowin cells during synthesis; simulation
and other targets use the same truth tables in portable SystemVerilog. RPC1
retains the board-validated generic mapping. The permutation interface and exact
24/RPC cycle count are unchanged.

RPC1 with block scratch memory maps as follows:

| Resource | Previous design | Reduced design | Reduction |
| --- | ---: | ---: | ---: |
| LUT4 | 20,703 | 14,192 | 31.45% |
| Flip-flops | 10,069 | 6,821 | 32.26% |
| BSRAM | 5 | 5 | 0% |

The reduced design uses 68.44% of LUT4 capacity and 43.86% of flip-flop
capacity, below the 85% utilization gate.

The current source-bound Gowin EDA RPC1 build in
`build/gowin_lut4_final_rpc1` uses 12,339/20,736 logic cells (59.51%),
6,786/15,552 logic FFs plus one I/O FF, 5/46 BSRAMs and 2/24 DSPs. The PLL
generates 37.125 MHz from the 27 MHz input; the board UART divisor is 322
clocks per bit. Routed core Fmax is 47.032 MHz, with 5.674 ns worst setup
slack, zero setup/hold violations and 21.1% clock margin. The packed outputs
are `pq_verify.fs` (7,264,154 bytes) and
`pq_verify.bin` (907,418 bytes). Gowin requests compression, but the generated
bitstream header says compression is off. The binary fits Gowin's 887 KiB
GW2AR-18 uncompressed configuration limit by only 870 bytes; the build check
now records this headroom and the actual compression flag. The timing exception
covers only asynchronous clear inputs of the two reset synchronizer FFs; core
data and reset-release paths remain timed.

Gowin documents `.fs` as text, `.bin` as binary, and an 887 KiB maximum
uncompressed GW2AR-18 configuration file ([UG290](https://cdn.gowinsemi.com.cn/UG290E.pdf)).
The Tang Nano 20K board has 64 Mbit of external flash ([Sipeed board specs](https://wiki.sipeed.com/hardware/en/tang/tang-nano-20k/nano-20k.html));
the FPGA configuration-size limit is tighter than that flash capacity.

The manifest binds the bitstream to the RTL, constraints and build script.
The fresh binary exactly matches the previously programmed volatile SRAM
configuration on GW2AR-18C (USB Debugger A, cable 4/channel 0), so no reflash
was needed. A fresh COM6 PING and all 28 hardware vectors pass, including valid,
invalid and malformed-length cases. All board cycle/permutation rows match
UART-top simulation exactly. Identity and regression evidence are in
`build/gowin_lut4_final_rpc1/`.

## Benchmark data

`make export-bench` gathers the RPC1 core simulation cycles and stage intervals,
then checks source hashes on the Yosys synthesis log and Gowin fit manifest. By
default, those are `build/bench_lut4_final` and `build/gowin_lut4_final_rpc1`;
pass
`--synthesis-log` and `--fit-manifest` to use another measured build. LUT4/FF
counts come from Yosys mapping; Fmax comes from the source-checked Gowin timing
report. The LUT count sums LUT1–4 cells because each uses one physical LUT4
slot. From a clean checkout, create those inputs and then build the report:

```sh
python scripts/run_verify_sim.py --all --rpc 1 --jobs 4
python scripts/board_build.py synth --rpc 1 --scratch-style 0 --build-dir build/bench_lut4_final
python scripts/gowin_build.py --build-dir build/gowin_lut4_final_rpc1
make pnr-keccak
make export-bench
make bench
```

`make bench` validates and aggregates the exported CSVs:

* `bench/measurements.csv`: `config,rpc,lut4,ff,bsram,lutram,fmax_mhz,f_run_mhz,timing_flow`
* `bench/verify_cycles.csv`: `config,tcId,mode,cycles,perms,keccak_cycles`
* `bench/stage_cycles.csv`: `config,tcId,stage,cycles`
* `bench/keccak_measurements.csv`: source-checked isolated Keccak resources,
  nextpnr Fmax and permutation latency

The benchmark command writes `bench/results.csv` and SVG plots in
`bench/plots/`. The `scope` column distinguishes complete verifier rows from
isolated Keccak rows; isolated rows leave verifier latency and throughput
blank. Their Fmax is a tool estimate, not a board clock recommendation.
The present baseline and design notes are in
[`docs/report.md`](docs/report.md); RPC and scratch-style
comparisons still need routed measurements. UART transfer time is not included
in verifier latency.

## Current status

See the [validation summary](docs/validation.md). The Python
verifier matches all 28 ACVP vectors; all 20 well-formed vectors pass core RTL,
and all 28 pass on the UART board path, including malformed lengths. Strict
lint is clean. The Gowin image uses 59.51%
logic and has 21.1% timing margin at 37.125 MHz. It is uncompressed, with 870
bytes of configuration-size headroom. The measured RPC1 baseline is in
[`docs/report.md`](docs/report.md). Source-bound nextpnr results also cover
isolated Keccak at RPC1/2/4. Higher-RPC full-verifier deployment remains future
work; the tested board baseline uses RPC1.

## License

Released under the MIT License. See [LICENSE](LICENSE).
