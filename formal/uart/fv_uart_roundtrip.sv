module fv_uart_roundtrip #(
    parameter integer TX_CLKS = 4,
    parameter integer RX_CLKS = 4
);
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = (reset_steps >= 3'd4);

    (* anyconst *) reg [7:0] tx_byte;
    reg sent = 1'b0;
    reg received = 1'b0;
    wire tx_ready;
    wire tx;
    wire rx_valid;
    wire [7:0] rx_byte;
    wire framing_error;

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    initial assume (!rst_n);

    uart_tx #(.CLKS_PER_BIT(TX_CLKS)) tx_dut (
        .clk(clk), .rst_n(rst_n), .byte_valid(rst_n && !sent),
        .byte_ready(tx_ready), .byte_data(tx_byte), .tx(tx)
    );
    uart_rx #(.CLKS_PER_BIT(RX_CLKS)) rx_dut (
        .clk(clk), .rst_n(rst_n), .rx(tx), .byte_valid(rx_valid),
        .byte_data(rx_byte), .framing_error(framing_error)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            sent <= 1'b0;
            received <= 1'b0;
        end else begin
            if (!sent && tx_ready)
                sent <= 1'b1;
            assert (!framing_error);
            if (rx_valid) begin
                assert (sent);
                assert (rx_byte == tx_byte);
                assert (!received);
                received <= 1'b1;
            end
            if (tx_ready)
                assert (tx);

            cover (sent);
            cover (received);
        end
    end
endmodule
