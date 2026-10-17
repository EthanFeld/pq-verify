module cmd_ctrl #(
    parameter integer CLKS_PER_BIT = 434
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          uart_rx_pin,
    output logic          uart_tx_pin,

    output logic          verify_start,
    input  logic          verify_start_ready,
    output logic          pure_mode,
    output logic [7:0]    ctx_len,
    output logic          ctx_valid,
    input  logic          ctx_ready,
    output logic [7:0]    ctx_byte,
    output logic          msg_valid,
    input  logic          msg_ready,
    output logic [7:0]    msg_byte,
    output logic          msg_last,

    output logic [127:0]  pk_seed,
    output logic [127:0]  pk_root,
    output logic          sig_load_en,
    output logic [10:0]   sig_load_addr,
    output logic [31:0]   sig_load_data,
    input  logic          sig_load_ready,

    input  logic          verify_done,
    input  logic          verify_valid,
    input  logic [31:0]   verify_cycles,
    input  logic [15:0]   verify_perms
);
    localparam logic [7:0] SYNC_REQ = 8'hA5;
    localparam logic [7:0] SYNC_RSP = 8'h5A;
    localparam logic [7:0] CMD_PING = 8'h01;
    localparam logic [7:0] CMD_LOAD_PK = 8'h02;
    localparam logic [7:0] CMD_LOAD_SIG = 8'h03;
    localparam logic [7:0] CMD_VERIFY = 8'h04;
    localparam logic [7:0] STATUS_OK = 8'h00;
    localparam logic [7:0] STATUS_BAD_CRC = 8'h01;
    localparam logic [7:0] STATUS_BAD_LENGTH = 8'h02;
    localparam logic [7:0] STATUS_BUSY = 8'h03;
    localparam logic [31:0] PK_BYTES = 32'd32;
    localparam logic [31:0] SIG_BYTES = 32'd7856;

    typedef enum logic [2:0] {
        P_SYNC,
        P_CMD,
        P_LEN0,
        P_LEN1,
        P_LEN2,
        P_LEN3,
        P_PAYLOAD,
        P_CRC
    } parser_state_t;

    parser_state_t parser_state;
    logic [7:0] rx_byte;
    logic rx_byte_valid;
    logic rx_framing_error;
    logic [7:0] crc_value;
    logic [7:0] crc_next;
    logic [7:0] command;
    logic [31:0] frame_length;
    logic [31:0] payload_remaining;
    // Largest indexed payload is the 7,856-byte signature. VERIFY stops
    // counting once its context and message-length prefix has been consumed.
    logic [12:0] payload_index;
    logic [23:0] message_length;
    logic [31:0] message_remaining;
    logic [1:0] message_length_byte;
    logic [7:0] verify_mode_reg;
    logic [7:0] verify_ctx_len_reg;
    logic frame_bad_length;
    logic frame_busy;
    logic pk_loaded;
    logic sig_loaded;
    logic verify_started;
    logic core_busy;
    logic core_done_seen;
    logic wait_verify_response;
    logic [7:0] verify_frame_status;
    logic saved_verify_valid;
    logic [31:0] saved_verify_cycles;
    logic [15:0] saved_verify_perms;
    logic ctx_pending;
    logic [7:0] ctx_byte_reg;
    logic msg_pending;
    logic [7:0] msg_byte_reg;
    logic msg_last_reg;
    logic msg_end_pending;
    logic [23:0] sig_payload_word;
    logic [10:0] sig_word_index;

    logic [7:0] tx_byte;
    logic tx_byte_ready;
    logic [7:0] response_mem [0:9];
    logic [3:0] response_length;
    logic [3:0] response_index;
    logic response_pending;
    logic queue_response;
    logic [1:0] response_kind;
    logic [7:0] response_command;
    logic [7:0] response_status;
    logic response_valid_value;
    logic [31:0] response_cycles_value;
    logic [15:0] response_perms_value;
    logic [7:0] computed_status;
    logic crc_matches;

    function automatic logic [7:0] crc8_step(
        input logic [7:0] crc_in,
        input logic [7:0] data
    );
        logic [7:0] value;
        begin
            value = crc_in ^ data;
            for (integer bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                if (value[7])
                    value = {value[6:0], 1'b0} ^ 8'h07;
                else
                    value = {value[6:0], 1'b0};
            end
            crc8_step = value;
        end
    endfunction

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_uart_rx (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx_pin),
        .byte_valid(rx_byte_valid), .byte_data(rx_byte),
        .framing_error(rx_framing_error)
    );

    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_uart_tx (
        .clk(clk), .rst_n(rst_n),
        .byte_valid(response_pending), .byte_ready(tx_byte_ready),
        .byte_data(tx_byte), .tx(uart_tx_pin)
    );

    always_comb begin
        crc_next = crc8_step(crc_value, rx_byte);
        crc_matches = (rx_byte == crc_value);
        if (!crc_matches)
            computed_status = STATUS_BAD_CRC;
        else if (frame_bad_length)
            computed_status = STATUS_BAD_LENGTH;
        else if (frame_busy)
            computed_status = STATUS_BUSY;
        else
            computed_status = STATUS_OK;

        pure_mode = (verify_mode_reg == 8'd1);
        ctx_len = verify_ctx_len_reg;
        ctx_valid = ctx_pending;
        ctx_byte = ctx_byte_reg;
        msg_valid = msg_pending;
        msg_byte = msg_byte_reg;
        msg_last = msg_pending ? msg_last_reg : msg_end_pending;
        tx_byte = response_mem[response_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            parser_state <= P_SYNC;
            crc_value <= '0;
            command <= '0;
            frame_length <= '0;
            payload_remaining <= '0;
            payload_index <= '0;
            message_length <= '0;
            message_remaining <= '0;
            message_length_byte <= '0;
            verify_mode_reg <= '0;
            verify_ctx_len_reg <= '0;
            frame_bad_length <= 1'b0;
            frame_busy <= 1'b0;
            pk_loaded <= 1'b0;
            sig_loaded <= 1'b0;
            verify_started <= 1'b0;
            core_busy <= 1'b0;
            core_done_seen <= 1'b0;
            wait_verify_response <= 1'b0;
            verify_frame_status <= STATUS_OK;
            saved_verify_valid <= 1'b0;
            saved_verify_cycles <= '0;
            saved_verify_perms <= '0;
            ctx_pending <= 1'b0;
            ctx_byte_reg <= '0;
            msg_pending <= 1'b0;
            msg_byte_reg <= '0;
            msg_last_reg <= 1'b0;
            msg_end_pending <= 1'b0;
            sig_payload_word <= '0;
            sig_word_index <= '0;
            verify_start <= 1'b0;
            pk_seed <= '0;
            pk_root <= '0;
            sig_load_en <= 1'b0;
            sig_load_addr <= '0;
            sig_load_data <= '0;
            response_length <= '0;
            response_index <= '0;
            response_pending <= 1'b0;
            queue_response <= 1'b0;
            response_kind <= '0;
            response_command <= '0;
            response_status <= STATUS_OK;
            response_valid_value <= 1'b0;
            response_cycles_value <= '0;
            response_perms_value <= '0;
            for (integer response_i = 0; response_i < 10; response_i = response_i + 1)
                response_mem[response_i] <= '0;
        end else begin
            verify_start <= 1'b0;
            sig_load_en <= 1'b0;
            queue_response <= 1'b0;

            if (ctx_pending && ctx_ready)
                ctx_pending <= 1'b0;
            if (msg_pending && msg_ready) begin
                msg_pending <= 1'b0;
                msg_last_reg <= 1'b0;
            end
            if (msg_end_pending && msg_ready)
                msg_end_pending <= 1'b0;

            if (verify_done) begin
                core_busy <= 1'b0;
                core_done_seen <= 1'b1;
                saved_verify_valid <= verify_valid;
                saved_verify_cycles <= verify_cycles;
                saved_verify_perms <= verify_perms;
                if (wait_verify_response) begin
                    response_kind <= 2'd2;
                    response_command <= CMD_VERIFY;
                    response_status <= verify_frame_status;
                    response_valid_value <= (verify_frame_status == STATUS_OK) && verify_valid;
                    response_cycles_value <= verify_cycles;
                    response_perms_value <= verify_perms;
                    queue_response <= 1'b1;
                    wait_verify_response <= 1'b0;
                    verify_started <= 1'b0;
                end
            end

            if (queue_response) begin
                response_mem[0] <= SYNC_RSP;
                response_mem[1] <= response_command;
                response_mem[2] <= response_status;
                response_index <= 4'd0;
                if ((response_kind == 2'd0) && (response_status == STATUS_OK)) begin
                    response_mem[2] <= 8'h53; // S
                    response_mem[3] <= 8'h4C; // L
                    response_mem[4] <= 8'h48; // H
                    response_mem[5] <= 8'h56; // V
                    response_mem[6] <= 8'd1;
                    response_length <= 4'd7;
                end else if (response_kind == 2'd2) begin
                    response_mem[3] <= response_valid_value ? 8'd1 : 8'd0;
                    response_mem[4] <= response_cycles_value[7:0];
                    response_mem[5] <= response_cycles_value[15:8];
                    response_mem[6] <= response_cycles_value[23:16];
                    response_mem[7] <= response_cycles_value[31:24];
                    response_mem[8] <= response_perms_value[7:0];
                    response_mem[9] <= response_perms_value[15:8];
                    response_length <= 4'd10;
                end else begin
                    response_length <= 4'd3;
                end
                response_pending <= 1'b1;
            end

            if (response_pending && tx_byte_ready) begin
                if (response_index + 1'b1 >= response_length) begin
                    response_pending <= 1'b0;
                    response_index <= '0;
                end else begin
                    response_index <= response_index + 1'b1;
                end
            end

            if (rx_framing_error) begin
                parser_state <= P_SYNC;
                if (verify_started) begin
                    msg_end_pending <= 1'b1;
                    verify_frame_status <= STATUS_BAD_CRC;
                    if (core_done_seen) begin
                        response_kind <= 2'd2;
                        response_command <= CMD_VERIFY;
                        response_status <= STATUS_BAD_CRC;
                        response_valid_value <= 1'b0;
                        response_cycles_value <= saved_verify_cycles;
                        response_perms_value <= saved_verify_perms;
                        queue_response <= 1'b1;
                        verify_started <= 1'b0;
                    end else begin
                        wait_verify_response <= 1'b1;
                    end
                end
            end else if (rx_byte_valid) begin
                case (parser_state)
                    P_SYNC: begin
                        if (rx_byte == SYNC_REQ) begin
                            parser_state <= P_CMD;
                            crc_value <= '0;
                        end
                    end

                    P_CMD: begin
                        command <= rx_byte;
                        crc_value <= crc_next;
                        parser_state <= P_LEN0;
                    end

                    P_LEN0: begin
                        frame_length[7:0] <= rx_byte;
                        crc_value <= crc_next;
                        parser_state <= P_LEN1;
                    end

                    P_LEN1: begin
                        frame_length[15:8] <= rx_byte;
                        crc_value <= crc_next;
                        parser_state <= P_LEN2;
                    end

                    P_LEN2: begin
                        frame_length[23:16] <= rx_byte;
                        crc_value <= crc_next;
                        parser_state <= P_LEN3;
                    end

                    P_LEN3: begin
                        frame_length[31:24] <= rx_byte;
                        payload_remaining <= {rx_byte, frame_length[23:0]};
                        payload_index <= '0;
                        message_length <= '0;
                        message_remaining <= '0;
                        message_length_byte <= '0;
                        crc_value <= crc_next;
                        frame_busy <= core_busy || !sig_load_ready;
                        frame_bad_length <= 1'b0;
                        if (!core_busy) begin
                            verify_started <= 1'b0;
                            core_done_seen <= 1'b0;
                            wait_verify_response <= 1'b0;
                        end
                        // A new load attempt replaces the prior object. Invalidate
                        // before length/CRC validation so a rejected frame cannot
                        // leave stale key or signature state available to VERIFY.
                        if (!(core_busy || !sig_load_ready)) begin
                            if (command == CMD_LOAD_PK)
                                pk_loaded <= 1'b0;
                            if (command == CMD_LOAD_SIG)
                                sig_loaded <= 1'b0;
                        end
                        if ((command == CMD_PING) && ({rx_byte, frame_length[23:0]} != 0))
                            frame_bad_length <= 1'b1;
                        else if ((command == CMD_LOAD_PK)
                            && ({rx_byte, frame_length[23:0]} != PK_BYTES))
                            frame_bad_length <= 1'b1;
                        else if ((command == CMD_LOAD_SIG)
                            && ({rx_byte, frame_length[23:0]} != SIG_BYTES))
                            frame_bad_length <= 1'b1;
                        else if ((command == CMD_VERIFY)
                            && ({rx_byte, frame_length[23:0]} < 32'd6))
                            frame_bad_length <= 1'b1;
                        else if (command > CMD_VERIFY || command == 8'd0)
                            frame_bad_length <= 1'b1;
                        if ({rx_byte, frame_length[23:0]} == 0)
                            parser_state <= P_CRC;
                        else
                            parser_state <= P_PAYLOAD;
                    end

                    P_PAYLOAD: begin
                        crc_value <= crc_next;
                        payload_remaining <= payload_remaining - 1'b1;
                        if ((command != CMD_VERIFY)
                            || (payload_index < (13'd6 + {5'd0, verify_ctx_len_reg})))
                            payload_index <= payload_index + 1'b1;

                        if ((command == CMD_LOAD_PK) && !frame_bad_length && !frame_busy) begin
                            // LOAD_PK frames are validated as exactly 32 bytes, so
                            // the low five index bits select seed/root and byte lane.
                            if (!payload_index[4])
                                pk_seed[127 - {payload_index[3:0], 3'b000} -: 8] <= rx_byte;
                            else
                                pk_root[127 - {payload_index[3:0], 3'b000} -: 8] <= rx_byte;
                            if (payload_index == 0)
                                pk_loaded <= 1'b0;
                        end

                        if ((command == CMD_LOAD_SIG) && !frame_bad_length && !frame_busy) begin
                            case (payload_index[1:0])
                                2'd0: sig_payload_word[23:16] <= rx_byte;
                                2'd1: sig_payload_word[15:8] <= rx_byte;
                                2'd2: sig_payload_word[7:0] <= rx_byte;
                                default: begin
                                    sig_load_en <= 1'b1;
                                    sig_load_addr <= sig_word_index;
                                    sig_load_data <= {sig_payload_word, rx_byte};
                                    sig_word_index <= sig_word_index + 1'b1;
                                end
                            endcase
                            if (payload_index == 0) begin
                                sig_loaded <= 1'b0;
                                sig_word_index <= '0;
                            end
                        end

                        if (command == CMD_VERIFY) begin
                            if (payload_index == 0) begin
                                verify_mode_reg <= rx_byte;
                                if (rx_byte > 8'd1)
                                    frame_bad_length <= 1'b1;
                            end else if (payload_index == 1) begin
                                verify_ctx_len_reg <= rx_byte;
                                if ((verify_mode_reg == 8'd0 && rx_byte != 0)
                                    || (frame_length < (32'd6 + {24'd0, rx_byte}))
                                    || !pk_loaded || !sig_loaded)
                                    frame_bad_length <= 1'b1;
                                if (frame_busy)
                                    frame_busy <= 1'b1;
                                else if (verify_mode_reg <= 8'd1 && pk_loaded && sig_loaded
                                    && (verify_mode_reg != 0 || rx_byte == 0)
                                    && (frame_length >= (32'd6 + {24'd0, rx_byte}))
                                    && verify_start_ready) begin
                                    verify_start <= 1'b1;
                                    verify_started <= 1'b1;
                                    core_busy <= 1'b1;
                                end else if (!verify_start_ready) begin
                                    frame_busy <= 1'b1;
                                end
                            end else if ((payload_index >= 13'd2)
                                && (payload_index < (13'd2 + {5'd0, verify_ctx_len_reg}))) begin
                                if (verify_started) begin
                                    ctx_byte_reg <= rx_byte;
                                    ctx_pending <= 1'b1;
                                end
                            end else if (payload_index < (13'd6 + {5'd0, verify_ctx_len_reg})) begin
                                message_length_byte <= message_length_byte + 1'b1;
                                case (message_length_byte)
                                    2'd0: message_length[7:0] <= rx_byte;
                                    2'd1: message_length[15:8] <= rx_byte;
                                    2'd2: message_length[23:16] <= rx_byte;
                                    default: begin
                                        message_remaining <= {rx_byte, message_length[23:0]};
                                        if (frame_length != (32'd6 + {24'd0, verify_ctx_len_reg}
                                            + {rx_byte, message_length[23:0]}))
                                            frame_bad_length <= 1'b1;
                                        if (({rx_byte, message_length[23:0]} == 0)
                                            && verify_started)
                                            msg_end_pending <= 1'b1;
                                    end
                                endcase
                            end else if ((message_remaining != 0) && verify_started) begin
                                msg_byte_reg <= rx_byte;
                                msg_pending <= 1'b1;
                                msg_last_reg <= (message_remaining == 1)
                                    || (payload_remaining == 1);
                                message_remaining <= message_remaining - 1'b1;
                            end
                        end

                        if ((payload_remaining == 1) && (command == CMD_VERIFY)
                            && verify_started
                            && !((payload_index >= (13'd6 + {5'd0, verify_ctx_len_reg}))
                                && (message_remaining != 0)))
                            msg_end_pending <= 1'b1;

                        if (payload_remaining == 1)
                            parser_state <= P_CRC;
                    end

                    P_CRC: begin
                        parser_state <= P_SYNC;
                        if ((command == CMD_LOAD_PK) && !frame_busy && !frame_bad_length)
                            pk_loaded <= crc_matches;
                        if ((command == CMD_LOAD_SIG) && !frame_busy && !frame_bad_length)
                            sig_loaded <= crc_matches;

                        if (command == CMD_VERIFY) begin
                            verify_frame_status <= computed_status;
                            if (verify_started) begin
                                if (core_done_seen || verify_done) begin
                                    response_kind <= 2'd2;
                                    response_command <= CMD_VERIFY;
                                    response_status <= computed_status;
                                    response_valid_value <= (computed_status == STATUS_OK)
                                        && (verify_done ? verify_valid : saved_verify_valid);
                                    response_cycles_value <= verify_done
                                        ? verify_cycles : saved_verify_cycles;
                                    response_perms_value <= verify_done
                                        ? verify_perms : saved_verify_perms;
                                    queue_response <= 1'b1;
                                    verify_started <= 1'b0;
                                end else begin
                                    wait_verify_response <= 1'b1;
                                end
                            end else begin
                                response_kind <= 2'd2;
                                response_command <= CMD_VERIFY;
                                response_status <= computed_status;
                                response_valid_value <= 1'b0;
                                response_cycles_value <= '0;
                                response_perms_value <= '0;
                                queue_response <= 1'b1;
                            end
                        end else begin
                            response_kind <= (command == CMD_PING) ? 2'd0 : 2'd1;
                            response_command <= command;
                            response_status <= computed_status;
                            response_valid_value <= 1'b0;
                            response_cycles_value <= '0;
                            response_perms_value <= '0;
                            queue_response <= 1'b1;
                        end
                    end

                    default: parser_state <= P_SYNC;
                endcase
            end

            if (verify_done && wait_verify_response) begin
                response_kind <= 2'd2;
                response_command <= CMD_VERIFY;
                response_status <= verify_frame_status;
                response_valid_value <= (verify_frame_status == STATUS_OK) && verify_valid;
                response_cycles_value <= verify_cycles;
                response_perms_value <= verify_perms;
                queue_response <= 1'b1;
                wait_verify_response <= 1'b0;
                verify_started <= 1'b0;
            end
        end
    end
endmodule
