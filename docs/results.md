# Board results

## Tang Nano 20K

The validated image targets the Gowin GW2AR-18C and runs the verifier at 38.571 MHz. Gowin fit reports 14,504 of 20,736 logic cells, 6,718 of 15,552 flip-flops, five block RAMs, and two DSP blocks.

| Measurement | Result |
| --- | ---: |
| Core clock | 38.571 MHz |
| Fmax | 43.212 MHz |
| Timing margin | 10.74% |
| Worst setup slack | 2.784 ns |
| Setup / hold violations | 0 / 0 |
| Bitstream size | 907,418 bytes |
| Bitstream SHA-256 | `07b4830a989a5220e681666a5c10f9ea8fea7ac54981d5aa3caa3966785256a7` |

## Hardware verification

The image passes 28/28 ACVP vectors and 400/400 generated vectors over UART at 115200 baud. The 400 generated vectors include 200 valid and 200 invalid signatures. Hardware verdicts, cycle counts, and permutation counts match UART-top simulation exactly across all 428 cases.

The generated set averages 66,091.09 core cycles, or 1.713 ms estimated at the configured clock. This latency is calculated from device-reported cycles; it is not host-to-result wall-clock time. A live valid-signature UART capture is in [hardware_demo.txt](../bench/evidence/gowin_c6_board_rpc1/hardware_demo.txt). Per-vector results and source-matched fit data are in the [board evidence directory](../bench/evidence/gowin_c6_board_rpc1/).

The image was loaded into volatile SRAM. SPI flash was not programmed.
