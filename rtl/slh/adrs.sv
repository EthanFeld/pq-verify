module adrs (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         set_layer,
    input  logic [31:0]  layer_value,
    input  logic         set_tree,
    input  logic [95:0]  tree_value,
    input  logic         set_type_and_clear,
    input  logic [31:0]  type_value,
    input  logic         set_keypair,
    input  logic [31:0]  keypair_value,
    input  logic         set_chain,
    input  logic         set_tree_height,
    input  logic [31:0]  word6_value,
    input  logic         set_hash,
    input  logic         set_tree_index,
    input  logic [31:0]  word7_value,
    output logic [255:0] address
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            address <= '0;
        end else if (set_type_and_clear) begin
            address[127:96] <= type_value;
            address[95:0] <= '0;
        end else if (set_layer) begin
            address[255:224] <= layer_value;
        end else if (set_tree) begin
            address[223:128] <= tree_value;
        end else if (set_keypair) begin
            address[95:64] <= keypair_value;
        end else if (set_chain || set_tree_height) begin
            address[63:32] <= word6_value;
        end else if (set_hash || set_tree_index) begin
            address[31:0] <= word7_value;
        end
    end
endmodule
