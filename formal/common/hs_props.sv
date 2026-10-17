// Ready/valid contract checker. Instantiate once per request/read channel and
// include every transaction field in payload so stalled requests stay intact.
module hs_props #(
    parameter integer PAYLOAD_WIDTH = 1,
    parameter integer COVER_STALL = 1
) (
    input logic clk,
    input logic rst_n,
    input logic valid,
    input logic ready,
    input logic [PAYLOAD_WIDTH-1:0] payload
);
    logic stalled;
    logic [PAYLOAD_WIDTH-1:0] held_payload;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            stalled <= 1'b0;
            held_payload <= '0;
        end else begin
            if (stalled) begin
                assert (valid);
                assert (payload == held_payload);
            end

            stalled <= valid && !ready;
            if (valid && !ready)
                held_payload <= payload;

            cover (valid && ready);
            if (COVER_STALL != 0)
                cover (stalled && valid && ready);
        end
    end
endmodule
