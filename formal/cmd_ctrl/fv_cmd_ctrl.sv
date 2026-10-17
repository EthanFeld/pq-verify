module fv_cmd_ctrl #(
    parameter integer PK_BYTES = 1,
    parameter integer SIG_BYTES = 4
);
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = reset_steps >= 3'd4;

    (* anyseq *) reg rx_byte_valid;
    (* anyseq *) reg [7:0] rx_byte;
    (* anyseq *) reg verify_done;
    reg core_active = 1'b0;
    reg previous_done = 1'b0;
    wire verify_start;

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    initial assume (!rst_n);

    always @(posedge clk) begin
        if (!rst_n) begin
            core_active <= 1'b0;
            previous_done <= 1'b0;
        end else begin
            assume (!verify_done || core_active);
            assume (!(verify_done && previous_done));
            previous_done <= verify_done;
            if (verify_start)
                core_active <= 1'b1;
            if (verify_done)
                core_active <= 1'b0;
        end
    end

    cmd_ctrl #(
        .CLKS_PER_BIT(4),
        .PK_BYTES(PK_BYTES),
        .SIG_BYTES(SIG_BYTES)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .uart_rx_pin(1'b1),
        .uart_tx_pin(),
        .verify_start(verify_start),
        .verify_start_ready(1'b1),
        .pure_mode(),
        .ctx_len(),
        .ctx_valid(),
        .ctx_ready(1'b1),
        .ctx_byte(),
        .msg_valid(),
        .msg_ready(1'b1),
        .msg_byte(),
        .msg_last(),
        .pk_seed(),
        .pk_root(),
        .sig_load_en(),
        .sig_load_addr(),
        .sig_load_data(),
        .sig_load_ready(1'b1),
        .verify_done(verify_done),
        .verify_valid(1'b1),
        .verify_cycles(32'd0),
        .verify_perms(16'd0),
        .formal_rx_byte_valid(rx_byte_valid),
        .formal_rx_byte(rx_byte)
    );
endmodule
