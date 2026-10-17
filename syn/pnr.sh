#!/usr/bin/env bash
set -euo pipefail

exec "${PYTHON:-python}" scripts/keccak_build.py --rpc 1 2 4 "$@"
