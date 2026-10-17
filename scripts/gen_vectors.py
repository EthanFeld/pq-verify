"""Generate independent SLH-DSA-SHAKE-128s vectors with OpenSSL."""

from __future__ import annotations

import argparse
import json
import random
import re
import string
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.slhdsa_ref import SHAKE128S, slh_verify  # noqa: E402
from scripts.tools import resolve_tool  # noqa: E402


PARAMETER_SET = "SLH-DSA-SHAKE-128s"
MAX_JSON_BYTES = 5_000_000
SAFE_CONTEXT = string.ascii_letters + string.digits + "_-"
SIGNATURE_PARTS = (
    "signature_R",
    "signature_FORS",
    *(f"signature_layer_{index}" for index in range(SHAKE128S.d)),
    "message",
    "context",
    "public_key",
)


def run_openssl(openssl: str, arguments: list[str]) -> bytes:
    completed = subprocess.run(
        [openssl, *arguments], check=True, capture_output=True, timeout=300
    )
    return completed.stdout


def openssl_version(openssl: str) -> str:
    text = run_openssl(openssl, ["version"]).decode("ascii", "replace").strip()
    match = re.search(r"OpenSSL\s+(\d+)\.(\d+)\.(\d+)", text)
    if not match or tuple(map(int, match.groups())) < (3, 5, 0):
        raise RuntimeError(f"OpenSSL 3.5+ required; found {text or 'unknown version'}")
    return text


def make_key(openssl: str, directory: Path) -> tuple[Path, bytes]:
    private_key = directory / "slh-dsa-key.pem"
    public_der = directory / "slh-dsa-public.der"
    run_openssl(openssl, ["genpkey", "-algorithm", PARAMETER_SET, "-out", str(private_key)])
    run_openssl(openssl, ["pkey", "-in", str(private_key), "-pubout", "-outform", "DER", "-out", str(public_der)])
    public_bytes = public_der.read_bytes()
    # SubjectPublicKeyInfo ends with a one-byte unused-bit count, then raw key.
    public_key = public_bytes[-SHAKE128S.public_key_bytes:]
    if len(public_key) != SHAKE128S.public_key_bytes:
        raise RuntimeError(f"unexpected raw public key size: {len(public_key)}")
    return private_key, public_key


def sign(
    openssl: str,
    private_key: Path,
    message: bytes,
    context: bytes,
    directory: Path,
) -> bytes:
    message_path = directory / "message.bin"
    signature_path = directory / "signature.bin"
    message_path.write_bytes(message)
    arguments = [
        "pkeyutl", "-sign", "-inkey", str(private_key), "-in", str(message_path),
        "-out", str(signature_path),
    ]
    if context:
        arguments.extend(("-pkeyopt", f"context-string:{context.decode('ascii')}"))
    run_openssl(openssl, arguments)
    signature = signature_path.read_bytes()
    if len(signature) != SHAKE128S.signature_bytes:
        raise RuntimeError(f"unexpected signature size: {len(signature)}")
    return signature


def flip_one_bit(value: bytes, rng: random.Random) -> bytes:
    if not value:
        return b"\x01"
    output = bytearray(value)
    output[rng.randrange(len(output))] ^= 1 << rng.randrange(8)
    return bytes(output)


def mutate_case(case: dict, category: str, rng: random.Random) -> dict:
    changed = dict(case)
    if category.startswith("signature_"):
        signature = bytearray.fromhex(case["signature"])
        if category == "signature_R":
            begin, end = 0, SHAKE128S.n
        elif category == "signature_FORS":
            begin, end = SHAKE128S.n, SHAKE128S.n + SHAKE128S.fors_bytes
        else:
            layer = int(category.rsplit("_", 1)[1])
            begin = SHAKE128S.n + SHAKE128S.fors_bytes + layer * SHAKE128S.xmss_bytes
            end = begin + SHAKE128S.xmss_bytes
        position = rng.randrange(begin, end)
        signature[position] ^= 1 << rng.randrange(8)
        changed["signature"] = signature.hex().upper()
    elif category == "message":
        changed["message"] = flip_one_bit(bytes.fromhex(case["message"]), rng).hex().upper()
    elif category == "context":
        changed["context"] = flip_one_bit(bytes.fromhex(case["context"]), rng).hex().upper()
    else:
        changed["pk"] = flip_one_bit(bytes.fromhex(case["pk"]), rng).hex().upper()
    changed["testPassed"] = False
    return changed


