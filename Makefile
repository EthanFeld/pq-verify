PYTHON ?= python
ifeq ($(OS),Windows_NT)
VERILATOR ?= verilator
else
VERILATOR ?= verilator_bin
endif
SV2V ?= sv2v
YOSYS ?= yosys
NEXTPNR ?= nextpnr-himbaechel
GOWIN_PACK ?= gowin_pack
export VERILATOR SV2V YOSYS NEXTPNR GOWIN_PACK IVERILOG VVP CXX
RTL_KECCAK := rtl/keccak/keccak_round.sv rtl/keccak/keccak_f1600.sv rtl/keccak/shake256.sv
RTL_DATAPATH := $(RTL_KECCAK) rtl/slh/adrs.sv rtl/slh/sig_ram.sv \
	rtl/slh/scratch_ram.sv rtl/slh/thash.sv rtl/slh/hmsg.sv
RTL_STAGES := $(RTL_DATAPATH) rtl/slh/fors_verify.sv rtl/slh/wots_verify.sv \
	rtl/slh/xmss_verify.sv rtl/slh/ht_verify.sv rtl/slh/slh_verify_top.sv
RTL_UART := rtl/io/uart_rx.sv rtl/io/uart_tx.sv rtl/io/crc8.sv
RTL_SYSTEM := $(RTL_STAGES) $(RTL_UART) rtl/io/cmd_ctrl.sv rtl/top/top_tn20k.sv

.PHONY: help lint formal formal-long formal-mutants formal-smoke formal-keccak-control formal-keccak-round formal-keccak-round-ci formal-keccak-round-long formal-shake256 formal-thash formal-thash-ci formal-thash-long formal-stages formal-stages-ci formal-stages-long formal-uart formal-cmd-ctrl test-keccak test-keccak-ooc test-shake test-round test-adrs test-thash test-hmsg \
	test-wots test-verify test-verify-ext test-system test-system-full \
	test-verify-smoke test-memory test-layout test-uart test-adrs test-robust test-protocol synth pnr pnr-keccak pnr-sweep pnr-scratch-sweep gowin-sweep gowin-scratch-sweep gowin-keccak-sweep collect-pnr collect-gowin collect-keccak-gowin bit bit-gowin load export-bench bench check-evidence check-hardware-parity

RPC ?= 1
SCRATCH_STYLE ?= 0
GOWIN_BUILD_DIR ?= build/gowin_final
GOWIN_PLACE_OPTION ?= 0
GOWIN_ROUTE_OPTION ?= 0
GOWIN_CABLE_INDEX ?= 4
GOWIN_CHANNEL ?= 0
SYSTEM_SIM_ARGS ?= --clks-per-bit 335
GOWIN_LOAD_ARGS ?=

help:
	@echo "SLH-DSA verifier targets:"
	@echo "  lint          Verilator lint for current RTL"
	@echo "  formal        CI formal suite (fast proof groups)"
	@echo "  formal-long   Long Keccak, thash, and stage proofs"
	@echo "  test-keccak   Keccak unit simulation"
	@echo "  test-keccak-ooc Seeded timing-wrapper simulation"
	@echo "  test-round    10,000 random Keccak round comparisons"
	@echo "  test-shake    SHAKE-256 unit simulation"
	@echo "  test-adrs     ADRS field and trace simulation"
	@echo "  test-thash    Tweakable-hash unit simulation"
	@echo "  test-hmsg      H_msg unit simulation"
	@echo "  test-wots     WOTS+ stage simulation"
	@echo "  test-verify   Full verifier regression and cycle-model check"
	@echo "  test-verify-ext Generated-vector verifier regression"
	@echo "  test-verify-smoke Selected ACVP verifier checks"
	@echo "  test-memory   Signature and scratch RAM interface checks"
	@echo "  test-layout   SHAKE-128s parameters and ADRS trace replay"
	@echo "  test-uart     UART loopback at fast and standard divisors"
	@echo "  test-robust    200 single-bit mutations and verifier recovery checks"
	@echo "  test-system   UART system simulation"
	@echo "  test-system-full Full ACVP and generated UART-top regression plus board parity"
	@echo "  test-protocol UART controller cocotb protocol checks"
	@echo "  synth         Yosys area synthesis"
	@echo "  pnr           nextpnr timing run"
	@echo "  pnr-keccak    RPC 1/2/4 out-of-context sweep"
	@echo "  pnr-sweep     Full verifier RPC 1/2/3/4 timing sweep"
	@echo "  pnr-scratch-sweep Scratch RAM block/distributed/register sweep"
	@echo "  gowin-sweep   Vendor P&R sweep for RPC 1/2/3/4"
	@echo "  gowin-scratch-sweep Vendor P&R sweep for scratch RAM styles"
	@echo "  gowin-keccak-sweep Isolated Keccak Gowin P&R for RPC 1/2/3/4"
	@echo "  collect-gowin Collect source-matched Gowin fit rows"
	@echo "  collect-keccak-gowin Collect isolated Keccak Gowin fit rows"
	@echo "  collect-pnr   Collect resource/Fmax data into bench/measurements.csv"
	@echo "  export-bench  Export source-checked core cycles and stage data"
	@echo "  bit           Pack FPGA bitstream"
	@echo "  bit-gowin     Vendor synthesis, routing and bitstream for RPC/style"
	@echo "  load          Load SRAM (hardware task only)"
	@echo "  bench         Refresh current board summary"
	@echo "  check-hardware-parity Compare committed board results with UART-top simulation"

lint:
	$(VERILATOR) --lint-only -Wall --top-module keccak_ooc_top rtl/keccak/keccak_round.sv rtl/keccak/keccak_f1600.sv rtl/top/keccak_ooc_top.sv
	$(VERILATOR) --lint-only -Wall --top-module shake256 $(RTL_KECCAK)
	$(VERILATOR) --lint-only -Wall --top-module thash -GSHARED_SHAKE=1 $(RTL_DATAPATH)
	$(VERILATOR) --lint-only -Wall --top-module hmsg -GSHARED_SHAKE=1 $(RTL_DATAPATH)
	$(VERILATOR) --lint-only -Wall --top-module fors_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module wots_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module xmss_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module ht_verify $(RTL_STAGES)
# The core returns byte addresses; aligned word reads intentionally drop bits [1:0].
	$(VERILATOR) --lint-only -Wall -Wno-UNUSEDSIGNAL --top-module slh_verify_top $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module uart_rx rtl/io/uart_rx.sv
	$(VERILATOR) --lint-only -Wall --top-module uart_tx rtl/io/uart_tx.sv
	$(VERILATOR) --lint-only -Wall --top-module crc8 rtl/io/crc8.sv
	$(VERILATOR) --lint-only -Wall --top-module cmd_ctrl $(RTL_UART) rtl/io/cmd_ctrl.sv
	$(VERILATOR) --lint-only -Wall -Wno-UNUSEDSIGNAL -DSIM --top-module top_tn20k $(RTL_SYSTEM)

formal: formal-smoke formal-keccak-control formal-keccak-round-ci formal-shake256 formal-thash-ci formal-stages-ci formal-uart formal-cmd-ctrl formal-mutants

formal-long: formal-keccak-round-long formal-thash-long formal-stages-long

formal-mutants:
	$(PYTHON) scripts/run_formal_mutants.py

formal-smoke:
	$(PYTHON) scripts/run_formal.py --target smoke

formal-keccak-control:
	$(PYTHON) scripts/run_formal.py --target keccak-control

formal-keccak-round:
	$(PYTHON) scripts/run_formal.py --target keccak-round

formal-keccak-round-ci:
	$(PYTHON) scripts/run_formal.py --target keccak-round --rpc 1

formal-keccak-round-long:
	$(PYTHON) scripts/run_formal.py --target keccak-round --rpc 2 --native-check 0
	$(PYTHON) scripts/run_formal.py --target keccak-round --rpc 4 --native-check 0

formal-shake256:
	$(PYTHON) scripts/run_formal.py --target shake256

formal-thash:
	$(PYTHON) scripts/run_formal.py --target thash

formal-thash-ci:
	$(PYTHON) scripts/run_formal.py --target thash --thash-kind F
	$(PYTHON) scripts/run_formal.py --target thash --thash-kind H

formal-thash-long:
	$(PYTHON) scripts/run_formal.py --target thash --thash-kind T_k
	$(PYTHON) scripts/run_formal.py --target thash --thash-kind T_len

formal-stages:
	$(PYTHON) scripts/run_formal.py --target stages

formal-stages-ci:
	$(PYTHON) scripts/run_formal.py --target stages --stage wots_verify
	$(PYTHON) scripts/run_formal.py --target stages --stage fors_verify
	$(PYTHON) scripts/run_formal.py --target stages --stage slh_top_reset

formal-stages-long:
	$(PYTHON) scripts/run_formal.py --target stages --stage xmss_verify
	$(PYTHON) scripts/run_formal.py --target stages --stage ht_verify

formal-uart:
	$(PYTHON) scripts/run_formal.py --target uart

formal-cmd-ctrl:
	$(PYTHON) scripts/run_formal.py --target cmd-ctrl

test-keccak:
	$(PYTHON) scripts/run_hash_sim.py --suite keccak

test-keccak-ooc:
	$(PYTHON) scripts/run_keccak_ooc_sim.py

test-round:
	$(PYTHON) scripts/run_round_sim.py

test-shake:
	$(PYTHON) scripts/run_hash_sim.py --suite shake

test-verify-smoke:
	$(PYTHON) scripts/run_verify_sim.py --tc 343 464 338 --jobs 2

test-verify:
	$(PYTHON) scripts/run_verify_sim.py --all --rpc $(RPC) --jobs 4
	$(PYTHON) scripts/check_perf_model.py --rpc $(RPC)

