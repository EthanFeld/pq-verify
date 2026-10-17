`timescale 1ns/1ps
module tb_system_uart;
    parameter integer CLKS_PER_BIT = 4;
    localparam integer MAX_FRAME_BYTES = 10000;
    localparam integer RESPONSE_TIMEOUT_CYCLES = 5000000;

    logic clk_27 = 1'b0;
    always #5 clk_27 = !clk_27;

    logic sim_rst_n = 1'b0;
    logic uart_rx_pin = 1'b1;
    wire uart_tx_pin;
    wire [5:0] led_n;
    logic [7:0] ping_bytes [0:MAX_FRAME_BYTES-1];
    logic [7:0] pk_bytes [0:MAX_FRAME_BYTES-1];
    logic [7:0] sig_bytes [0:MAX_FRAME_BYTES-1];
    logic [7:0] stale_sig_bytes [0:MAX_FRAME_BYTES-1];
    logic [7:0] verify_bytes [0:MAX_FRAME_BYTES-1];
    logic rx_byte_valid;
    logic [7:0] rx_byte;
    logic rx_framing_error;

    string ping_file;
    string pk_file;
    string sig_file;
    string stale_sig_file;
    string verify_file;
    integer ping_len;
    integer pk_len;
    integer sig_len;
    integer stale_sig_len;
    integer stale_check;
    integer verify_len;
    integer test_id;
    integer expected_valid;
    integer expected_pk_status;
    integer expected_sig_status;
    integer expected_verify_status;
    integer expected_cycles;
    integer expected_perms;
    integer wait_cycles;
    logic [7:0] response [0:9];
    logic [31:0] response_cycles;
    logic [15:0] response_perms;
    integer accepted_context_bytes;
    integer accepted_message_bytes;
    integer hmsg_input_wait_cycles;
    longint unsigned cycle_delta;
    longint unsigned cycle_tolerance;

    top_tn20k #(
        .RPC(1),
        .SCRATCH_STYLE(0),
        .CLKS_PER_BIT(CLKS_PER_BIT)
    ) dut (
        .clk_27(clk_27),
        .uart_rx_pin(uart_rx_pin),
        .uart_tx_pin(uart_tx_pin),
        .led_n(led_n),
        .sim_rst_n(sim_rst_n)
    );

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_uart_monitor (
        .clk(clk_27),
        .rst_n(sim_rst_n),
        .rx(uart_tx_pin),
        .byte_valid(rx_byte_valid),
        .byte_data(rx_byte),
        .framing_error(rx_framing_error)
    );

    always @(posedge clk_27 or negedge sim_rst_n) begin
        if (!sim_rst_n) begin
            accepted_context_bytes <= 0;
            accepted_message_bytes <= 0;
            hmsg_input_wait_cycles <= 0;
        end else begin
            if (dut.ctx_valid && dut.ctx_ready)
                accepted_context_bytes <= accepted_context_bytes + 1;
            if (dut.msg_valid && dut.msg_ready)
                accepted_message_bytes <= accepted_message_bytes + 1;
            if (dut.u_verifier.hmsg_input_wait)
                hmsg_input_wait_cycles <= hmsg_input_wait_cycles + 1;
        end
    end

    task automatic send_uart_byte(input logic [7:0] value);
        begin
            @(negedge clk_27);
            uart_rx_pin = 1'b0;
            repeat (CLKS_PER_BIT) @(negedge clk_27);
            for (integer bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                uart_rx_pin = value[bit_index];
                repeat (CLKS_PER_BIT) @(negedge clk_27);
            end
            uart_rx_pin = 1'b1;
            repeat (CLKS_PER_BIT) @(negedge clk_27);
        end
    endtask

    task automatic send_frame(input integer frame_kind, input integer length);
        logic [7:0] value;
        begin
            for (integer index = 0; index < length; index = index + 1) begin
                case (frame_kind)
                    0: value = ping_bytes[index];
                    1: value = pk_bytes[index];
                    2: value = sig_bytes[index];
                    4: value = stale_sig_bytes[index];
                    default: value = verify_bytes[index];
                endcase
                send_uart_byte(value);
            end
        end
    endtask

    task automatic receive_uart_byte(output logic [7:0] value, input integer command);
        begin
            wait_cycles = 0;
            while (rx_byte_valid !== 1'b1) begin
                @(posedge clk_27);
                #1;
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > RESPONSE_TIMEOUT_CYCLES)
                    $fatal(1, "tc %0d: UART timeout at command %0d", test_id, command);
            end
            value = rx_byte;
            if (rx_framing_error)
                $fatal(1, "tc %0d: UART framing error at command %0d", test_id, command);
            do @(negedge clk_27); while (rx_byte_valid === 1'b1);
        end
    endtask

    task automatic expect_byte(input logic [7:0] expected, input integer command);
        logic [7:0] actual;
        begin
            receive_uart_byte(actual, command);
            if (actual !== expected)
                $fatal(1, "tc %0d: command %0d response byte got=%02x expected=%02x",
                    test_id, command, actual, expected);
        end
    endtask

    initial begin
        if (!$value$plusargs("ping_file=%s", ping_file)
                || !$value$plusargs("pk_file=%s", pk_file)
                || !$value$plusargs("sig_file=%s", sig_file)
                || !$value$plusargs("stale_sig_file=%s", stale_sig_file)
                || !$value$plusargs("verify_file=%s", verify_file)
                || !$value$plusargs("ping_len=%d", ping_len)
                || !$value$plusargs("pk_len=%d", pk_len)
                || !$value$plusargs("sig_len=%d", sig_len)
                || !$value$plusargs("stale_sig_len=%d", stale_sig_len)
                || !$value$plusargs("stale_check=%d", stale_check)
                || !$value$plusargs("verify_len=%d", verify_len)
                || !$value$plusargs("test_id=%d", test_id)
                || !$value$plusargs("expected_valid=%d", expected_valid)
                || !$value$plusargs("expected_pk_status=%d", expected_pk_status)
                || !$value$plusargs("expected_sig_status=%d", expected_sig_status)
                || !$value$plusargs("expected_verify_status=%d", expected_verify_status)
                || !$value$plusargs("expected_cycles=%d", expected_cycles)
                || !$value$plusargs("expected_perms=%d", expected_perms))
            $fatal(1, "missing system-test argument");
        if (ping_len > MAX_FRAME_BYTES || pk_len > MAX_FRAME_BYTES
                || sig_len > MAX_FRAME_BYTES || verify_len > MAX_FRAME_BYTES)
            $fatal(1, "tc %0d: frame too large", test_id);

        $readmemh(ping_file, ping_bytes, 0, ping_len - 1);
        $readmemh(pk_file, pk_bytes, 0, pk_len - 1);
        $readmemh(sig_file, sig_bytes, 0, sig_len - 1);
        if (stale_check)
            $readmemh(stale_sig_file, stale_sig_bytes, 0, stale_sig_len - 1);
        $readmemh(verify_file, verify_bytes, 0, verify_len - 1);

        repeat (5) @(negedge clk_27);
        sim_rst_n = 1'b1;
        repeat (5) @(negedge clk_27);

        send_frame(0, ping_len);
        expect_byte(8'h5A, 1);
        expect_byte(8'h01, 1);
        expect_byte(8'h53, 1);
        expect_byte(8'h4C, 1);
        expect_byte(8'h48, 1);
        expect_byte(8'h56, 1);
        expect_byte(8'h01, 1);

        send_frame(1, pk_len);
        expect_byte(8'h5A, 2);
        expect_byte(8'h02, 2);
        expect_byte(8'(expected_pk_status), 2);

        send_frame(2, sig_len);
        expect_byte(8'h5A, 3);
        expect_byte(8'h03, 3);
        expect_byte(8'(expected_sig_status), 3);

        send_frame(3, verify_len);
        for (integer response_index = 0; response_index < 10; response_index = response_index + 1)
            receive_uart_byte(response[response_index], 4);

        if (response[0] !== 8'h5A || response[1] !== 8'h04
                || response[2] !== 8'(expected_verify_status))
            $fatal(1, "tc %0d: malformed VERIFY response", test_id);
        if (response[3] !== 8'(expected_valid))
            $fatal(1, "tc %0d: verdict got=%0d expected=%0d",
                test_id, response[3], expected_valid);

        response_cycles = {response[7], response[6], response[5], response[4]};
        response_perms = {response[9], response[8]};
        $display("DEBUG system tc=%0d cycles=%0d perms=%0d ctx_bytes=%0d msg_bytes=%0d skipped_wait=%0d",
            test_id, response_cycles, response_perms, accepted_context_bytes,
            accepted_message_bytes, hmsg_input_wait_cycles);
        $fflush();
        cycle_delta = response_cycles >= 32'(expected_cycles)
            ? 64'(response_cycles - 32'(expected_cycles))
            : 64'(32'(expected_cycles) - response_cycles);
        cycle_tolerance = (64'(expected_cycles) + 49) / 50;
        if (cycle_delta > cycle_tolerance)
            $fatal(1, "tc %0d: cycles got=%0d expected=%0d delta=%0d limit=%0d",
                test_id, response_cycles, expected_cycles, cycle_delta, cycle_tolerance);
        if (response_perms !== 16'(expected_perms))
            $fatal(1, "tc %0d: permutations got=%0d expected=%0d",
                test_id, response_perms, expected_perms);

        $display("PASS system tc=%0d valid=%0d cycles=%0d perms=%0d",
            test_id, response[3], response_cycles, response_perms);
        $fflush();

        if (stale_check) begin
            send_frame(4, stale_sig_len);
            expect_byte(8'h5A, 5);
            expect_byte(8'h03, 5);
            expect_byte(8'h02, 5);
            send_frame(3, verify_len);
            for (integer stale_index = 0; stale_index < 10; stale_index = stale_index + 1)
                receive_uart_byte(response[stale_index], 6);
            if (response[0] !== 8'h5A || response[1] !== 8'h04
                    || response[2] !== 8'h02 || response[3] !== 8'h00
                    || {response[9], response[8], response[7], response[6],
                        response[5], response[4]} !== 48'd0)
                $fatal(1, "tc %0d: rejected LOAD_SIG left stale VERIFY state", test_id);
            $display("PASS system stale-signature-reject tc=%0d", test_id);
            $fflush();
        end
        $finish;
    end

    initial begin
        #200000000;
        $fatal(1, "tc %0d: system UART watchdog", test_id);
    end
endmodule