def describe_mutation(case: dict, mutant: dict, category: str) -> dict:
    for field in ("signature", "message", "context", "pk"):
        original = bytes.fromhex(case[field])
        changed = bytes.fromhex(mutant[field])
        if not original and len(changed) == 1 and changed[0] & (changed[0] - 1) == 0:
            return {"field": field, "offset": 0, "xor_mask": changed[0],
                    "append": True, "part": category}
        differences = [(offset, left ^ right)
                       for offset, (left, right) in enumerate(zip(original, changed))
                       if left != right]
        if len(differences) == 1:
            offset, mask = differences[0]
            if mask & (mask - 1) == 0:
                return {"field": field, "offset": offset, "xor_mask": mask,
                        "part": category}
    raise RuntimeError(f"mutation was not a single bit flip: {category}")


def vector_size(metadata: dict, tests: list[dict]) -> int:
    document = {"header": metadata, "tests": tests}
    return len((json.dumps(document, indent=2) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=200, help="valid signatures; matching invalid mutations are added")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--openssl", help="OpenSSL executable (or set OPENSSL)")
    parser.add_argument("--output", type=Path, default=ROOT / "vectors/shake128s/generated.json")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")

    openssl = args.openssl or resolve_tool("openssl")
    try:
        version = openssl_version(openssl)
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))

    count = args.count
    rng = random.Random(args.seed)
    valid_cases: list[dict] = []
    invalid_cases: list[dict] = []
    metadata = {
        "generator": "OpenSSL pkeyutl / genpkey",
        "version": version,
        "parameter_set": PARAMETER_SET,
        "seed": args.seed,
        "requested_valid_count": args.count,
        "valid_count": count,
        "invalid_count": count,
        "contexts": "uniform lengths 0..255; seeded printable ASCII octets for CLI compatibility",
        "keying": "new OpenSSL key every 10 signatures; OpenSSL DRBG supplies key/signing entropy",
        "invalid_encoding": "single-bit mutation deltas against valid cases; model.vector_corpus expands them",
        "mutation_parts": list(SIGNATURE_PARTS),
    }

    build_dir = ROOT / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gen_vectors_", dir=build_dir) as temporary:
        temporary_path = Path(temporary)
        key_dir = temporary_path / "key"
        key_dir.mkdir()
        private_key: Path | None = None
        public_key = b""

        for index in range(count):
            if index % 10 == 0:
                private_key, public_key = make_key(openssl, key_dir)
            message = rng.randbytes(rng.randrange(0, 1025))
            context = "".join(rng.choice(SAFE_CONTEXT) for _ in range(rng.randrange(0, 256))).encode("ascii")
            assert private_key is not None
            signature = sign(openssl, private_key, message, context, temporary_path)
            if not slh_verify(message, signature, context, public_key):
                raise RuntimeError(f"OpenSSL/reference disagreement on generated valid case {index}")
            case = {
                "tcId": 1_000_000 + index,
                "mode": "pure",
                "pk": public_key.hex().upper(),
                "message": message.hex().upper(),
                "context": context.hex().upper(),
                "signature": signature.hex().upper(),
                "testPassed": True,
            }
            valid_cases.append(case)

            category = SIGNATURE_PARTS[index % len(SIGNATURE_PARTS)]
            mutant = mutate_case(case, category, rng)
            for attempt in range(8):
                changed_message = bytes.fromhex(mutant["message"])
                changed_signature = bytes.fromhex(mutant["signature"])
                changed_context = bytes.fromhex(mutant["context"])
                changed_public_key = bytes.fromhex(mutant["pk"])
                if not slh_verify(changed_message, changed_signature, changed_context, changed_public_key):
                    break
                mutant = mutate_case(case, category, rng)
            else:
                raise RuntimeError(f"mutation remained valid: {category} case {index}")
            invalid_cases.append({
                "tcId": 2_000_000 + index,
                "base_tcId": case["tcId"],
                "mutation": describe_mutation(case, mutant, category),
                "testPassed": False,
            })
            if (index + 1) % 10 == 0 or index + 1 == count:
                print(f"Generated and reference-checked {index + 1}/{count} valid + invalid pairs", flush=True)

    tests = valid_cases + invalid_cases
    size = vector_size(metadata, tests)
    while size > MAX_JSON_BYTES and count > 1:
        count -= 1
        valid_cases.pop()
        invalid_cases.pop()
        tests = valid_cases + invalid_cases
        metadata["valid_count"] = count
        metadata["invalid_count"] = count
        size = vector_size(metadata, tests)
    if size > MAX_JSON_BYTES:
        raise RuntimeError("generated JSON exceeds the 5 MB limit")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {"header": metadata, "tests": tests}
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {count} valid + {count} invalid vectors ({size:,} bytes) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
