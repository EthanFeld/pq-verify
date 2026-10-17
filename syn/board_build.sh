#!/usr/bin/env bash
set -euo pipefail

exec "${PYTHON:-python}" scripts/board_build.py "${1:-}" \
    --rpc "${RPC:-1}" --scratch-style "${SCRATCH_STYLE:-0}"
