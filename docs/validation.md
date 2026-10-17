# Validation

Results below describe measured software, RTL, and hardware checks. Isolated
Keccak measurements are out-of-context timing results; they do not predict
full-verifier performance at the board clock.

## Functional checks

| Scope | Coverage | Result |
| --- | --- | --- |
| Python reference | 28 NIST ACVP SHAKE-128s cases | All verdicts match |
| Core RTL | 20 well-formed cases at RPC1/2/3/4 | 80 runs pass checkpoints and cycle accounting |
| UART board path | 28 valid, invalid, and malformed-input cases | All pass; counters match UART-top simulation |
| Keccak and SHAKE | Round oracle, permutation, and 77 SHAKE/hashlib cases per RPC | All pass |
| Isolated timing wrapper | 17 full-state oracle cases at RPC1/2/4 | All 51 pass, including reset and busy handling |
| RPC4 map transform | 1,280 shared Theta terms and unchanged state/control registers | 197,968 equivalence checks pass |

## Isolated Keccak area and timing

All routes use the GW2AR-18C database, a 27 MHz input constraint, and complete
LUT4 timing arcs. RPC4 uses wire-length-driven placement and routing, then
reports static timing on its legal route. “Latency” below is core permutation
cycles divided by the measured Fmax; it excludes the wrapper's one seed setup
clock.

| RPC | Routed LUT4 | FF | Fmax | Core cycles | Latency at Fmax | Meets 27 MHz |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 4,485 | 1,673 | 132.363 MHz | 24 | 0.18132 us | Yes |
| 2 | 7,964 | 1,673 | 76.051 MHz | 12 | 0.15779 us | Yes |
| 4 | 16,917 | 1,672 | 23.255 MHz | 6 | 0.25801 us | No |

RPC2 improves isolated permutation latency by 13.0% versus RPC1 at measured
Fmax, with 77.6% more LUTs. RPC4 is routed but misses 27 MHz and is slower at
its measured Fmax. The benchmark export marks this constraint miss explicitly.
RPC1 remains the board baseline: smallest area, timing margin, and current
full-verifier hardware evidence.

The compact RPC4 round mapping reduces the seeded wrapper from 17,778 to
15,573 mapped LUTs (12.4%). Shared Theta terms raise the pre-fit count to
16,853 while reducing routing fanout; the original generic full-load wrapper
used 19,915 mapped LUTs. Counts here are from the same Yosys mapping flow and
sum LUT1–4 cells. Fitted LUT counts include cells inserted during routing.

## Reproduce

Install the tools described in the README, then run the software and RTL
checks:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest model/
make lint
make test-round
make test-keccak-ooc
make test-shake
make test-uart
make test-verify-smoke
make test-protocol
```

The nextpnr comparison is collected with `make pnr-keccak`; this requires
Yosys, sv2v, and nextpnr-himbaechel. `make bench` combines full-verifier rows
with source-checked OOC results. Build files and generated CSVs are ignored;
measurement summaries and flow details are in
[`benchmark_report.md`](benchmark_report.md) and [`report.md`](report.md).

The Tang Nano 20K RPC1 image is the only full-verifier build reported here.
It runs at 37.125 MHz, reaches 47.032 MHz Fmax, and passed all 28 board vectors.
Higher-RPC OOC results describe the Keccak core only; they do not establish a
higher-RPC full-verifier fit or board-level speedup.
