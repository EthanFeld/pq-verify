# Building and running

## Prerequisites

Install Python 3.10+, GNU Make, a C++ compiler, Verilator, Icarus Verilog,
Yosys, SymbiYosys, Boolector, sv2v, nextpnr-himbaechel, Apicula (`gowin_pack`)
and openFPGALoader. Python packages are listed in `requirements-dev.txt`.
Gowin vendor builds also require Gowin EDA.

On Windows, set `YOSYSHQ_ROOT` when the OSS CAD Suite is installed outside a
recognized bundle path. Set `VERILATOR_ROOT` if Verilator cannot report its
runtime include directory. `scripts/tools.py` resolves explicit environment
overrides, then `PATH`, then known bundles. Gowin builds accept `GOWIN_HOME`.

Install the Python requirements:

```sh
python -m pip install -r requirements-dev.txt
```

## Simulation and formal checks

```sh
make lint
make test-verify
make test-protocol
make test-robust
make formal
```

`make test-verify` runs the 20 well-formed ACVP cases at RPC1 by default. Use
`make test-verify RPC=4` to select another RPC setting. Formal targets and their
limits are listed in [verification](verification.md). Build products and
formal work directories are written under ignored `build/`.

Refresh `bench/results.csv`, plots, and the README results table with:

```sh
make bench
```

## FPGA images

Build with the open-source Yosys/nextpnr flow:

```sh
make bit
```

Build with Gowin EDA:

```sh
make bit-gowin
```

The Gowin runner validates the source hashes, constraints, fit report, and
bitstream identity. Set `GOWIN_HOME` to a different installation path. Build
outputs are stored under `build/`; use a separate `GOWIN_BUILD_DIR` for each
configuration.

## Load the board

Connect the Tang Nano 20K and check the image without programming:

```sh
GOWIN_LOAD_ARGS=--check-only make load
```

Load a verified image into volatile SRAM:

```sh
make load
```

`make load` does not program SPI flash. If the serial port is omitted,
`host/slhv.py` lists available ports; pass `--port` to select the board.
