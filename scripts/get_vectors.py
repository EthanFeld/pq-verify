#!/usr/bin/env python3
"""Fetch pinned ACVP SLH-DSA vectors and filter the SHAKE-128s verifier cases."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen


REPOSITORY = "usnistgov/ACVP-Server"
SOURCE_PATH = "gen-val/json-files/SLH-DSA-sigVer-FIPS205/internalProjection.json"
PARAMETER_SET = "SLH-DSA-SHAKE-128s"
USER_AGENT = "pq-verify-vector-fetcher/1.0"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
COMMIT_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", re.IGNORECASE)


def fetch(url: str, timeout: int = 180) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_file_commit() -> str:
    api_url = (
        f"https://api.github.com/repos/{REPOSITORY}/commits"
        f"?path={SOURCE_PATH}&per_page=1"
    )
    failures: list[str] = []
    try:
        commits = json.loads(fetch(api_url, timeout=30))
        if not commits or not commits[0].get("sha"):
            raise ValueError("GitHub API returned no commit SHA")
        sha = str(commits[0]["sha"])
        if not COMMIT_RE.fullmatch(sha):
            raise ValueError(f"GitHub API returned an invalid commit SHA: {sha!r}")
        return sha
    except (OSError, TimeoutError, ValueError, TypeError, KeyError) as exc:
        failures.append(f"REST API: {exc}")

    # GitHub also publishes per-file commit history as an Atom feed. This
    # avoids api.github.com, which is blocked on some restricted networks.
    atom_url = (
        f"https://github.com/{REPOSITORY}/commits/master/{SOURCE_PATH}.atom"
    )
    try:
        feed = ET.fromstring(fetch(atom_url, timeout=30))
        entry = feed.find(f"{ATOM_NS}entry")
        if entry is None:
            raise ValueError("file-history feed has no commit entries")
        candidates = [entry.findtext(f"{ATOM_NS}id", "")]
        candidates.extend(
            link.get("href", "")
            for link in entry.findall(f"{ATOM_NS}link")
        )
        for candidate in candidates:
            match = COMMIT_RE.search(candidate)
            if match:
                return match.group(0)
        raise ValueError("file-history feed has no full commit SHA")
    except (OSError, TimeoutError, ValueError, ET.ParseError) as exc:
        failures.append(f"file-history feed: {exc}")

    raise RuntimeError(
        "Could not find the latest vector-file commit. "
        + "; ".join(failures)
        + ". Retry with --source-commit <40-character SHA> when network access is available."
    )


def filter_vectors(source: dict) -> tuple[list[dict], Counter[tuple[str, bool]]]:
    vectors: list[dict] = []
    counts: Counter[tuple[str, bool]] = Counter()
    for group in source.get("testGroups", []):
        if group.get("parameterSet") != PARAMETER_SET:
            continue

        interface = group.get("signatureInterface")
        if interface == "internal":
            mode = "internal"
        elif interface == "external" and group.get("preHash") == "pure":
            mode = "pure"
        else:
            continue

        for case in group.get("tests", []):
            required = ("tcId", "pk", "message", "signature", "testPassed")
            absent = [key for key in required if key not in case]
            if absent:
                raise ValueError(
                    f"ACVP tcId {case.get('tcId', '?')} lacks fields: "
                    + ", ".join(absent)
                )
            if not isinstance(case["testPassed"], bool):
                raise ValueError(f"ACVP tcId {case['tcId']} has non-boolean testPassed")
            vector = {
                "tcId": case["tcId"],
                "mode": mode,
                "pk": case["pk"],
                "message": case["message"],
                "context": case.get("context", ""),
                "signature": case["signature"],
                "testPassed": case["testPassed"],
            }
            vectors.append(vector)
            counts[(mode, case["testPassed"])] += 1
    return vectors, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--source-commit",
        help="use this pinned ACVP-Server commit instead of resolving the latest file commit",
    )
    args = parser.parse_args()
    root: Path = args.root.resolve()
    raw_path = root / "vectors" / "acvp" / "internalProjection.json"
    output_path = root / "vectors" / "shake128s" / "sigver.json"
    commit_path = root / "vectors" / "shake128s" / "source_commit.txt"

    try:
        sha = args.source_commit or latest_file_commit()
        if not COMMIT_RE.fullmatch(sha):
            raise ValueError("--source-commit must be a full 40-character Git commit SHA")
        raw_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/{SOURCE_PATH}"
        raw_bytes = fetch(raw_url)
        source = json.loads(raw_bytes)
        vectors, counts = filter_vectors(source)
        if not vectors:
            raise ValueError(f"No {PARAMETER_SET} internal/pure vectors found")
        for mode in ("internal", "pure"):
            if not counts[(mode, True)] or not counts[(mode, False)]:
                raise ValueError(
                    f"Filtered ACVP vectors need valid and invalid {mode} cases; "
                    f"got valid={counts[(mode, True)]}, invalid={counts[(mode, False)]}"
                )
    except (OSError, RuntimeError, ValueError, TypeError, ET.ParseError) as exc:
        parser.error(f"vector fetch/filter failed: {exc}")

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    output_path.write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")
    commit_path.write_text(sha + "\n", encoding="ascii")
    print(f"Source commit: {sha}")
    for mode in ("internal", "pure"):
        print(
            f"{mode}: valid={counts[(mode, True)]} "
            f"invalid={counts[(mode, False)]}"
        )
    print(f"Total vectors: {len(vectors)}")
    print(f"Filtered file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
