#!/usr/bin/env bash
set -euo pipefail

for rpc in 1 2 3 4; do
    RPC="$rpc" bash syn/board_build.sh pnr
done
