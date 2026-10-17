module top_tn20k #(
    parameter integer RPC = 1,
    parameter integer SCRATCH_STYLE = 0,
`ifdef SIM
    // Simulation bypasses the PLL and uses the 27 MHz reference clock.
    parameter integer CLKS_PER_BIT = 234
`else
    // 27 MHz * 11 / 8 = 37.125 MHz; 322 cycles/bit is 115.3 kbaud.
    parameter integer CLKS_PER_BIT = 322
`endif
) (
    input  logic       clk_27,
    input  logic       uart_rx_pin,
    output logic       uart_tx_pin,
    output logic [5:0] led_n
`ifdef SIM
    , input logic      sim_rst_n
`endif
);
    logic core_clk;
    // Intentional async assertion / sync release reset chain. Its released
    // output also serves as an async reset to downstream state machines.
    /* verilator lint_off SYNCASYNCNET */
    logic [1:0] reset_sync;
    /* verilator lint_on SYNCASYNCNET */
    logic rst_n;
    logic verify_start;
    logic verify_start_ready;
    logic pure_mode;
    logic [7:0] ctx_len;
    logic ctx_valid;
    logic ctx_ready;
    logic [7:0] ctx_byte;
    logic msg_valid;
    logic msg_ready;
    logic [7:0] msg_byte;
    logic msg_last;
    logic [127:0] pk_seed;
    logic [127:0] pk_root;
    logic sig_load_en;
    logic [10:0] sig_load_addr;
    logic [31:0] sig_load_data;
    logic sig_load_ready;
    logic verify_done;
    logic verify_valid;
    logic [31:0] verify_cycles;
    logic [15:0] verify_perms;
    logic verify_busy;
    logic result_seen;
    logic result_valid;

`ifdef SIM
    assign core_clk = clk_27;

    always_ff @(posedge core_clk or negedge sim_rst_n) begin
        if (!sim_rst_n)
            reset_sync <= 2'b00;
        else
            reset_sync <= {reset_sync[0], 1'b1};
    end
`else
    logic pll_locked;
    logic pll_stable;

    // IDIV=8, FBDIV=11, ODIV=16: 27 MHz in, 37.125 MHz out, 594 MHz VCO.
    rPLL #(
        .FCLKIN("27"),
        .DEVICE("GW2AR-18C"),
        .DYN_IDIV_SEL("false"),
        .IDIV_SEL(7),
        .DYN_FBDIV_SEL("false"),
        .FBDIV_SEL(10),
        .DYN_ODIV_SEL("false"),
        .ODIV_SEL(16),
        .PSDA_SEL("0000"),
        .DYN_DA_EN("false"),
        .DUTYDA_SEL("1000"),
        .CLKFB_SEL("internal")
    ) u_rpll (
        .CLKOUT(core_clk),
        .LOCK(pll_locked),
        .CLKOUTP(),
        .CLKOUTD(),
        .CLKOUTD3(),
        .RESET(1'b0),
        .RESET_P(1'b0),
        .CLKIN(clk_27),
        .CLKFB(1'b0),
        .FBDSEL(6'b0),
        .IDSEL(6'b0),
        .ODSEL(6'b0),
        .PSDA(4'b0),
        .DUTYDA(4'b0),
        .FDLY(4'b0)
    );

    logic [15:0] lock_count;
    localparam logic [15:0] LOCK_STABLE_CYCLES = 16'd54000;

    // Gowin documents that LOCK can glitch while acquiring lock. Require it
    // to remain high for 2 ms on the reference clock before releasing logic.
    always_ff @(posedge clk_27 or negedge pll_locked) begin
        if (!pll_locked) begin
            lock_count <= 16'd0;
            pll_stable <= 1'b0;
        end else if (!pll_stable) begin
            if (lock_count == LOCK_STABLE_CYCLES - 1'b1) begin
                lock_count <= LOCK_STABLE_CYCLES;
                pll_stable <= 1'b1;
            end else begin
                lock_count <= lock_count + 1'b1;
            end
        end
    end

    // Asynchronous assertion, synchronous deassertion in the core domain.
    always_ff @(posedge core_clk or negedge pll_stable) begin
        if (!pll_stable)
            reset_sync <= 2'b00;
        else
            reset_sync <= {reset_sync[0], 1'b1};
    end
`endif

    assign rst_n = reset_sync[1];

    cmd_ctrl #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_cmd_ctrl (
        .clk(core_clk),
        .rst_n(rst_n),
        .uart_rx_pin(uart_rx_pin),
        .uart_tx_pin(uart_tx_pin),
        .verify_start(verify_start),
        .verify_start_ready(verify_start_ready),
        .pure_mode(pure_mode),
        .ctx_len(ctx_len),
        .ctx_valid(ctx_valid),
        .ctx_ready(ctx_ready),
        .ctx_byte(ctx_byte),
        .msg_valid(msg_valid),
        .msg_ready(msg_ready),
        .msg_byte(msg_byte),
        .msg_last(msg_last),
        .pk_seed(pk_seed),
        .pk_root(pk_root),
        .sig_load_en(sig_load_en),
        .sig_load_addr(sig_load_addr),
        .sig_load_data(sig_load_data),
        .sig_load_ready(sig_load_ready),
        .verify_done(verify_done),
        .verify_valid(verify_valid),
        .verify_cycles(verify_cycles),
        .verify_perms(verify_perms)
    );

    slh_verify_top #(.RPC(RPC), .SCRATCH_STYLE(SCRATCH_STYLE)) u_verifier (
        .clk(core_clk),
        .rst_n(rst_n),
        .start(verify_start),
        .start_ready(verify_start_ready),
        .pure_mode(pure_mode),
        .ctx_len(ctx_len),
        .ctx_valid(ctx_valid),
        .ctx_ready(ctx_ready),
        .ctx_byte(ctx_byte),
        .msg_valid(msg_valid),
        .msg_ready(msg_ready),
        .msg_byte(msg_byte),
        .msg_last(msg_last),
        .pk_seed(pk_seed),
        .pk_root(pk_root),
        .sig_load_en(sig_load_en),
        .sig_load_addr(sig_load_addr),
        .sig_load_data(sig_load_data),
        .sig_load_ready(sig_load_ready),
        .done(verify_done),
        .valid(verify_valid),
        .cycles(verify_cycles),
        .perms(verify_perms)
    );

    always_ff @(posedge core_clk or negedge rst_n) begin
        if (!rst_n) begin
            verify_busy <= 1'b0;
            result_seen <= 1'b0;
            result_valid <= 1'b0;
        end else begin
            if (verify_start) begin
                verify_busy <= 1'b1;
                result_seen <= 1'b0;
            end
            if (verify_done) begin
                verify_busy <= 1'b0;
                result_seen <= 1'b1;
                result_valid <= verify_valid;
            end
        end
    end

    always_comb begin
        led_n = 6'b111111;
        led_n[0] = verify_busy;                 // LED0 on while idle
        led_n[1] = !verify_busy;                // LED1 on while verifying
        led_n[2] = !(result_seen && result_valid); // LED2 on for valid
        led_n[3] = !(result_seen && !result_valid); // LED3 on for invalid
    end
endmodule
