module fv_shake_bulk #(
    parameter integer RPC = 1,
    parameter integer BULK_BYTES = 64
);
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = (reset_steps >= 3'd4);

    reg bulk_sent = 1'b0;
    reg output_seen = 1'b0;
    reg [7:0] cycles_after_bulk = 8'd0;
    reg [2:0] permutation_count = 3'd0;
    reg past_valid = 1'b0;

    (* anyconst *) reg [639:0] input_lanes;
    wire bulk_valid = rst_n && !bulk_sent;
    wire bulk_ready;
    wire [6:0] bulk_bytes = 7'(BULK_BYTES);
    wire in_ready;
    wire out_valid;
    wire [255:0] out_data;
    wire permutation_start;
    wire permutation_busy;

    initial assume (!rst_n);

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    shake256 #(
        .RPC(RPC),
        .FORMAL_CONTROL_ONLY(1)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(1'b0),
        .in_ready(in_ready),
        .in_data(64'b0),
        .in_bytes(4'b0),
        .in_last(1'b0),
        .bulk_valid(bulk_valid),
        .bulk_ready(bulk_ready),
        .bulk_lanes(input_lanes),
        .bulk_bytes(bulk_bytes),
        .out_valid(out_valid),
        .out(out_data),
        .permutation_start(permutation_start),
        .formal_perm_busy(permutation_busy)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            bulk_sent <= 1'b0;
            output_seen <= 1'b0;
            cycles_after_bulk <= 8'd0;
            permutation_count <= 3'd0;
            past_valid <= 1'b0;
        end else begin
            if (permutation_busy)
                assert (!in_ready && !bulk_ready);
            assert (!bulk_ready || (!permutation_busy && !out_valid));

            if (past_valid && $past(bulk_valid && !bulk_ready)) begin
                assert (bulk_valid);
                assert (input_lanes == $past(input_lanes));
                assert (bulk_bytes == $past(bulk_bytes));
            end

            if (bulk_valid && bulk_ready) begin
                assert (!bulk_sent);
                assert (BULK_BYTES == 64 || BULK_BYTES == 80);
                bulk_sent <= 1'b1;
            end

            if (permutation_start)
                permutation_count <= permutation_count + 1'b1;

            if (bulk_sent && !output_seen) begin
                assert (cycles_after_bulk < 8'd64);
                cycles_after_bulk <= cycles_after_bulk + 1'b1;
            end

            if (out_valid) begin
                assert (bulk_sent);
                assert (!output_seen);
                assert (permutation_count == 1);
                output_seen <= 1'b1;
            end

            if (past_valid && $past(out_valid))
                assert (!out_valid);

            cover (bulk_valid && bulk_ready);
            cover (out_valid && permutation_count == 1);
            past_valid <= 1'b1;
        end
    end
endmodule
