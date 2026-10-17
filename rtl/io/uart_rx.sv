module uart_rx #(
    parameter integer CLKS_PER_BIT = 434
) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       rx,
    output logic       byte_valid,
    output logic [7:0] byte_data,
    output logic       framing_error
);
    localparam integer COUNT_W = (CLKS_PER_BIT < 2) ? 1 : $clog2(CLKS_PER_BIT + 1);
    typedef enum logic [1:0] {ST_IDLE, ST_START, ST_DATA, ST_STOP} state_t;

    state_t state;
    logic rx_meta;
    logic rx_sync;
    logic [COUNT_W-1:0] baud_count;
    logic [2:0] bit_index;
    logic [7:0] shift_reg;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_meta <= 1'b1;
            rx_sync <= 1'b1;
            state <= ST_IDLE;
            baud_count <= '0;
            bit_index <= '0;
            shift_reg <= '0;
            byte_valid <= 1'b0;
            byte_data <= '0;
            framing_error <= 1'b0;
        end else begin
            rx_meta <= rx;
            rx_sync <= rx_meta;
            byte_valid <= 1'b0;
            framing_error <= 1'b0;

            case (state)
                ST_IDLE: begin
                    if (!rx_sync) begin
                        baud_count <= COUNT_W'((CLKS_PER_BIT / 2) - 1);
                        state <= ST_START;
                    end
                end

                ST_START: begin
                    if (baud_count == 0) begin
                        if (!rx_sync) begin
                            baud_count <= COUNT_W'(CLKS_PER_BIT - 1);
                            bit_index <= '0;
                            state <= ST_DATA;
                        end else begin
                            state <= ST_IDLE;
                        end
                    end else begin
                        baud_count <= baud_count - 1'b1;
                    end
                end

                ST_DATA: begin
                    if (baud_count == 0) begin
                        shift_reg[bit_index] <= rx_sync;
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
                    if (baud_count == 0) begin
                        if (rx_sync) begin
                            byte_data <= shift_reg;
                            byte_valid <= 1'b1;
                        end else begin
                            framing_error <= 1'b1;
                        end
                        state <= ST_IDLE;
                    end else begin
                        baud_count <= baud_count - 1'b1;
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule
