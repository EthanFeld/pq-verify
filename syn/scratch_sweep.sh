#!/usr/bin/env bash
set -euo pipefail

for scratch_style in 0 1 2; do
    SCRATCH_STYLE="$scratch_style" RPC="${RPC:-1}" bash syn/board_build.sh pnr
done
