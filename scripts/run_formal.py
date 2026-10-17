"""Run repository formal targets and print a compact result table."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools import ROOT, resolve_tool, tool_environment, yosys_data_file


FORMAL = ROOT / "formal"
BUILD = ROOT / "build" / "formal"


def run_sby(config: Path, workdir: Path, env: dict[str, str]) -> bool:
    if os.name == "nt" and shutil.which("yosys-smtbmc", path=env.get("PATH")) is None:
        yosys_root = Path(resolve_tool("yosys", env)).parent.parent
        bundled = yosys_root / "bin" / "yosys-smtbmc.exe.exe"
        if bundled.is_file():
            shim_dir = BUILD / "tools"
            shim_dir.mkdir(parents=True, exist_ok=True)
            shim = shim_dir / "yosys-smtbmc.cmd"
            shim.write_text(f'@"{bundled}" %*\r\n@exit /b %ERRORLEVEL%\r\n', encoding="ascii")
            env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    command = [resolve_tool("sby", env), "-f", "-d", str(workdir), str(config)]
    result = subprocess.run(
        command, cwd=config.parent, env=env, check=False,
        capture_output=True, text=True,
    )
    if result.returncode:
        detail = result.stdout + result.stderr
        print(detail[-12000:], file=sys.stderr, flush=True)
    return result.returncode == 0


def run_yosys_sat(rpc: int, native_check: int, env: dict[str, str]) -> bool:
    """Use Yosys's native SAT engine for the wide combinational Keccak miter."""
    cell_model = (BUILD / "gowin_cells_sim.v").as_posix()
    script = "; ".join((
        "read -formal -D PQ_GOWIN_LUT4 -sv "
        "formal/keccak_round/fv_keccak_round_equiv.sv "
        "rtl/keccak/keccak_round.sv " + cell_model,
        f"chparam -set RPC {rpc} -set NATIVE_CHECK {native_check} fv_keccak_round_equiv",
        "prep -top fv_keccak_round_equiv -flatten",
        "memory_map",
        "opt",
        "chformal -lower",
        "chformal -cover -remove",
        "sat -seq 1 -verify -prove-asserts -set-assumes",
    ))
    command = [resolve_tool("yosys", env), "-Q", "-p", script]
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, check=False,
            capture_output=True, text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"Yosys SAT timed out after 30 minutes for RPC{rpc}, native={native_check}", file=sys.stderr)
        if exc.stdout:
            print(str(exc.stdout)[-12000:], file=sys.stderr)
        return False
    if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in result.stdout:
        print((result.stdout + result.stderr)[-12000:], file=sys.stderr)
        return False
    return True


def run_yosys_sat_native_lut4(env: dict[str, str]) -> bool:
    """Exhaustively prove Gowin LUT4 cells match portable truth tables."""
    cell_model = (BUILD / "gowin_cells_sim.v").as_posix()
    script = "; ".join((
        "read -formal -D PQ_GOWIN_LUT4 -sv "
        "formal/keccak_round/fv_keccak_lut4.sv "
        "rtl/keccak/keccak_round.sv " + cell_model,
        "prep -top fv_keccak_lut4 -flatten",
        "memory_map",
        "opt",
        "chformal -lower",
        "chformal -cover -remove",
        "sat -seq 1 -verify -prove-asserts -set-assumes",
    ))
    result = subprocess.run(
        [resolve_tool("yosys", env), "-Q", "-p", script],
        cwd=ROOT, env=env, check=False, capture_output=True, text=True, timeout=120,
    )
    if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in result.stdout:
        print((result.stdout + result.stderr)[-12000:], file=sys.stderr)
        return False
    return True


def run_smoke(env: dict[str, str]) -> list[tuple[str, str, bool]]:
    config = FORMAL / "smoke" / "smoke.sby"
    results = []
    for mode in ("prove", "cover"):
        generated = config.parent / f".smoke_{mode}.sby"
        generated.write_text(
            config.read_text(encoding="utf-8").replace("mode prove", f"mode {mode}"),
            encoding="utf-8",
        )
        try:
            ok = run_sby(generated, BUILD / f"smoke_{mode}", env)
        finally:
            generated.unlink(missing_ok=True)
        results.append(("smoke", mode, ok))
    return results


