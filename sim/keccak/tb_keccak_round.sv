`timescale 1ns/1ps
module tb_keccak_round;
    parameter integer CASES = 10000;
    parameter integer LUT4_MAP = 0;

    logic [1599:0] state_in = 0;
    logic [4:0] round_idx = 0;
    wire [1599:0] state_out;
    logic [3207:0] vectors [0:CASES-1];
    string vectors_file;
    integer checks = 0;

    keccak_round #(.LUT4_MAP(LUT4_MAP)) dut (
        .state_in(state_in), .round_idx(round_idx), .state_out(state_out)
    );

    initial begin
        if (!$value$plusargs("vectors_file=%s", vectors_file))
            $fatal(1, "missing vectors_file");
        $readmemh(vectors_file, vectors);
        for (integer index = 0; index < CASES; index = index + 1) begin
            state_in = vectors[index][3207:1608];
            round_idx = vectors[index][1604:1600];
            #1;
            if (state_out !== vectors[index][1599:0])
                $fatal(1, "round mismatch vector=%0d round=%0d", index, round_idx);
            checks = checks + 1;
        end
        $display("PASS Keccak round LUT4_MAP=%0d state/round pairs=%0d", LUT4_MAP, checks);
        $finish;
    end
endmodule
