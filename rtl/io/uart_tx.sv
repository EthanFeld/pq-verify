module uart_tx #(
    parameter integer CLKS_PER_BIT = 434
) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       byte_valid,
    output logic       byte_ready,
    input  logic [7:0] byte_data,
    output logic       tx
);
    localparam integer COUNT_W = (CLKS_PER_BIT < 2) ? 1 : $clog2(CLKS_PER_BIT + 1);
    typedef enum logic [1:0] {ST_IDLE, ST_START, ST_DATA, ST_STOP} state_t;

    state_t state;
    logic [COUNT_W-1:0] baud_count;
    logic [2:0] bit_index;
    logic [7:0] shift_reg;

    always_comb begin
        byte_ready = (state == ST_IDLE);
        tx = 1'b1;
        case (state)
            ST_START: tx = 1'b0;
            ST_DATA: tx = shift_reg[bit_index];
            default: tx = 1'b1;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            baud_count <= '0;
            bit_index <= '0;
            shift_reg <= '0;
        end else begin
            case (state)
                ST_IDLE: begin
                    if (byte_valid && byte_ready) begin
                        shift_reg <= byte_data;
                        baud_count <= COUNT_W'(CLKS_PER_BIT - 1);
                        state <= ST_START;
                    end
                end

                ST_START: begin
                    if (baud_count == 0) begin
                        baud_count <= COUNT_W'(CLKS_PER_BIT - 1);
                        bit_index <= '0;
                        state <= ST_DATA;
                    end else begin
                        baud_count <= baud_count - 1'b1;
                    end
                end

                ST_DATA: begin
                    if (baud_count == 0) begin
                        baud_count <= COUNT_W'(CLKS_PER_BIT - 1);
                        if (bit_index == 3'd7)
                            state <= ST_STOP;
                        else
                            bit_index <= bit_index + 1'b1;
                    end else begin
                        baud_count <= baud_count - 1'b1;
                    end
                end

                ST_STOP: begin
                    if (baud_count == 0)
                        state <= ST_IDLE;
                    else
                        baud_count <= baud_count - 1'b1;
                end

                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule
