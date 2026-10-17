PYTHON ?= python
VERILATOR ?= verilator
SV2V ?= $(if $(wildcard .tools/sv2v/sv2v-Windows/sv2v.exe),.tools/sv2v/sv2v-Windows/sv2v.exe,sv2v)
YOSYS ?= yosys
NEXTPNR ?= nextpnr-himbaechel
GOWIN_PACK ?= gowin_pack
export SV2V YOSYS NEXTPNR GOWIN_PACK
RTL_KECCAK := rtl/keccak/keccak_round.sv rtl/keccak/keccak_f1600.sv rtl/keccak/shake256.sv
RTL_DATAPATH := $(RTL_KECCAK) rtl/slh/adrs.sv rtl/slh/sig_ram.sv \
	rtl/slh/scratch_ram.sv rtl/slh/thash.sv rtl/slh/hmsg.sv
RTL_STAGES := $(RTL_DATAPATH) rtl/slh/fors_verify.sv rtl/slh/wots_verify.sv \
	rtl/slh/xmss_verify.sv rtl/slh/ht_verify.sv rtl/slh/slh_verify_top.sv
RTL_UART := rtl/io/uart_rx.sv rtl/io/uart_tx.sv rtl/io/crc8.sv
RTL_SYSTEM := $(RTL_STAGES) $(RTL_UART) rtl/io/cmd_ctrl.sv rtl/top/top_tn20k.sv

.PHONY: help lint test-keccak test-keccak-ooc test-shake test-round test-adrs test-thash test-hmsg \
	test-wots test-verify test-system \
	test-verify-smoke test-memory test-layout test-uart test-adrs test-robust test-protocol synth pnr pnr-keccak pnr-sweep pnr-scratch-sweep gowin-sweep gowin-scratch-sweep gowin-keccak-sweep collect-pnr collect-gowin collect-keccak-gowin bit bit-gowin load export-bench bench

RPC ?= 1
SCRATCH_STYLE ?= 0
GOWIN_BUILD_DIR ?= build/gowin_final
GOWIN_PLACE_OPTION ?= 0
GOWIN_ROUTE_OPTION ?= 0
GOWIN_CABLE_INDEX ?= 4
GOWIN_CHANNEL ?= 0
SYSTEM_SIM_ARGS ?=
GOWIN_LOAD_ARGS ?=

help:
	@echo "SLH-DSA verifier targets:"
	@echo "  lint          Verilator lint for current RTL"
	@echo "  test-keccak   Keccak unit simulation"
	@echo "  test-keccak-ooc Seeded timing-wrapper simulation"
	@echo "  test-round    10,000 random Keccak round comparisons"
	@echo "  test-shake    SHAKE-256 unit simulation"
	@echo "  test-adrs     ADRS field and trace simulation"
	@echo "  test-thash    Tweakable-hash unit simulation"
	@echo "  test-hmsg      H_msg unit simulation"
	@echo "  test-wots     WOTS+ stage simulation"
	@echo "  test-verify   Full verifier regression and cycle-model check"
	@echo "  test-verify-smoke Selected ACVP verifier checks"
	@echo "  test-memory   Signature and scratch RAM interface checks"
	@echo "  test-layout   SHAKE-128s parameters and ADRS trace replay"
	@echo "  test-uart     UART loopback at fast and standard divisors"
	@echo "  test-robust    200 single-bit mutations and verifier recovery checks"
	@echo "  test-system   UART system simulation"
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
	@echo "  bench         Generate benchmark table and plots"

lint:
	$(VERILATOR) --lint-only -Wall --top-module keccak_ooc_top rtl/keccak/keccak_round.sv rtl/keccak/keccak_f1600.sv rtl/top/keccak_ooc_top.sv
	$(VERILATOR) --lint-only -Wall --top-module shake256 $(RTL_KECCAK)
	$(VERILATOR) --lint-only -Wall --top-module thash -GSHARED_SHAKE=1 $(RTL_DATAPATH)
	$(VERILATOR) --lint-only -Wall --top-module hmsg -GSHARED_SHAKE=1 $(RTL_DATAPATH)
	$(VERILATOR) --lint-only -Wall --top-module fors_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module wots_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module xmss_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module ht_verify $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module slh_verify_top $(RTL_STAGES)
	$(VERILATOR) --lint-only -Wall --top-module uart_rx rtl/io/uart_rx.sv
	$(VERILATOR) --lint-only -Wall --top-module uart_tx rtl/io/uart_tx.sv
	$(VERILATOR) --lint-only -Wall --top-module crc8 rtl/io/crc8.sv
	$(VERILATOR) --lint-only -Wall --top-module cmd_ctrl $(RTL_UART) rtl/io/cmd_ctrl.sv
	$(VERILATOR) --lint-only -Wall -DSIM --top-module top_tn20k $(RTL_SYSTEM)

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

test-protocol:
	$(PYTHON) scripts/run_protocol_cocotb.py

bench:
	$(PYTHON) scripts/build_bench.py

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
