module scratch_ram #(
    // 0 = block RAM, 1 = distributed RAM, 2 = registers.
    parameter integer RAM_STYLE = 0
) (
    input  logic       clk,
    input  logic       wr_en,
    input  logic [7:0] wr_addr,
    input  logic [31:0] wr_data,
    input  logic [7:0] rd_addr,
    output logic [31:0] rd_data
);
    // 56 words hold FORS roots; 140 words hold 35 WOTS+ chain ends.
    generate
        if (RAM_STYLE == 0) begin : G_BLOCK
            (* ram_style = "block", syn_ramstyle = "block_ram" *) logic [31:0] mem [0:255];
            always_ff @(posedge clk) begin
                if (wr_en)
                    mem[wr_addr] <= wr_data;
                rd_data <= mem[rd_addr];
            end
        end else if (RAM_STYLE == 1) begin : G_DISTRIBUTED
            (* ram_style = "distributed", syn_ramstyle = "distributed_ram" *) logic [31:0] mem [0:255];
            always_ff @(posedge clk) begin
                if (wr_en)
                    mem[wr_addr] <= wr_data;
                rd_data <= mem[rd_addr];
            end
        end else begin : G_REGISTERS
            (* ram_style = "registers", syn_ramstyle = "registers" *) logic [31:0] mem [0:255];
            always_ff @(posedge clk) begin
                if (wr_en)
                    mem[wr_addr] <= wr_data;
                rd_data <= mem[rd_addr];
            end
        end
    endgenerate
endmodule
