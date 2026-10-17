module fv_shake256 #(
    parameter integer RPC = 1,
    parameter integer MESSAGE_BYTES = 0
);
    localparam integer RATE_BYTES = 136;
    localparam integer BEATS = (MESSAGE_BYTES == 0) ? 1 : ((MESSAGE_BYTES + 7) / 8);
    localparam integer EXPECTED_PERMUTATIONS = (MESSAGE_BYTES / RATE_BYTES) + 1;
    localparam integer BOUND_CYCLES = BEATS + EXPECTED_PERMUTATIONS * (24 / RPC + 4) + 8;

    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = (reset_steps >= 3'd4);

    reg [7:0] beat_index = 8'd0;
    reg [1:0] message_index = 2'd0;
    reg [1:0] completed_messages = 2'd0;
    reg [15:0] accepted_bytes = 16'd0;
    reg [7:0] permutation_count = 8'd0;
    reg [10:0] cycles_after_last = 11'd0;
    reg accepted_last = 1'b0;
    reg observed_out = 1'b0;

    (* anyconst *) reg [63:0] input_word;
    wire in_valid = (message_index < 2);
    wire in_last = in_valid && (beat_index == BEATS - 1);
    wire [3:0] in_bytes = (MESSAGE_BYTES == 0) ? 4'd0 :
        ((in_last && (MESSAGE_BYTES % 8) != 0) ? 4'(MESSAGE_BYTES % 8) : 4'd8);
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
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_data(input_word),
        .in_bytes(in_bytes),
        .in_last(in_last),
        .bulk_valid(1'b0),
        .bulk_ready(),
        .bulk_lanes(640'b0),
        .bulk_bytes(7'b0),
        .out_valid(out_valid),
        .out(out_data),
        .permutation_start(permutation_start),
        .formal_perm_busy(permutation_busy)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            beat_index <= 8'd0;
            message_index <= 2'd0;
            completed_messages <= 2'd0;
            accepted_bytes <= 16'd0;
            permutation_count <= 8'd0;
            cycles_after_last <= 11'd0;
            accepted_last <= 1'b0;
            observed_out <= 1'b0;
        end else begin
            if (permutation_busy)
                assert (!in_ready);

            if (in_valid && in_ready) begin
                assert (message_index == completed_messages);
                accepted_bytes <= accepted_bytes + in_bytes;
                if (in_last) begin
                    accepted_last <= 1'b1;
                    message_index <= message_index + 1'b1;
                    beat_index <= 8'd0;
                end else begin
                    beat_index <= beat_index + 1'b1;
                end
            end

            if (permutation_start)
                permutation_count <= permutation_count + 1'b1;

            if (accepted_last && !observed_out && !out_valid) begin
                assert (!(in_valid && in_ready));
                assert (cycles_after_last < BOUND_CYCLES);
                cycles_after_last <= cycles_after_last + 1'b1;
            end

            if (out_valid) begin
                assert (accepted_last);
                assert (!observed_out);
                assert (message_index == completed_messages + 1'b1);
                assert (accepted_bytes == MESSAGE_BYTES);
                assert (permutation_count == EXPECTED_PERMUTATIONS);
                completed_messages <= completed_messages + 1'b1;
                observed_out <= 1'b1;
                if (completed_messages == 0) begin
                    accepted_bytes <= 16'd0;
                    permutation_count <= 8'd0;
                    cycles_after_last <= 11'd0;
                    accepted_last <= 1'b0;
                    observed_out <= 1'b0;
                end else begin
                    message_index <= 2'd2;
                end
            end

            assert (permutation_count <= EXPECTED_PERMUTATIONS);
            if (in_valid)
                assert (!(in_bytes < 4'd8 && !in_last));
            cover (permutation_busy && !in_ready);
            cover (out_valid && completed_messages == 1 && accepted_bytes == MESSAGE_BYTES &&
                permutation_count == EXPECTED_PERMUTATIONS);
        end
    end
endmodule