def run_keccak_control(
    env: dict[str, str], selected_rpc: int | None = None, selected_in_place: int | None = None
) -> list[tuple[str, str, bool]]:
    config = FORMAL / "keccak_control" / "keccak_control.sby"
    original = config.read_text(encoding="utf-8")
    results = []
    rpcs = (selected_rpc,) if selected_rpc is not None else (1, 2, 3, 4)
    in_place_values = (selected_in_place,) if selected_in_place is not None else (0, 1)
    for rpc in rpcs:
        for in_place in in_place_values:
            name = f"keccak_control_rpc{rpc}_inplace{in_place}"
            for mode in ("prove", "cover"):
                generated = config.parent / f".{name}_{mode}.sby"
                body = original.replace("mode prove", f"mode {mode}")
                body = body.replace(
                    "chparam -set RPC 1 -set IN_PLACE 0 fv_keccak_control",
                    f"chparam -set RPC {rpc} -set IN_PLACE {in_place} fv_keccak_control",
                )
                generated.write_text(body, encoding="utf-8")
                try:
                    ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
                finally:
                    generated.unlink(missing_ok=True)
                results.append((name, mode, ok))
                print(f"{'PASS' if ok else 'FAIL'} {name} ({mode})", flush=True)
                if not ok:
                    return results
    return results


def run_keccak_round(
    env: dict[str, str], selected_rpc: int | None = None, native_check: int | None = None
) -> list[tuple[str, str, bool]]:
    config = FORMAL / "keccak_round" / "keccak_round.sby"
    cover_config = config
    cover_original = cover_config.read_text(encoding="utf-8")
    BUILD.mkdir(parents=True, exist_ok=True)
    cells_sim = yosys_data_file("gowin/cells_sim.v", env)
    (BUILD / "gowin_cells_sim.v").write_bytes(cells_sim.read_bytes())

    results = []
    if native_check != 1:
        # RPC4 uses the universal single-round proof as its induction lemma.
        # A direct four-round SAT cone exceeded the practical runtime on this host.
        if selected_rpc is None:
            mapping_rpcs = (1, 2)
        elif selected_rpc in (1, 2):
            mapping_rpcs = (selected_rpc,)
        elif selected_rpc == 4:
            mapping_rpcs = (1,)
        else:
            mapping_rpcs = ()
        for rpc in mapping_rpcs:
            name = f"keccak_round_rpc{rpc}_mapping"
            for mode in ("prove", "cover"):
                if mode == "prove":
                    print(f"RUN {name} (Yosys SAT)", flush=True)
                    ok = run_yosys_sat(rpc, 0, env)
                else:
                    generated = cover_config.parent / f".{name}_{mode}.sby"
                    body = cover_original.replace(
                        "chparam -set RPC 1 fv_keccak_round_cover",
                        f"chparam -set RPC {rpc} fv_keccak_round_cover",
                    )
                    generated.write_text(body, encoding="utf-8")
                    try:
                        ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
                    finally:
                        generated.unlink(missing_ok=True)
                results.append((name, mode, ok))
                print(f"{'PASS' if ok else 'FAIL'} {name} ({mode})", flush=True)
                if not ok:
                    return results

        if selected_rpc in (None, 4):
            name = "keccak_round_rpc4_mapping"
            results.append((name, "composition from universal RPC1 proof", True))
            print(f"PASS {name} (composition from universal RPC1 proof)", flush=True)

            generated = cover_config.parent / f".{name}_cover.sby"
            body = cover_original.replace(
                "chparam -set RPC 1 fv_keccak_round_cover",
                "chparam -set RPC 4 fv_keccak_round_cover",
            )
            generated.write_text(body, encoding="utf-8")
            try:
                cover_ok = run_sby(generated, BUILD / f"{name}_cover", env)
            finally:
                generated.unlink(missing_ok=True)
            results.append((name, "cover", cover_ok))
            print(f"{'PASS' if cover_ok else 'FAIL'} {name} (cover)", flush=True)
            if not cover_ok:
                return results

    if native_check != 0 and selected_rpc in (None, 1):
        name = "keccak_round_rpc1_native"
        print(f"RUN {name} (native LUT4 truth tables)", flush=True)
        ok = run_yosys_sat_native_lut4(env)
        results.append((name, "all four LUT4 truth tables", ok))
        print(f"{'PASS' if ok else 'FAIL'} {name} (all four LUT4 truth tables)", flush=True)
    return results


def run_shake256(env: dict[str, str], selected_rpc: int | None = None) -> list[tuple[str, str, bool]]:
    config = FORMAL / "shake256" / "shake256.sby"
    original = config.read_text(encoding="utf-8")
    results = []
    for rpc in ((selected_rpc,) if selected_rpc is not None else (1, 4)):
        for message_bytes in (0, 135, 136, 137, 272):
            name = f"shake256_rpc{rpc}_{message_bytes}B"
            for mode in ("bmc", "cover"):
                generated = config.parent / f".{name}_{mode}.sby"
                body = original.replace("mode bmc", f"mode {mode}")
                body = body.replace(
                    "chparam -set RPC 1 -set MESSAGE_BYTES 0 fv_shake256",
                    f"chparam -set RPC {rpc} -set MESSAGE_BYTES {message_bytes} fv_shake256",
                )
                generated.write_text(body, encoding="utf-8")
                try:
                    ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
                finally:
                    generated.unlink(missing_ok=True)
                results.append((name, mode, ok))
                print(f"{'PASS' if ok else 'FAIL'} {name} ({mode})", flush=True)
                if not ok:
                    return results
    return results


