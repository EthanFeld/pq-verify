`timescale 1ns/1ps
module tb_keccak;
    parameter integer RPC = 1;
    parameter integer IN_PLACE = 0;
    parameter integer CASES = 1000;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    logic start = 0;
    logic state_load = 0;
    logic [1599:0] state_in = 0;
    wire [1599:0] state_out;
    wire busy, done;
    logic [1599:0] inputs [0:CASES-1];
    logic [1599:0] expected [0:CASES-1];
    string input_file, expected_file;

    keccak_f1600 #(.RPC(RPC), .IN_PLACE(IN_PLACE)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .state_load(state_load),
        .state_in(state_in), .state_out(state_out), .busy(busy), .done(done)
    );

    task automatic check_case(input integer index);
        @(negedge clk);
        state_in = inputs[index];
        if (IN_PLACE != 0) begin
            state_load = 1;
            @(negedge clk);
            state_load = 0;
        end
        start = 1;
        @(posedge clk); #1;
        if (!busy || done) $fatal(1, "start handshake failed");
        @(negedge clk);
        start = 0;
        // Once accepted, the external input must no longer affect the round.
        state_in = ~inputs[index];
        for (integer cycle = 1; cycle <= 24 / RPC; cycle = cycle + 1) begin
            @(posedge clk); #1;
            if (done !== (cycle == 24 / RPC))
                $fatal(1, "case %0d: wrong done latency at cycle %0d", index, cycle);
        end
        if (busy || state_out !== expected[index])
            $fatal(1, "case %0d: permutation mismatch", index);
        @(posedge clk); #1;
        if (done) $fatal(1, "done must pulse for one cycle");
    endtask

    initial begin
        if (!$value$plusargs("input_file=%s", input_file)
                || !$value$plusargs("expected_file=%s", expected_file))
            $fatal(1, "missing vector files");
        $readmemh(input_file, inputs);
        $readmemh(expected_file, expected);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (integer index = 0; index < CASES; index = index + 1)
            check_case(index);
        // Reset must abort an active permutation and allow a fresh request.
        @(negedge clk);
        start = 1;
        repeat (2) @(negedge clk);
        rst_n = 0;
        start = 0;
        #1;
        if (busy || done || state_out !== 1600'd0)
            $fatal(1, "reset did not clear an active permutation");
        @(negedge clk);
        rst_n = 1;
        check_case(0);
        $display("PASS keccak RPC=%0d IN_PLACE=%0d: %0d states, latency, reset", RPC, IN_PLACE, CASES);
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1, "simulation watchdog");
    end
endmodule
