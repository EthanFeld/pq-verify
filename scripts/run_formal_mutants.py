"""Run formal bug injections and require each mutation to be detected."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_formal import BUILD, run_sby  # noqa: E402
from tools import resolve_tool, tool_environment, yosys_data_file  # noqa: E402


SOURCE = ROOT / "rtl/keccak/keccak_f1600.sv"
WRAPPER = ROOT / "formal/keccak_control/fv_keccak_control.sv"
ROUND = ROOT / "rtl/keccak/keccak_round.sv"
CMD_CTRL = ROOT / "rtl/io/cmd_ctrl.sv"
CMD_CTRL_WRAPPER = ROOT / "formal/cmd_ctrl/fv_cmd_ctrl.sv"
UART_TX = ROOT / "rtl/io/uart_tx.sv"
UART_RX = ROOT / "rtl/io/uart_rx.sv"
UART_ROUNDTRIP_WRAPPER = ROOT / "formal/uart/fv_uart_roundtrip.sv"
UART_GLITCH_WRAPPER = ROOT / "formal/uart/fv_uart_glitch.sv"
UART_ROUNDTRIP_CONFIG = ROOT / "formal/uart/uart.sby"
UART_GLITCH_CONFIG = ROOT / "formal/uart/uart_glitch.sby"
THASH = ROOT / "rtl/slh/thash.sv"
THASH_WRAPPER = ROOT / "formal/thash/fv_thash.sv"
THASH_CONFIG = ROOT / "formal/thash/thash.sby"
SHAKE = ROOT / "rtl/keccak/shake256.sv"
SHAKE_WRAPPER = ROOT / "formal/shake256/fv_shake256.sv"
SHAKE_CONFIG = ROOT / "formal/shake256/shake256.sby"
WOTS = ROOT / "rtl/slh/wots_verify.sv"
WOTS_WRAPPER = ROOT / "formal/stages/fv_wots_verify.sv"
WOTS_CONFIG = ROOT / "formal/stages/wots_verify.sby"
FORS = ROOT / "rtl/slh/fors_verify.sv"
FORS_WRAPPER = ROOT / "formal/stages/fv_fors_verify.sv"
FORS_CONFIG = ROOT / "formal/stages/fors_verify.sby"
XMSS = ROOT / "rtl/slh/xmss_verify.sv"
XMSS_WRAPPER = ROOT / "formal/stages/fv_xmss_verify.sv"
XMSS_CONFIG = ROOT / "formal/stages/xmss_verify.sby"
HT = ROOT / "rtl/slh/ht_verify.sv"
HT_WRAPPER = ROOT / "formal/stages/fv_ht_verify.sv"
HT_CONFIG = ROOT / "formal/stages/ht_verify.sby"
ROUND_WRAPPER = ROOT / "formal/keccak_round/fv_keccak_round_equiv.sv"
MUTATIONS = {
    "round_count_off_by_one": (
        "round_base + RPC_COUNT >= 6'd24",
        "round_base + RPC_COUNT > 6'd24",
    ),
    "done_sticks_high": (
        "        end else begin\n            done <= 1'b0;",
        "        end else begin\n            done <= done;",
    ),
}
CMD_CTRL_MUTATIONS = {
    "cmd_ctrl_crc_accepts_bad_frame": (
        "if (!crc_matches)",
        "if (1'b0 && !crc_matches)",
    ),
    "cmd_ctrl_busy_status_dropped": (
        "else if (frame_busy)",
        "else if (1'b0 && frame_busy)",
    ),
}
UART_MUTATIONS = (
    (
        "uart_tx_reverses_bit_order",
        UART_TX,
        "ST_DATA: tx = shift_reg[bit_index];",
        "ST_DATA: tx = shift_reg[7-bit_index];",
        UART_ROUNDTRIP_WRAPPER,
        UART_ROUNDTRIP_CONFIG,
        {"../../rtl/io/uart_tx.sv": "uart_tx.sv", "../../rtl/io/uart_rx.sv": "uart_rx.sv"},
        (UART_TX, UART_RX),
    ),
    (
        "uart_rx_accepts_false_start",
        UART_RX,
        "ST_START: begin\n                    if (baud_count == 0) begin\n                        if (!rx_sync) begin",
        "ST_START: begin\n                    if (baud_count == 0) begin\n                        if (1'b1) begin",
        UART_GLITCH_WRAPPER,
        UART_GLITCH_CONFIG,
        {"../../rtl/io/uart_rx.sv": "uart_rx.sv"},
        (UART_RX,),
    ),
)
THASH_MUTATIONS = (
    (
        "thash_marks_every_lane_final",
        THASH,
        "engine_in_last = ((state == ST_READ_SOURCE) && word_source_mode\n                && src_valid && word_completes_lane) ? word_completes_message : lane_final;",
        "engine_in_last = 1'b1;",
        THASH_WRAPPER,
        THASH_CONFIG,
        {
            "../../rtl/slh/thash.sv": "thash.sv",
            "../../rtl/keccak/shake256.sv": "shake256.sv",
            "../../rtl/keccak/keccak_round.sv": "keccak_round.sv",
            "../../rtl/keccak/keccak_f1600.sv": "keccak_f1600.sv",
        },
        (THASH, ROOT / "rtl/keccak/shake256.sv", ROOT / "rtl/keccak/keccak_round.sv",
         ROOT / "rtl/keccak/keccak_f1600.sv"),
    ),
    (
        "thash_ready_reasserts_while_busy",
        THASH,
        "req_ready = (state == ST_IDLE)\n            || ((state == ST_WAIT_HASH) && engine_out_valid);",
        "req_ready = (state == ST_IDLE) || (state == ST_WAIT_HASH);",
        THASH_WRAPPER,
        THASH_CONFIG,
        {
            "../../rtl/slh/thash.sv": "thash.sv",
            "../../rtl/keccak/shake256.sv": "shake256.sv",
            "../../rtl/keccak/keccak_round.sv": "keccak_round.sv",
            "../../rtl/keccak/keccak_f1600.sv": "keccak_f1600.sv",
        },
        (THASH, ROOT / "rtl/keccak/shake256.sv", ROOT / "rtl/keccak/keccak_round.sv",
         ROOT / "rtl/keccak/keccak_f1600.sv"),
    ),
)
SHAKE_MUTATIONS = (
    (
        "shake_accepts_input_while_permuting",
        SHAKE,
        "assign in_ready = (state == ST_ABSORB) && !perm_busy && !out_valid;",
        "assign in_ready = !out_valid;",
        SHAKE_WRAPPER,
        SHAKE_CONFIG,
        {
            "../../rtl/keccak/shake256.sv": "shake256.sv",
            "../../rtl/keccak/keccak_round.sv": "keccak_round.sv",
            "../../rtl/keccak/keccak_f1600.sv": "keccak_f1600.sv",
        },
        (SHAKE, ROOT / "rtl/keccak/keccak_round.sv", ROOT / "rtl/keccak/keccak_f1600.sv"),
    ),
    (
        "shake_response_sticks_high",
        SHAKE,
        "            perm_start <= 1'b0;\n            out_valid <= 1'b0;\n\n            case (state)",
        "            perm_start <= 1'b0;\n            out_valid <= out_valid;\n\n            case (state)",
        SHAKE_WRAPPER,
        SHAKE_CONFIG,
        {
            "../../rtl/keccak/shake256.sv": "shake256.sv",
            "../../rtl/keccak/keccak_round.sv": "keccak_round.sv",
            "../../rtl/keccak/keccak_f1600.sv": "keccak_f1600.sv",
        },
        (SHAKE, ROOT / "rtl/keccak/keccak_round.sv", ROOT / "rtl/keccak/keccak_f1600.sv"),
    ),
)
STAGE_MUTATIONS = (
    (
        "wots_hash_payload_changes_on_ready",
        WOTS,
        "hash_pair = {chain_node, 128'd0};",
        "hash_pair = {chain_node, {127'd0, hash_req_ready}};",
        WOTS_WRAPPER,
        WOTS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/wots_verify.sv": "wots_verify.sv",
        },
        (WOTS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "wots_hash_address_changes_on_ready",
        WOTS,
        "chain_word = {26'd0, chain_number};",
        "chain_word = {25'd0, hash_req_ready, chain_number};",
        WOTS_WRAPPER,
        WOTS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/wots_verify.sv": "wots_verify.sv",
        },
        (WOTS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "fors_hash_payload_changes_on_ready",
        FORS,
        "hash_pair = {secret_reg, 128'd0};",
        "hash_pair = {secret_reg, {127'd0, hash_req_ready}};",
        FORS_WRAPPER,
        FORS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/fors_verify.sv": "fors_verify.sv",
        },
        (FORS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "fors_hash_address_changes_on_ready",
        FORS,
        "index_word = {16'd0, path_index};",
        "index_word = {15'd0, hash_req_ready, path_index};",
        FORS_WRAPPER,
        FORS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/fors_verify.sv": "fors_verify.sv",
        },
        (FORS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "xmss_hash_payload_changes_on_ready",
        XMSS,
        "hash_pair = (leaf_index_reg[0])\n            ? {auth_reg, node_reg}\n            : {node_reg, auth_reg};",
        "hash_pair = (leaf_index_reg[0])\n            ? {auth_reg, {node_reg[127:1], hash_req_ready}}\n            : {node_reg, {auth_reg[127:1], hash_req_ready}};",
        XMSS_WRAPPER,
        XMSS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/xmss_verify.sv": "xmss_verify.sv",
        },
        (XMSS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "xmss_hash_address_changes_on_ready",
        XMSS,
        "index_word = {24'd0, leaf_index_reg[8:1]};",
        "index_word = {23'd0, hash_req_ready, leaf_index_reg[8:1]};",
        XMSS_WRAPPER,
        XMSS_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/xmss_verify.sv": "xmss_verify.sv",
        },
        (XMSS,),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "ht_hash_payload_changes_on_ready",
        HT,
        "hash_pair = wots_hash_pair;",
        "hash_pair = {wots_hash_pair[255:1], hash_req_ready};",
        HT_WRAPPER,
        HT_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/ht_verify.sv": "ht_verify.sv",
            "../../rtl/slh/wots_verify.sv": "wots_verify.sv",
            "../../rtl/slh/xmss_verify.sv": "xmss_verify.sv",
        },
        (HT, WOTS, XMSS),
        (ROOT / "formal/common/hs_props.sv",),
    ),
    (
        "ht_hash_address_changes_on_ready",
        HT,
        "hash_adrs = wots_hash_adrs;",
        "hash_adrs = {wots_hash_adrs[255:1], hash_req_ready};",
        HT_WRAPPER,
        HT_CONFIG,
        {
            "../common/hs_props.sv": "hs_props.sv",
            "../../rtl/slh/ht_verify.sv": "ht_verify.sv",
            "../../rtl/slh/wots_verify.sv": "wots_verify.sv",
            "../../rtl/slh/xmss_verify.sv": "xmss_verify.sv",
        },
        (HT, WOTS, XMSS),
        (ROOT / "formal/common/hs_props.sv",),
    ),
)
ROUND_MUTATIONS = {
    "keccak_round_lut4_truth_table": (
        ".INIT(16'h6996)",
        ".INIT(16'h6997)",
    ),
    "keccak_round_chi_truth_table": (
        ".INIT(16'h659a)",
        ".INIT(16'h659b)",
    ),
}


def run_keccak_round_mutant(
    name: str, source: str, target_dir: Path, env: dict[str, str]
) -> bool:
    """Return true only when the full-state mapping miter finds a counterexample."""
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / ROUND_WRAPPER.name).write_bytes(ROUND_WRAPPER.read_bytes())
    (target_dir / ROUND.name).write_text(source, encoding="utf-8")
    cells_sim = yosys_data_file("gowin/cells_sim.v", env)
    (target_dir / "gowin_cells_sim.v").write_bytes(cells_sim.read_bytes())
    script = "; ".join((
        "read -formal -D PQ_GOWIN_LUT4 -sv "
        "fv_keccak_round_equiv.sv keccak_round.sv gowin_cells_sim.v",
        "chparam -set RPC 1 -set NATIVE_CHECK 0 fv_keccak_round_equiv",
        "prep -top fv_keccak_round_equiv -flatten",
        "memory_map", "opt", "chformal -lower", "chformal -cover -remove",
        "sat -seq 1 -verify -prove-asserts -set-assumes",
    ))
    try:
        result = subprocess.run(
            [resolve_tool("yosys", env), "-Q", "-p", script],
            cwd=target_dir, env=env, check=False, capture_output=True,
            text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL mutant {name}: Yosys SAT timed out", flush=True)
        return False
    output = result.stdout + result.stderr
    killed = result.returncode != 0 and "model found" in output
    if not killed:
        print(output[-12000:], file=sys.stderr, flush=True)
    print(
        f"{'PASS' if killed else 'FAIL'} mutant {name}: "
        f"counterexample={'yes' if killed else 'no'}",
        flush=True,
    )
    return killed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="run only these named mutants")
    args = parser.parse_args()
    selected = set(args.only or ())
    env = tool_environment()
    failed = False
    ran = 0
    for name, (needle, replacement) in ROUND_MUTATIONS.items():
        if selected and name not in selected:
            continue
        ran += 1
        source = ROUND.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue
        killed = run_keccak_round_mutant(
            name, source.replace(needle, replacement, 1), BUILD / "mutants" / name, env
        )
        failed |= not killed

    for name, (needle, replacement) in MUTATIONS.items():
        if selected and name not in selected:
            continue
        ran += 1
        source = SOURCE.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "fv_keccak_control.sv").write_bytes(WRAPPER.read_bytes())
        (target_dir / "keccak_round.sv").write_bytes(ROUND.read_bytes())
        (target_dir / "keccak_f1600.sv").write_text(
            source.replace(needle, replacement, 1), encoding="utf-8"
        )
        config = target_dir / "mutant.sby"
        config.write_text(
            "\n".join((
                "[options]", "mode prove", "depth 64", "multiclock on", "",
                "[engines]", "smtbmc boolector", "",
                "[script]",
                "read -formal -sv fv_keccak_control.sv keccak_round.sv keccak_f1600.sv",
                "chparam -set RPC 1 -set IN_PLACE 0 fv_keccak_control",
                "prep -top fv_keccak_control", "",
                "[files]", "fv_keccak_control.sv", "keccak_round.sv",
                "keccak_f1600.sv", "",
            )),
            encoding="utf-8",
        )
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed

    for name, (needle, replacement) in CMD_CTRL_MUTATIONS.items():
        if selected and name not in selected:
            continue
        ran += 1
        source = CMD_CTRL.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "fv_cmd_ctrl.sv").write_bytes(CMD_CTRL_WRAPPER.read_bytes())
        (target_dir / "cmd_ctrl.sv").write_text(
            source.replace(needle, replacement, 1), encoding="utf-8"
        )
        config = target_dir / "mutant.sby"
        config.write_text(
            "\n".join((
                "[options]", "mode bmc", "depth 144", "multiclock on", "",
                "[engines]", "smtbmc boolector", "",
                "[script]",
                "read -formal -D FORMAL -sv fv_cmd_ctrl.sv cmd_ctrl.sv",
                "chparam -set PK_BYTES 1 -set SIG_BYTES 4 fv_cmd_ctrl",
                "prep -top fv_cmd_ctrl", "",
                "[files]", "fv_cmd_ctrl.sv", "cmd_ctrl.sv", "",
            )),
            encoding="utf-8",
        )
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed

    for name, source_path, needle, replacement, wrapper_path, config_path, file_map, support_paths in UART_MUTATIONS:
        if selected and name not in selected:
            continue
        ran += 1
        source = source_path.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / wrapper_path.name).write_bytes(wrapper_path.read_bytes())
        for support_path in support_paths:
            body = support_path.read_text(encoding="utf-8")
            if support_path == source_path:
                body = body.replace(needle, replacement, 1)
            (target_dir / support_path.name).write_text(body, encoding="utf-8")
        config_body = config_path.read_text(encoding="utf-8")
        for original, local in file_map.items():
            config_body = config_body.replace(original, local)
        if config_path == UART_GLITCH_CONFIG:
            config_body = config_body.replace("depth 64", "depth 128", 1)
        config = target_dir / "mutant.sby"
        config.write_text(config_body, encoding="utf-8")
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed

    for name, source_path, needle, replacement, wrapper_path, config_path, file_map, support_paths in THASH_MUTATIONS:
        if selected and name not in selected:
            continue
        ran += 1
        source = source_path.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / wrapper_path.name).write_bytes(wrapper_path.read_bytes())
        for support_path in support_paths:
            body = support_path.read_text(encoding="utf-8")
            if support_path == source_path:
                body = body.replace(needle, replacement, 1)
            (target_dir / support_path.name).write_text(body, encoding="utf-8")
        config_body = config_path.read_text(encoding="utf-8")
        for original, local in file_map.items():
            config_body = config_body.replace(original, local)
        config_body = config_body.replace("depth 4096", "depth 256", 1)
        config_body = config_body.replace(
            "chparam -set KIND 0 -set COUNT 16 fv_thash",
            "chparam -set KIND 2 -set COUNT 16 fv_thash", 1,
        )
        config = target_dir / "mutant.sby"
        config.write_text(config_body, encoding="utf-8")
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed

    for name, source_path, needle, replacement, wrapper_path, config_path, file_map, support_paths in SHAKE_MUTATIONS:
        if selected and name not in selected:
            continue
        ran += 1
        source = source_path.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / wrapper_path.name).write_bytes(wrapper_path.read_bytes())
        for support_path in support_paths:
            body = support_path.read_text(encoding="utf-8")
            if support_path == source_path:
                body = body.replace(needle, replacement, 1)
            (target_dir / support_path.name).write_text(body, encoding="utf-8")
        config_body = config_path.read_text(encoding="utf-8")
        for original, local in file_map.items():
            config_body = config_body.replace(original, local)
        config = target_dir / "mutant.sby"
        config.write_text(config_body, encoding="utf-8")
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed

    for name, source_path, needle, replacement, wrapper_path, config_path, file_map, support_paths, common_paths in STAGE_MUTATIONS:
        if selected and name not in selected:
            continue
        ran += 1
        source = source_path.read_text(encoding="utf-8")
        if source.count(needle) != 1:
            print(f"FAIL {name}: source anchor must occur exactly once")
            failed = True
            continue

        target_dir = BUILD / "mutants" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / wrapper_path.name).write_bytes(wrapper_path.read_bytes())
        for support_path in support_paths:
            body = support_path.read_text(encoding="utf-8")
            body = body.replace(needle, replacement, 1)
            (target_dir / support_path.name).write_text(body, encoding="utf-8")
        for common_path in common_paths:
            (target_dir / common_path.name).write_bytes(common_path.read_bytes())
        config_body = config_path.read_text(encoding="utf-8")
        for original, local in file_map.items():
            config_body = config_body.replace(original, local)
        config = target_dir / "mutant.sby"
        config.write_text(config_body, encoding="utf-8")
        workdir = target_dir / "result"
        run_sby(config, workdir, env)
        status_file = workdir / "status"
        status = status_file.read_text(encoding="utf-8").split()[0] if status_file.is_file() else "ERROR"
        killed = status == "FAIL"
        print(f"{'PASS' if killed else 'FAIL'} mutant {name}: status={status}", flush=True)
        failed |= not killed
    if selected and ran != len(selected):
        print(f"FAIL requested {len(selected)} mutants but matched {ran}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