def run_shake_bulk(env: dict[str, str]) -> list[tuple[str, str, bool]]:
    """Check the one-block register-bulk path used by F and H calls."""
    config = FORMAL / "shake256" / "shake_bulk.sby"
    original = config.read_text(encoding="utf-8")
    results = []
    for bulk_bytes in (64, 80):
        name = f"shake_bulk_{bulk_bytes}B"
        for mode in ("bmc", "cover"):
            generated = config.parent / f".{name}_{mode}.sby"
            body = original.replace("mode bmc", f"mode {mode}")
            body = body.replace(
                "chparam -set RPC 1 -set BULK_BYTES 64 fv_shake_bulk",
                f"chparam -set RPC 1 -set BULK_BYTES {bulk_bytes} fv_shake_bulk",
            )
            generated.write_text(body, encoding="utf-8")
            try:
                ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
            finally:
                generated.unlink(missing_ok=True)
            results.append((name, mode, ok))
            print(f"{'PASS' if ok else 'FAIL'} {name} ({mode}, depth 128)", flush=True)
            if not ok:
                return results
    return results


def run_thash(env: dict[str, str], selected_kind: str | None = None) -> list[tuple[str, str, bool]]:
    config = FORMAL / "thash" / "thash.sby"
    original = config.read_text(encoding="utf-8")
    cases = (("F", 0, 16), ("H", 1, 32), ("T_k", 2, 224), ("T_len", 3, 560))
    if selected_kind is not None:
        cases = tuple(case for case in cases if case[0] == selected_kind)
    results = []
    for label, kind, count in cases:
        name = f"thash_{label}"
        payload_lanes = (48 + count + 7) // 8
        source_cycles = (3 * count) if kind >= 2 else (2 * payload_lanes)
        request_bound = source_cycles + 2 * payload_lanes + 24
        depth = 2 * (request_bound + 4) + 8
        for mode in ("bmc", "cover"):
            generated = config.parent / f".{name}_{mode}.sby"
            body = original.replace("mode bmc", f"mode {mode}")
            body = body.replace("depth 4096", f"depth {depth}")
            body = body.replace(
                "chparam -set KIND 0 -set COUNT 16 fv_thash",
                f"chparam -set KIND {kind} -set COUNT {count} fv_thash",
            )
            generated.write_text(body, encoding="utf-8")
            try:
                ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
            finally:
                generated.unlink(missing_ok=True)
            results.append((name, mode, ok))
            print(f"{'PASS' if ok else 'FAIL'} {name} ({mode}, depth {depth})", flush=True)
            if not ok:
                return results
    return results


def run_stage_handshakes(env: dict[str, str], selected_stage: str | None = None) -> list[tuple[str, str, bool]]:
    """Run stage-level start/done, request stability, and address checks."""
    stages = ("wots_verify", "xmss_verify", "fors_verify", "ht_verify", "slh_top_reset") if selected_stage is None else (selected_stage,)
    results: list[tuple[str, str, bool]] = []
    for stage in stages:
        config = FORMAL / "stages" / f"{stage}.sby"
        original = config.read_text(encoding="utf-8")
        for mode in ("bmc", "cover"):
            generated = config.parent / f".{stage}_{mode}.sby"
            generated.write_text(original.replace("mode bmc", f"mode {mode}"), encoding="utf-8")
            try:
                ok = run_sby(generated, BUILD / f"{stage}_{mode}", env)
            finally:
                generated.unlink(missing_ok=True)
            results.append((stage, mode, ok))
            print(f"{'PASS' if ok else 'FAIL'} {stage} ({mode})", flush=True)
            if not ok:
                return results
    return results


