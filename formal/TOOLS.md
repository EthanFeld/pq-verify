# Formal toolchain

Required tools:

- SymbiYosys (`sby`)
- Yosys and `yosys-smtbmc`
- Boolector (default solver), or another solver supported by SBY

Use a matching OSS CAD Suite / YosysHQ release so SBY, Yosys, and the SMT
solver are mutually compatible. The project resolver expects these tools on
`PATH`; set `YOSYSHQ_ROOT` when they are installed in a bundle directory.

Versions observed on the development machine for this target:

- SBY: `v0.66-23-g6e3dc04`
- Yosys: `0.66+228` (git `95b5e4360`)
- Boolector: `3.2.4`

GitHub Actions installs the matching OSS CAD Suite with
`YosysHQ/setup-oss-cad-suite@v4` and prints the resolved SBY, Yosys, and
Boolector versions before running `make formal`. The action selects its latest
release unless its `version` input is set.
