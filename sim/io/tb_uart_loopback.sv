`timescale 1ns/1ps
module uart_loopback_case #(
    parameter integer CLKS_PER_BIT = 4,
    parameter integer CASE_ID = 0
) (
    input  logic clk,
    input  logic rst_n,
    output logic done = 0
);
    logic tx_valid = 0;
    logic [7:0] tx_data = 0;
    wire tx_ready, tx_line;
    wire rx_valid, framing_error;
    wire [7:0] rx_data;
    logic [7:0] expected [0:2];
    integer received = 0;

    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) tx (
        .clk(clk), .rst_n(rst_n), .byte_valid(tx_valid), .byte_ready(tx_ready),
        .byte_data(tx_data), .tx(tx_line)
    );
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) rx (
        .clk(clk), .rst_n(rst_n), .rx(tx_line), .byte_valid(rx_valid),
        .byte_data(rx_data), .framing_error(framing_error)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            received = 0;
            done = 0;
        end else begin
            if (framing_error)
                $fatal(1, "UART framing error CPB=%0d", CLKS_PER_BIT);
            if (rx_valid) begin
                if (received >= 3 || rx_data !== expected[received])
                    $fatal(1, "UART loopback mismatch CPB=%0d index=%0d got=%02x expected=%02x",
                           CLKS_PER_BIT, received, rx_data, expected[received]);
                received = received + 1;
                if (received == 3) begin
                    done = 1;
                    $display("PASS UART loopback CPB=%0d bytes=3", CLKS_PER_BIT);
                end
            end
        end
    end

    initial begin
        expected[0] = 8'h00;
        expected[1] = 8'ha5;
        expected[2] = 8'hff;
        wait (rst_n);
        for (integer index = 0; index < 3; index = index + 1) begin
            @(negedge clk);
            while (!tx_ready) @(negedge clk);
            tx_data = expected[index];
            tx_valid = 1;
            @(negedge clk);
            tx_valid = 0;
        end
    end
endmodule

module tb_uart_loopback;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    wire done_fast, done_uart;

    uart_loopback_case #(.CLKS_PER_BIT(4), .CASE_ID(4)) fast_case (
        .clk(clk), .rst_n(rst_n), .done(done_fast)
    );
    uart_loopback_case #(.CLKS_PER_BIT(434), .CASE_ID(434)) uart_case (
        .clk(clk), .rst_n(rst_n), .done(done_uart)
    );

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        wait (done_fast && done_uart);
        $display("PASS UART loopback suite CPB=4,434");
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "UART loopback watchdog");
    end
endmodule
