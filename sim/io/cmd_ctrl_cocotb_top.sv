module cmd_ctrl_cocotb_top #(
    parameter integer CLKS_PER_BIT = 4
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          uart_rx_pin,
    output logic          uart_tx_pin,
    input  logic          verify_start_ready,
    input  logic          ctx_ready,
    input  logic          msg_ready,
    input  logic          sig_load_ready,
    input  logic          verify_done,
    input  logic          verify_valid,
    input  logic [31:0]   verify_cycles,
    input  logic [15:0]   verify_perms,
    output logic          verify_start,
    output logic          pure_mode,
    output logic [7:0]    ctx_len,
    output logic          ctx_valid,
    output logic [7:0]    ctx_byte,
    output logic          msg_valid,
    output logic [7:0]    msg_byte,
    output logic          msg_last,
    output logic [127:0]  pk_seed,
    output logic [127:0]  pk_root,
    output logic          sig_load_en,
    output logic [10:0]   sig_load_addr,
    output logic [31:0]   sig_load_data
);
    cmd_ctrl #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut (.*);
endmodule
