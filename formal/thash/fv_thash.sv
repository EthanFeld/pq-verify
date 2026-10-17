// Contract: one-cycle src_valid after src_rd_en; source byte is any stable
// value. Shared SHAKE input ready stalls one cycle in four; output valid pulses
// two cycles after the accepted final word. No real memory or sponge is modeled.
module fv_thash #(
    parameter integer KIND = 0,
    parameter integer COUNT = 16
);
    localparam integer PREFIX_BYTES = 48;
    localparam integer TOTAL_BYTES = PREFIX_BYTES + COUNT;
    localparam integer TOTAL_LANES = (TOTAL_BYTES + 7) / 8;
    localparam integer REQUEST_BOUND = (KIND >= 2)
        ? (3 * COUNT + 2 * TOTAL_LANES + 24)
        : (3 * TOTAL_LANES + 24);

    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = (reset_steps >= 3'd4);

    reg request_sent = 1'b0;
    reg outstanding = 1'b0;
    reg response_seen = 1'b0;
    reg [1:0] ready_phase = 2'd0;
    reg source_valid_reg = 1'b0;
    reg shake_output_valid_reg = 1'b0;
    reg [1:0] shake_output_delay = 2'd0;
    reg [15:0] shake_bytes = 16'd0;
    reg [1:0] shake_last_count = 2'd0;
    reg [12:0] request_age = 13'd0;
    reg past_valid = 1'b0;

    (* anyconst *) reg [127:0] pk_seed;
    (* anyconst *) reg [255:0] request_address;
    (* anyconst *) reg [255:0] request_pair;
    (* anyconst *) reg [7:0] source_byte;
    (* anyseq *) reg [31:0] source_word;

    wire req_valid = !request_sent;
    wire req_ready;
    wire [1:0] req_kind = 2'(KIND);
    wire [1:0] req_src_sel = (KIND >= 2) ? 2'd1 : 2'd3;
    wire [15:0] req_src_addr = 16'd0;
    wire [15:0] req_count = 16'(COUNT);
    wire src_rd_en;
    wire [1:0] src_rd_sel;
    wire [15:0] src_rd_addr;
    wire src_valid = source_valid_reg;
    wire shake_in_valid;
    wire shake_in_ready = (ready_phase != 2'd0);
    wire [63:0] shake_in_data;
    wire [3:0] shake_in_bytes;
    wire shake_in_last;
    wire shake_bulk_valid;
    wire shake_bulk_ready = ready_phase[1];
    wire [639:0] shake_bulk_lanes;
    wire [6:0] shake_bulk_bytes;
    wire shake_out_valid = shake_output_valid_reg;
    wire [255:0] shake_out = 256'd0;
    wire rsp_valid;
    wire [127:0] rsp_node;

    initial assume (!rst_n);

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    thash #(.RPC(1), .SHARED_SHAKE(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_ready(req_ready),
        .req_kind(req_kind), .req_adrs(request_address),
        .req_src_sel(req_src_sel), .req_src_addr(req_src_addr),
        .req_count(req_count), .pk_seed(pk_seed), .req_pair(request_pair),
        .src_rd_en(src_rd_en), .src_rd_sel(src_rd_sel), .src_rd_addr(src_rd_addr),
        .src_valid(src_valid), .src_byte(source_byte), .src_word(source_word),
        .shake_in_valid(shake_in_valid), .shake_in_ready(shake_in_ready),
        .shake_in_data(shake_in_data), .shake_in_bytes(shake_in_bytes),
        .shake_in_last(shake_in_last),
        .shake_bulk_valid(shake_bulk_valid), .shake_bulk_ready(shake_bulk_ready),
        .shake_bulk_lanes(shake_bulk_lanes), .shake_bulk_bytes(shake_bulk_bytes),
        .shake_out_valid(shake_out_valid), .shake_out(shake_out),
        .rsp_valid(rsp_valid), .rsp_node(rsp_node)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            request_sent <= 1'b0;
            outstanding <= 1'b0;
            response_seen <= 1'b0;
            ready_phase <= 2'd0;
            source_valid_reg <= 1'b0;
            shake_output_valid_reg <= 1'b0;
            shake_output_delay <= 2'd0;
            shake_bytes <= 16'd0;
            shake_last_count <= 2'd0;
            request_age <= 13'd0;
            past_valid <= 1'b0;
        end else begin
            ready_phase <= ready_phase + 1'b1;
            source_valid_reg <= src_rd_en;
            shake_output_valid_reg <= 1'b0;

            if (shake_output_delay != 0) begin
                if (shake_output_delay == 1) begin
                    shake_output_delay <= 2'd0;
                    shake_output_valid_reg <= 1'b1;
                end else begin
                    shake_output_delay <= shake_output_delay - 1'b1;
                end
            end

            if (req_valid && req_ready) begin
                assert (!request_sent);
                assert (!outstanding);
                request_sent <= 1'b1;
                outstanding <= 1'b1;
                request_age <= 13'd0;
            end

            if (outstanding && !rsp_valid) begin
                assert (!req_ready);
                assert (request_age < REQUEST_BOUND);
                request_age <= request_age + 1'b1;
            end
            if (rsp_valid) begin
                assert (outstanding);
                assert (!response_seen);
                assert (shake_last_count == 1);
                assert (shake_bytes == TOTAL_BYTES);
                response_seen <= 1'b1;
                outstanding <= 1'b0;
            end

            if (past_valid && $past(shake_in_valid && !shake_in_ready)) begin
                assert (shake_in_valid);
                assert (shake_in_data == $past(shake_in_data));
                assert (shake_in_bytes == $past(shake_in_bytes));
                assert (shake_in_last == $past(shake_in_last));
            end
            if (past_valid && $past(shake_bulk_valid && !shake_bulk_ready)) begin
                assert (shake_bulk_valid);
                assert (shake_bulk_lanes == $past(shake_bulk_lanes));
                assert (shake_bulk_bytes == $past(shake_bulk_bytes));
            end

            if (shake_in_valid && shake_in_ready) begin
                shake_bytes <= shake_bytes + shake_in_bytes;
                if (shake_in_last) begin
                    shake_last_count <= shake_last_count + 1'b1;
                    assert (shake_bytes + shake_in_bytes == TOTAL_BYTES);
                    shake_output_delay <= 2'd2;
                end
            end

            if (shake_bulk_valid && shake_bulk_ready) begin
                assert (KIND < 2);
                assert (shake_bulk_bytes == TOTAL_BYTES);
                assert (shake_bytes + shake_bulk_bytes == TOTAL_BYTES);
                shake_bytes <= shake_bytes + shake_bulk_bytes;
                shake_last_count <= shake_last_count + 1'b1;
                shake_output_delay <= 2'd2;
            end

            if (src_rd_en) begin
                assert (src_rd_sel == 2'd1);
                assert (src_rd_addr < 16'd1024);
                assert (src_rd_addr < req_count);
            end

            assert (shake_last_count <= 1);
            assert (!(rsp_valid && !request_sent));
            cover (rsp_valid && shake_last_count == 1 && shake_bytes == TOTAL_BYTES);
            cover ((KIND < 2) ? (shake_bulk_valid && shake_bulk_ready)
                              : (shake_in_valid && shake_in_ready));
            cover ((KIND < 2) ? (shake_bulk_valid && !shake_bulk_ready)
                              : (shake_in_valid && !shake_in_ready));
            past_valid <= 1'b1;
        end
    end
endmodule
