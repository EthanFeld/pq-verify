"""Full independent-reference checks for ACVP and generated vectors."""

from pathlib import Path
import os

from model.slhdsa_ref import slh_verify, slh_verify_internal
from model.vector_corpus import load_vector_cases


ROOT = Path(__file__).resolve().parents[1]


def _load_cases(path: Path) -> list[dict]:
    cases = load_vector_cases(path)
    assert isinstance(cases, list)
    return cases


def _check_case(case: dict) -> None:
    message = bytes.fromhex(case["message"])
    signature = bytes.fromhex(case["signature"])
    public_key = bytes.fromhex(case["pk"])
    if case["mode"] == "internal":
        actual = slh_verify_internal(message, signature, public_key)
    else:
        context = bytes.fromhex(case.get("context", ""))
        actual = slh_verify(message, signature, context, public_key)
    assert actual is case["testPassed"], f"tcId {case['tcId']} disagrees with expected verdict"


def test_all_acvp_vectors_match_reference() -> None:
    cases = _load_cases(ROOT / "vectors/shake128s/sigver.json")
    assert len(cases) == 28
    for case in cases:
        _check_case(case)


def test_generated_vectors_match_reference() -> None:
    cases = _load_cases(ROOT / "vectors/shake128s/generated.json")
    assert len(cases) == 400
    limit = int(os.environ.get("PQ_VERIFY_GENERATED_LIMIT", "0"))
    if limit:
        if limit < 2 or limit > len(cases) or limit % 2:
            raise ValueError("PQ_VERIFY_GENERATED_LIMIT must be an even value from 2 through 400")
        half = limit // 2
        valid = [case for case in cases if case["testPassed"]]
        invalid = [case for case in cases if not case["testPassed"]]
        cases = valid[:half] + invalid[:half]
    for case in cases:
        _check_case(case)
