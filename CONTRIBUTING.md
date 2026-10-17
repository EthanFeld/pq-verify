# Contributing

Thanks for helping improve the verifier. Keep changes focused and include a
regression for behavioral changes.

## Development setup

Install Python 3.10 or later, GNU Make, Verilator, and Icarus Verilog. Install
the Python packages with:

```sh
python -m pip install -r requirements-dev.txt
```

Board builds also require Yosys, sv2v, nextpnr-himbaechel, Apicula, and the
Gowin tools described in the README.

## Before opening a pull request

Run checks relevant to your change. Continuous integration runs these core
checks:

```sh
python -m pytest model/
make lint
make test-round
make test-keccak-ooc
make test-shake
make test-uart
make test-verify-smoke
make test-protocol
```

Protocol, full-verifier, hardware, and board-fit checks need additional tools or
longer runtimes. See the README for details. Do not include generated build
files, raw ACVP projections, or local simulator outputs. Keep performance
claims tied to their synthesis and timing flow.
