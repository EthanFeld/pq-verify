`timescale 1ns/1ps
module tb_keccak_ooc #(
    parameter integer RPC = 1,
    parameter integer CASES = 16
);
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    wire busy;
    wire done;
    wire pin_out;
    logic [1599:0] expected [0:CASES-1];
    string expected_file;
    always #5 clk = ~clk;

    keccak_ooc_top #(.RPC(RPC)) dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .busy(busy), .done(done), .pin_out(pin_out)
    );

    task automatic run_case(input integer index);
        integer elapsed;
        begin
            @(negedge clk);
            start = 1'b1;
            @(posedge clk);
            #1;
            if (!busy || done) $fatal(1, "seed request was not accepted");
            @(negedge clk);
            start = 1'b0;
            fork
                begin
                    // An extra request while busy must not alter the seed.
                    wait (dut.core_busy);
                    repeat (2) @(negedge clk);
                    start = 1'b1;
                    @(negedge clk);
                    start = 1'b0;
                end
                begin
                    elapsed = 0;
                    while (!done) begin
                        @(posedge clk);
                        #1;
                        elapsed = elapsed + 1;
                        if (elapsed > 24 / RPC + 1) $fatal(1, "wrapper watchdog");
                    end
                    if (elapsed != 24 / RPC + 1) $fatal(1, "wrapper latency mismatch");
                    if (busy || dut.state_out !== expected[index])
                        $fatal(1, "seeded permutation mismatch: case %0d", index);
                    if (pin_out !== ^expected[index][255:0])
                        $fatal(1, "digest parity mismatch");
                end
            join
        end
    endtask

    initial begin
        if (!$value$plusargs("expected_file=%s", expected_file))
            $fatal(1, "expected_file is required");
        $readmemh(expected_file, expected);
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        for (integer index = 0; index < CASES; index = index + 1)
            run_case(index);

        // Reset interrupts a permutation and restores both bank and LFSR.
        @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        repeat (3) @(negedge clk);
        rst_n = 1'b0;
        #1;
        if (busy || done) $fatal(1, "reset did not clear wrapper");
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        run_case(0);
        @(posedge clk);
        #1;
        if (done) $fatal(1, "done was not a pulse");
        $display("PASS Keccak OOC RPC=%0d: %0d seeded states, busy rejection, reset, exact latency",
                 RPC, CASES + 1);
        $finish;
    end
endmodule
