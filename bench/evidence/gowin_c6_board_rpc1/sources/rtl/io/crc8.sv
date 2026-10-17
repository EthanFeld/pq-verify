module crc8 (
    input  logic [7:0]  data,
    input  logic [7:0]  crc_in,
    output logic [7:0]  crc_out
);
    logic [7:0] value;

    always_comb begin
        value = crc_in ^ data;
        for (integer bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
            if (value[7])
                value = {value[6:0], 1'b0} ^ 8'h07;
            else
                value = {value[6:0], 1'b0};
        end
        crc_out = value;
    end
endmodule
