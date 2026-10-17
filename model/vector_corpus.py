"""Load verifier vectors, expanding compact one-bit mutation records."""

from __future__ import annotations

import json
from pathlib import Path


def load_vector_cases(path: Path) -> list[dict]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    records = loaded["tests"] if isinstance(loaded, dict) else loaded
    if not isinstance(records, list):
        raise ValueError("vector file must contain a list or a header/tests document")

    cases: list[dict] = []
    by_id: dict[int, dict] = {}
    for record in records:
        case = dict(record)
        if "mutation" in case:
            base_id = int(case.pop("base_tcId"))
            mutation = case.pop("mutation")
            base = by_id.get(base_id)
            if base is None or base["testPassed"] is not True:
                raise ValueError(f"mutation tcId {case.get('tcId')} has no earlier valid base {base_id}")
            field = mutation.get("field")
            if field not in {"signature", "message", "context", "pk"}:
                raise ValueError(f"mutation tcId {case.get('tcId')} has invalid field {field!r}")
            value = bytearray.fromhex(base[field])
            offset = int(mutation["offset"])
            mask = int(mutation["xor_mask"])
            append = bool(mutation.get("append", False))
            if (not 1 <= mask <= 255 or mask & (mask - 1)
                    or (append and (value or offset != 0))
                    or (not append and not 0 <= offset < len(value))):
                raise ValueError(f"mutation tcId {case.get('tcId')} is not a single in-range bit flip")
            if append:
                value.append(mask)
            else:
                value[offset] ^= mask
            expanded = dict(base)
            expanded[field] = value.hex().upper()
            expanded["tcId"] = int(case["tcId"])
            expanded["testPassed"] = False
            case = expanded
        else:
            case["tcId"] = int(case["tcId"])
        if case["tcId"] in by_id:
            raise ValueError(f"duplicate vector tcId {case['tcId']}")
        by_id[case["tcId"]] = case
        cases.append(case)
    return cases
