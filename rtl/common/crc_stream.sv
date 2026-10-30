// Portable CRC/FCS, wire bit 0 first. Contract: docs/RTL_CRC.md.
module crc_stream #(
  parameter int CRC_WIDTH = 32,
  parameter int WORD_BITS = 8,
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst,
  input logic cfg_valid,
  output logic cfg_ready, configured,
  input logic [1:0] cfg_mode,
  input logic [CRC_WIDTH-1:0] cfg_poly, cfg_init, cfg_xorout,
  input logic cfg_reflected, cfg_refout,
  input logic s_valid, s_last,
  output logic s_ready,
  input logic [WORD_BITS-1:0] s_data,
  input logic [5:0] s_nbits,
  output logic m_valid, m_last,
  input logic m_ready,
  output logic [WORD_BITS-1:0] m_data,
  output logic [5:0] m_nbits,
  output logic [CRC_WIDTH-1:0] m_crc,
  output logic m_ok, error
);
  initial begin
    if (CRC_WIDTH < 1 || CRC_WIDTH > 32) $fatal(1, "CRC_WIDTH must be 1..32");
    if (WORD_BITS != 1 && WORD_BITS != 8 && WORD_BITS != 32)
      $fatal(1, "WORD_BITS must be 1, 8 or 32");
  end
  wire reset_now = rst == RESET_ACTIVE;
  logic [1:0] mode;
  logic [CRC_WIDTH-1:0] poly, init_crc, xorout, state, tail;
  logic reflected, refout, in_frame, emitting, halted, o_valid;
  logic [5:0] fill, remaining;
  logic [CRC_WIDTH-1:0] fcs_shift, final_crc;
  logic [WORD_BITS-1:0] o_data;
  logic [5:0] o_nbits;
  logic o_last, o_ok;
  logic [CRC_WIDTH-1:0] o_crc;
  wire ce = !o_valid || m_ready;
  assign cfg_ready = !reset_now && !halted && !in_frame && !emitting && !o_valid;
  assign s_ready = !reset_now && configured && !halted && !emitting && ce &&
                   (in_frame || !o_valid) && !(cfg_valid && cfg_ready);
  assign m_valid = !reset_now && o_valid;
  assign m_data = o_data;
  assign m_nbits = o_nbits;
  assign m_last = o_last;
  assign m_crc = o_crc;
  assign m_ok = o_ok;

  function automatic logic [CRC_WIDTH-1:0] reverse_crc(input logic [CRC_WIDTH-1:0] v);
    for (int j=0; j<CRC_WIDTH; j++) reverse_crc[j] = v[CRC_WIDTH-1-j];
  endfunction
  function automatic logic [CRC_WIDTH-1:0] step_crc(
    input logic [CRC_WIDTH-1:0] v, input logic b);
    logic feedback;
    feedback = (reflected ? v[0] : v[CRC_WIDTH-1]) ^ b;
    return (reflected ? v >> 1 : v << 1) ^ (feedback ? poly : {CRC_WIDTH{1'b0}});
  endfunction

  logic [CRC_WIDTH-1:0] next_state, next_tail, result_crc, expected_tail;
  logic [5:0] next_fill, emit_bits;
  logic [WORD_BITS-1:0] emit_data;
  logic bad_word, check_ok;
  always_comb begin
    next_state = in_frame ? state : init_crc;
    next_tail = in_frame ? tail : '0;
    next_fill = in_frame ? fill : 6'd0;
    bad_word = s_nbits > 6'(WORD_BITS) ||
               (s_nbits < 6'(WORD_BITS) && !s_last) ||
               (s_nbits == 0 && (in_frame || !s_last)) ||
               ((s_data >> s_nbits) != 0);
    for (int j=0; j<WORD_BITS; j++) begin
      if (j < int'(s_nbits)) begin
        if (mode == 2) begin
          if (next_fill == 6'(CRC_WIDTH))
            next_state = step_crc(next_state, next_tail[CRC_WIDTH-1]);
          else next_fill = next_fill + 1'b1;
          next_tail = (next_tail << 1) | CRC_WIDTH'(s_data[j]);
        end else next_state = step_crc(next_state, s_data[j]);
      end
    end
    result_crc = (refout ? reverse_crc(next_state) : next_state) ^ xorout;
    expected_tail = reflected ? reverse_crc(result_crc) : result_crc;
    check_ok = next_fill == 6'(CRC_WIDTH) && next_tail == expected_tail;
    emit_bits = remaining > 6'(WORD_BITS) ? 6'(WORD_BITS) : remaining;
    emit_data = '0;
    for (int j=0; j<WORD_BITS; j++)
      if (j < int'(emit_bits)) emit_data[j] = 1'(fcs_shift >> j);
  end

  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; halted <= 0;
      in_frame <= 0; emitting <= 0; o_valid <= 0;
      fill <= 0; remaining <= 0;
    end else begin
      if (ce) o_valid <= 0;
      if (cfg_valid && cfg_ready) begin
        if (cfg_mode == 3) begin error <= 1; halted <= 1; configured <= 0; end
        else begin
          mode <= cfg_mode; poly <= cfg_poly; init_crc <= cfg_init; xorout <= cfg_xorout;
          reflected <= cfg_reflected; refout <= cfg_refout; configured <= 1;
        end
      end
      if (s_valid && s_ready) begin
        if (bad_word) begin error <= 1; halted <= 1; configured <= 0; in_frame <= 0; end
        else begin
          state <= next_state; tail <= next_tail; fill <= next_fill;
          in_frame <= !s_last;
          if (mode != 0 && s_nbits != 0 || mode == 0 && s_last || mode == 2 && s_last) begin
            o_valid <= 1; o_data <= mode == 0 ? {WORD_BITS{1'b0}} : s_data;
            o_nbits <= mode == 0 ? 6'd0 : s_nbits;
            o_last <= s_last && mode != 1;
            o_crc <= s_last && mode != 1 ? result_crc : {CRC_WIDTH{1'b0}};
            o_ok <= s_last && mode != 1 && (mode != 2 || check_ok);
          end
          if (s_last && mode == 2 && !check_ok) error <= 1;
          if (s_last && mode == 1) begin
            emitting <= 1; remaining <= 6'(CRC_WIDTH); final_crc <= result_crc;
            // fcs_shift bit0 is the next wire bit for either register orientation.
            fcs_shift <= reflected ? result_crc : reverse_crc(result_crc);
          end
        end
      end
      if (emitting && ce) begin
        o_valid <= 1; o_data <= emit_data; o_nbits <= emit_bits;
        o_last <= remaining == emit_bits;
        o_crc <= remaining == emit_bits ? final_crc : {CRC_WIDTH{1'b0}};
        o_ok <= remaining == emit_bits;
        fcs_shift <= fcs_shift >> emit_bits;
        remaining <= remaining - emit_bits;
        if (remaining == emit_bits) emitting <= 0;
      end
    end
  end
endmodule
