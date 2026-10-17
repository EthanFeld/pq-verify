module keccak_round #(
    parameter integer LUT4_MAP = 0
) (
    input  logic [1599:0] state_in,
    input  logic [4:0]    round_idx,
    output logic [1599:0] state_out
);
    logic [63:0] rc;

    function automatic logic [63:0] rol64(
        input logic [63:0] value,
        input integer amount
    );
        begin
            if (amount == 0)
                rol64 = value;
            else
                rol64 = (value << amount) | (value >> (64 - amount));
        end
    endfunction

    function automatic integer rho_offset(input integer lane_idx);
        begin
            case (lane_idx)
                0: rho_offset = 0;
                1: rho_offset = 1;
                2: rho_offset = 62;
                3: rho_offset = 28;
                4: rho_offset = 27;
                5: rho_offset = 36;
                6: rho_offset = 44;
                7: rho_offset = 6;
                8: rho_offset = 55;
                9: rho_offset = 20;
                10: rho_offset = 3;
                11: rho_offset = 10;
                12: rho_offset = 43;
                13: rho_offset = 25;
                14: rho_offset = 39;
                15: rho_offset = 41;
                16: rho_offset = 45;
                17: rho_offset = 15;
                18: rho_offset = 21;
                19: rho_offset = 8;
                20: rho_offset = 18;
                21: rho_offset = 2;
                22: rho_offset = 61;
                23: rho_offset = 56;
                24: rho_offset = 14;
                default: rho_offset = 0;
            endcase
        end
    endfunction

    function automatic logic [63:0] round_constant(input logic [4:0] index);
        begin
            case (index)
                0: round_constant = 64'h0000000000000001;
                1: round_constant = 64'h0000000000008082;
                2: round_constant = 64'h800000000000808a;
                3: round_constant = 64'h8000000080008000;
                4: round_constant = 64'h000000000000808b;
                5: round_constant = 64'h0000000080000001;
                6: round_constant = 64'h8000000080008081;
                7: round_constant = 64'h8000000000008009;
                8: round_constant = 64'h000000000000008a;
                9: round_constant = 64'h0000000000000088;
                10: round_constant = 64'h0000000080008009;
                11: round_constant = 64'h000000008000000a;
                12: round_constant = 64'h000000008000808b;
                13: round_constant = 64'h800000000000008b;
                14: round_constant = 64'h8000000000008089;
                15: round_constant = 64'h8000000000008003;
                16: round_constant = 64'h8000000000008002;
                17: round_constant = 64'h8000000000000080;
                18: round_constant = 64'h000000000000800a;
                19: round_constant = 64'h800000008000000a;
                20: round_constant = 64'h8000000080008081;
                21: round_constant = 64'h8000000000008080;
                22: round_constant = 64'h0000000080000001;
                23: round_constant = 64'h8000000080008008;
                default: round_constant = 64'h0;
            endcase
        end
    endfunction

    assign rc = round_constant(round_idx);
    generate
      if (LUT4_MAP != 0) begin : G_LUT4
        logic [63:0] c4 [0:4];
        logic [63:0] c [0:4];
        logic [63:0] theta [0:24];
        logic [63:0] b [0:24];
        for (genvar x = 0; x < 5; x = x + 1) begin : G_COLUMN
            for (genvar bit_index = 0; bit_index < 64; bit_index = bit_index + 1) begin : G_PARITY
                // Five-input column parity takes two LUTs. Explicit cuts
                // prevent the mapper from choosing wide LUT mux chains.
                keccak_lut4 #(.INIT(16'h6996)) u_xor4 (
                    .i({
                    state_in[(x + 15) * 64 + bit_index],
                    state_in[(x + 10) * 64 + bit_index],
                    state_in[(x + 5) * 64 + bit_index],
                    state_in[x * 64 + bit_index]
                    }), .o(c4[x][bit_index])
                );
                keccak_lut4 #(.INIT(16'h6666)) u_xor2 (
                    .i({2'b00, state_in[(x + 20) * 64 + bit_index], c4[x][bit_index]}),
                    .o(c[x][bit_index])
                );
            end
            for (genvar y = 0; y < 5; y = y + 1) begin : G_LANE
                localparam integer LANE = x + 5 * y;
                for (genvar bit_index = 0; bit_index < 64; bit_index = bit_index + 1) begin : G_THETA
                    // Fuse A xor C[x-1] xor rol(C[x+1], 1) in one LUT.
                    keccak_lut4 #(.INIT(16'h9696)) u_theta (
                        .i({1'b0,
                        state_in[LANE * 64 + bit_index],
                        c[(x + 4) % 5][bit_index],
                        c[(x + 1) % 5][(bit_index + 63) % 64]
                        }), .o(theta[LANE][bit_index])
                    );
                end
                assign b[y + 5 * ((2 * x + 3 * y) % 5)] =
                    rol64(theta[LANE], rho_offset(LANE));
                for (genvar bit_index = 0; bit_index < 64; bit_index = bit_index + 1) begin : G_CHI
                    // I0 xor ((not I1) and I2) xor I3, including iota.
                    keccak_lut4 #(.INIT(16'h659a)) u_chi (
                        .i({(LANE == 0) ? rc[bit_index] : 1'b0,
                            b[((x + 2) % 5) + 5 * y][bit_index],
                            b[((x + 1) % 5) + 5 * y][bit_index], b[LANE][bit_index]}),
                        .o(state_out[LANE * 64 + bit_index])
                    );
                end
            end
        end
      end else begin : G_GENERIC
        logic [63:0] a [0:24];
        logic [63:0] b [0:24];
        logic [63:0] c [0:4];
        logic [63:0] d [0:4];
        integer x;
        integer y;
        integer lane;
        always_comb begin
            for (lane = 0; lane < 25; lane = lane + 1)
                a[lane] = state_in[lane * 64 +: 64];
            for (x = 0; x < 5; x = x + 1)
                c[x] = a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20];
            for (x = 0; x < 5; x = x + 1)
                d[x] = c[(x + 4) % 5] ^ rol64(c[(x + 1) % 5], 1);
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x + 5 * y] = a[x + 5 * y] ^ d[x];
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    b[y + 5 * ((2 * x + 3 * y) % 5)] =
                        rol64(a[x + 5 * y], rho_offset(x + 5 * y));
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x + 5 * y] = b[x + 5 * y] ^
                        ((~b[((x + 1) % 5) + 5 * y]) & b[((x + 2) % 5) + 5 * y]);
            a[0] = a[0] ^ rc;
            for (lane = 0; lane < 25; lane = lane + 1)
                state_out[lane * 64 +: 64] = a[lane];
        end
      end
    endgenerate
endmodule

// One truth table is used by simulation and native Gowin synthesis.
/* verilator lint_off DECLFILENAME */
module keccak_lut4 #(
    parameter logic [15:0] INIT = 16'h0000
) (
    input logic [3:0] i,
    output logic o
);
`ifdef PQ_GOWIN_LUT4
    LUT4 #(.INIT(INIT)) u_lut (.I0(i[0]), .I1(i[1]), .I2(i[2]), .I3(i[3]), .F(o));
`else
    assign o = INIT[i];
`endif
endmodule
/* verilator lint_on DECLFILENAME */
