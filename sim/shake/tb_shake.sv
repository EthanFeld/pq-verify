`timescale 1ns/1ps
module tb_shake;
    parameter integer RPC = 1;
    parameter integer CASES = 1;
    parameter integer BEATS = 1;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    logic in_valid = 0;
    logic [63:0] in_data = 0;
    logic [3:0] in_bytes = 0;
    logic in_last = 0;
    wire in_ready, out_valid, permutation_start;
    wire [255:0] out;
    logic [68:0] beats [0:BEATS-1];
    logic [351:0] cases [0:CASES-1];
    string beats_file, cases_file;
    integer permutations = 0;
    integer before_permutations, offset, count, length, waits;
    integer random_seed = 32'h1285aee;
    integer unused_random;

    shake256 #(.RPC(RPC)) dut (
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
        .in_data(in_data), .in_bytes(in_bytes), .in_last(in_last),
        .bulk_valid(1'b0), .bulk_ready(), .bulk_lanes(640'b0), .bulk_bytes(7'b0),
        .out_valid(out_valid), .out(out), .permutation_start(permutation_start)
    );

    always @(posedge clk)
        if (rst_n && permutation_start) permutations = permutations + 1;

    task automatic send_beat(input logic [68:0] beat);
        repeat ($urandom_range(0, 2)) @(negedge clk);
        @(negedge clk);
        {in_last, in_bytes, in_data} = beat;
        in_valid = 1;
        waits = 0;
        while (!in_ready) begin
            @(negedge clk);
            waits = waits + 1;
            if (waits > 100) $fatal(1, "input stalled");
        end
        @(posedge clk); #1;
        @(negedge clk);
        in_valid = 0;
        in_last = 0;
        in_data = ~in_data;
    endtask

    initial begin
        if (!$value$plusargs("beats_file=%s", beats_file)
                || !$value$plusargs("cases_file=%s", cases_file))
            $fatal(1, "missing vector files");
        $readmemh(beats_file, beats);
        $readmemh(cases_file, cases);
        unused_random = $urandom(random_seed);
        repeat (3) @(negedge clk);
        rst_n = 1;
        // Discard a partially absorbed message, then check empty-message
        // hashing first so stale data in the shared bank cannot hide.
        send_beat({1'b0, 4'd8, 64'h0123456789abcdef});
        @(negedge clk);
        rst_n = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        for (integer index = 0; index < CASES; index = index + 1) begin
            length = cases[index][351:320];
            offset = cases[index][319:288];
            count = cases[index][287:256];
            before_permutations = permutations;
            for (integer beat = 0; beat < count; beat = beat + 1)
                send_beat(beats[offset + beat]);
            waits = 0;
            while (!out_valid) begin
                @(posedge clk); #1;
                waits = waits + 1;
                if (waits > 100) $fatal(1, "case %0d: output stalled", index);
            end
            if (out !== cases[index][255:0])
                $fatal(1, "case %0d length=%0d: SHAKE mismatch got=%h expected=%h", index, length, out, cases[index][255:0]);
            if (permutations - before_permutations != length / 136 + 1)
                $fatal(1, "case %0d: permutation count mismatch", index);
            @(posedge clk); #1;
            if (out_valid) $fatal(1, "out_valid must pulse for one cycle");
        end
        $display("PASS shake RPC=%0d: %0d hashlib cases, stalls, padding, permutation counts", RPC, CASES);
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1, "simulation watchdog");
    end
endmodule
