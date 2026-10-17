module sig_ram (
    input  logic        clk,
    input  logic        wr_en,
    input  logic [10:0] wr_addr,
    input  logic [31:0] wr_data,
    input  logic [10:0] rd_addr,
    output logic [31:0] rd_data
);
    (* ram_style = "block" *) logic [31:0] mem [0:2047];

    always_ff @(posedge clk) begin
        if (wr_en)
            mem[wr_addr] <= wr_data;
        rd_data <= mem[rd_addr];
    end
endmodule
