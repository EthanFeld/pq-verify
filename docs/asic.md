# ASIC considerations

The current RTL targets a Gowin FPGA and uses board-specific PLL, UART, RAM,
and pin constraints. An ASIC implementation would need SRAM macros and wrappers
for the FPGA's clock and IO resources. The SLH-DSA stage controllers and shared
hash datapath can remain the starting point, but macro timing and the synthesis
library will change area and critical paths.

The shared Keccak unit reduces area by serializing H_msg and tweakable hashes.
An ASIC has different area and wire-delay tradeoffs; higher round parallelism
or parallel chain units may improve latency, at additional area and routing
cost. Measure those choices with a real standard-cell flow before making claims.

Published estimates from SLotH and a SHA-2+ SPHINCS+ co-design appear in the
[ASIC comparison](results.md#published-asic-estimate). Both are synthesis or
hardware/software co-design results, not tapeouts.