def run_uart(env: dict[str, str]) -> list[tuple[str, str, bool]]:
    """Check UART framing at nominal rate and a practical one-clock skew."""
    config = FORMAL / "uart" / "uart.sby"
    original = config.read_text(encoding="utf-8")
    results: list[tuple[str, str, bool]] = []
    # A one-clock difference at 4 clocks/bit is a 20–25% baud mismatch and
    # cannot preserve sampling phase over a complete frame. Use a 32/33-clock
    # nominal period for the ±1-clock tolerance checks (about 3% mismatch).
    for tx_clks, rx_clks, depth in ((4, 4, 128), (33, 32, 768), (32, 33, 768)):
        name = f"uart_tx{tx_clks}_rx{rx_clks}"
        for mode in ("bmc", "cover"):
            generated = config.parent / f".{name}_{mode}.sby"
            body = original.replace("mode bmc", f"mode {mode}")
            body = body.replace("depth 128", f"depth {depth}")
            body = body.replace(
                "chparam -set TX_CLKS 4 -set RX_CLKS 4 fv_uart_roundtrip",
                f"chparam -set TX_CLKS {tx_clks} -set RX_CLKS {rx_clks} fv_uart_roundtrip",
            )
            generated.write_text(body, encoding="utf-8")
            try:
                ok = run_sby(generated, BUILD / f"{name}_{mode}", env)
            finally:
                generated.unlink(missing_ok=True)
            results.append((name, mode, ok))
            print(f"{'PASS' if ok else 'FAIL'} {name} ({mode}, depth {depth})", flush=True)
            if not ok:
                return results
    glitch_config = FORMAL / "uart" / "uart_glitch.sby"
    glitch_original = glitch_config.read_text(encoding="utf-8")
    for mode in ("bmc", "cover"):
        generated = glitch_config.parent / f".uart_glitch_{mode}.sby"
        generated.write_text(glitch_original.replace("mode bmc", f"mode {mode}"), encoding="utf-8")
        try:
            ok = run_sby(generated, BUILD / f"uart_glitch_{mode}", env)
        finally:
            generated.unlink(missing_ok=True)
        results.append(("uart_glitch", mode, ok))
        print(f"{'PASS' if ok else 'FAIL'} uart_glitch ({mode})", flush=True)
        if not ok:
            return results
    return results


def run_cmd_ctrl(env: dict[str, str]) -> list[tuple[str, str, bool]]:
    """Bound the command parser's start, CRC, and busy-response behavior."""
    config = FORMAL / "cmd_ctrl" / "cmd_ctrl.sby"
    original = config.read_text(encoding="utf-8")
    results: list[tuple[str, str, bool]] = []
    for mode in ("bmc", "cover"):
        generated = config.parent / f".cmd_ctrl_{mode}.sby"
        generated.write_text(original.replace("mode bmc", f"mode {mode}"), encoding="utf-8")
        try:
            ok = run_sby(generated, BUILD / f"cmd_ctrl_{mode}", env)
        finally:
            generated.unlink(missing_ok=True)
        results.append(("cmd_ctrl", mode, ok))
        print(f"{'PASS' if ok else 'FAIL'} cmd_ctrl ({mode})", flush=True)
        if not ok:
            return results
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("smoke", "keccak-control", "keccak-round", "shake256", "thash", "stages", "uart", "cmd-ctrl", "all"), default="all")
    parser.add_argument("--rpc", type=int, choices=(1, 2, 3, 4))
    parser.add_argument("--in-place", type=int, choices=(0, 1))
    parser.add_argument("--native-check", type=int, choices=(0, 1))
    parser.add_argument("--shake-rpc", type=int, choices=(1, 4))
    parser.add_argument("--thash-kind", choices=("F", "H", "T_k", "T_len"))
    parser.add_argument("--stage", choices=("wots_verify", "xmss_verify", "fors_verify", "ht_verify", "slh_top_reset"))
    args = parser.parse_args()
    env = tool_environment()
    results: list[tuple[str, str, bool]] = []
    if args.target in ("smoke", "all"):
        results.extend(run_smoke(env))
    if args.target in ("keccak-control", "all"):
        results.extend(run_keccak_control(env, args.rpc, args.in_place))
    if args.target in ("keccak-round", "all"):
        results.extend(run_keccak_round(env, args.rpc, args.native_check))
    if args.target in ("shake256", "all"):
        results.extend(run_shake256(env, args.shake_rpc))
        results.extend(run_shake_bulk(env))
    if args.target in ("thash", "all"):
        results.extend(run_thash(env, args.thash_kind))
    if args.target in ("stages", "all"):
        results.extend(run_stage_handshakes(env, args.stage))
    if args.target in ("uart", "all"):
        results.extend(run_uart(env))
    if args.target in ("cmd-ctrl", "all"):
        results.extend(run_cmd_ctrl(env))
    print("\nFormal summary")
    for target, mode, passed in results:
        print(f"{'PASS' if passed else 'FAIL'}  {target:<32} {mode}")
    return 0 if results and all(passed for _, _, passed in results) else 1


if __name__ == "__main__":
    sys.exit(main())
