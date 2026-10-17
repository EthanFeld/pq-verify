#!/usr/bin/env python3
"""Check that checked-in benchmark evidence matches its measured source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "bench/evidence"
ACTIVE_EVIDENCE = EVIDENCE / "gowin_c6_board_rpc1"
MAX_FILE_BYTES = 200_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_manifest(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError(f"{path.relative_to(ROOT)}: missing source hashes")
    status = data.get("status", "current")
    snapshot_dir = data.get("source_snapshot_dir")
    if status == "snapshot":
        if not isinstance(snapshot_dir, str) or not snapshot_dir:
            raise ValueError(f"{path.relative_to(ROOT)}: snapshot evidence needs source_snapshot_dir")
    elif status != "current":
        raise ValueError(f"{path.relative_to(ROOT)}: status must be current or snapshot")

    errors: list[str] = []
    for name, expected in sources.items():
        if not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 64 or any(
            char not in "0123456789abcdef" for char in expected
        ):
            errors.append(f"{path.relative_to(ROOT)}: invalid source hash entry {name!r}")
            continue
        try:
            if status == "snapshot":
                snapshot_root = (path.parent / snapshot_dir).resolve()
                source_path = (snapshot_root / name).resolve()
                if not source_path.is_relative_to(snapshot_root):
                    raise ValueError(f"snapshot source path escapes snapshot directory: {name}")
                actual_data = source_path.read_bytes()
            else:
                actual_data = (ROOT / name).read_bytes()
        except (OSError, ValueError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        if sha256(actual_data) != expected:
            errors.append(f"{path.relative_to(ROOT)}: source hash mismatch for {name}")
    return errors


def main() -> int:
    if not EVIDENCE.is_dir():
        print(f"missing evidence directory: {EVIDENCE.relative_to(ROOT)}", file=sys.stderr)
        return 1
    files = sorted(path for path in ACTIVE_EVIDENCE.rglob("*") if path.is_file())
    oversized = [f"{path.relative_to(ROOT)}: {path.stat().st_size} bytes exceeds {MAX_FILE_BYTES}"
                 for path in files if path.stat().st_size > MAX_FILE_BYTES]
    manifests = [ACTIVE_EVIDENCE / "manifest.json"]
    if not manifests:
        print("no evidence manifests found", file=sys.stderr)
        return 1
    errors = oversized
    for path in manifests:
        try:
            errors.extend(check_manifest(path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS evidence: {len(manifests)} manifests, {len(files)} files, all source hashes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