test-verify-ext:
	$(PYTHON) scripts/run_verify_sim.py --all --vectors vectors/shake128s/generated.json --rpc $(RPC) --jobs 4
	$(PYTHON) scripts/check_perf_model.py --vectors vectors/shake128s/generated.json --rpc $(RPC)
	$(PYTHON) scripts/export_generated_histogram.py --vectors vectors/shake128s/generated.json --rpc $(RPC)
	$(PYTHON) scripts/export_hash_cycle_breakdown.py --vectors vectors/shake128s/generated.json --rpc $(RPC)

test-memory:
	$(PYTHON) scripts/run_memory_sim.py

test-layout test-adrs:
	$(PYTHON) scripts/run_layout_sim.py

test-uart:
	$(PYTHON) scripts/run_uart_sim.py

test-thash:
	$(PYTHON) scripts/run_thash_replay.py

test-hmsg:
	$(PYTHON) scripts/run_hmsg_boundaries.py

test-wots:
	$(PYTHON) scripts/run_wots_corner.py

test-robust:
	$(PYTHON) scripts/run_robustness_sim.py --workers 4

test-system:
	$(PYTHON) scripts/run_system_sim.py $(SYSTEM_SIM_ARGS)

test-system-full:
	$(PYTHON) scripts/run_verify_sim.py --all --rpc $(RPC) --jobs 4
	$(PYTHON) scripts/run_verify_sim.py --all --vectors vectors/shake128s/generated.json --rpc $(RPC) --jobs 4
	$(PYTHON) scripts/run_system_sim.py --all --reuse-core-results --jobs 4 --clks-per-bit 4
	$(PYTHON) scripts/run_system_sim.py --all --vectors vectors/shake128s/generated.json --reuse-core-results --jobs 4 --clks-per-bit 4
	$(PYTHON) scripts/check_hardware_sim_parity.py --uart-clks-per-bit 4

test-protocol:
	$(PYTHON) scripts/run_protocol_cocotb.py

bench:
	$(PYTHON) scripts/check_evidence.py
	$(PYTHON) scripts/update_readme_results.py

check-evidence:
	$(PYTHON) scripts/check_evidence.py

check-hardware-parity:
	$(PYTHON) scripts/check_hardware_sim_parity.py --uart-clks-per-bit 4

pnr-keccak:
	$(PYTHON) scripts/keccak_build.py --rpc 1 2 4

collect-pnr:
	$(PYTHON) scripts/collect_pnr.py

export-bench:
	$(PYTHON) scripts/export_bench_inputs.py

pnr-sweep:
	SCRATCH_STYLE="$(SCRATCH_STYLE)" SV2V="$(SV2V)" YOSYS="$(YOSYS)" NEXTPNR="$(NEXTPNR)" GOWIN_PACK="$(GOWIN_PACK)" bash syn/full_rpc_sweep.sh
	$(PYTHON) scripts/collect_pnr.py

pnr-scratch-sweep:
	RPC="$(RPC)" SV2V="$(SV2V)" YOSYS="$(YOSYS)" NEXTPNR="$(NEXTPNR)" GOWIN_PACK="$(GOWIN_PACK)" bash syn/scratch_sweep.sh
	$(PYTHON) scripts/collect_pnr.py

gowin-sweep:
	$(PYTHON) scripts/run_gowin_sweep.py --mode rpc --scratch-style $(SCRATCH_STYLE) --place-option $(GOWIN_PLACE_OPTION) --route-option $(GOWIN_ROUTE_OPTION)

gowin-scratch-sweep:
	$(PYTHON) scripts/run_gowin_sweep.py --mode scratch --rpc $(RPC) --place-option $(GOWIN_PLACE_OPTION) --route-option $(GOWIN_ROUTE_OPTION)

collect-gowin:
	$(PYTHON) scripts/collect_gowin.py

gowin-keccak-sweep:
	$(PYTHON) scripts/run_gowin_sweep.py --mode keccak --place-option $(GOWIN_PLACE_OPTION) --route-option $(GOWIN_ROUTE_OPTION)

collect-keccak-gowin:
	$(PYTHON) scripts/collect_keccak_gowin.py

synth:
	$(PYTHON) scripts/board_build.py synth --rpc $(RPC) --scratch-style $(SCRATCH_STYLE)

pnr:
	$(PYTHON) scripts/board_build.py pnr --rpc $(RPC) --scratch-style $(SCRATCH_STYLE)
	$(PYTHON) scripts/collect_pnr.py

bit:
	$(PYTHON) scripts/board_build.py bit --rpc $(RPC) --scratch-style $(SCRATCH_STYLE)

bit-gowin:
	$(PYTHON) scripts/gowin_build.py --rpc $(RPC) --scratch-style $(SCRATCH_STYLE) --place-option $(GOWIN_PLACE_OPTION) --route-option $(GOWIN_ROUTE_OPTION) --build-dir $(GOWIN_BUILD_DIR)

load:
	$(PYTHON) scripts/program_board.py --build-dir $(GOWIN_BUILD_DIR) \
		--cable-index $(GOWIN_CABLE_INDEX) --channel $(GOWIN_CHANNEL) $(GOWIN_LOAD_ARGS)
