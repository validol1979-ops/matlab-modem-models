// Second-order IIR notch (research_core notch; bit-exact reference oset_fixed.notch).
// Coefficients from the configuration port (one transfer, between transactions): B1 = -2c,
// A1 = 2rc, A2 = -r^2 in 18-bit Q16 (oset_fixed.notch_coefficients designs them). A
// transaction is one Q15 signal (s_last on its last sample) and gives as many outputs; it
// starts from a zero state. Re and im are filtered independently with G = 5 guard bits:
//   X = x << 5, Y[k] = sat25(X[k] + rnd(B1*X[k-1], 16) + X[k-2] + rnd(A2*Y[k-2], 16)
//                          + rnd(A1*Y[k-1], 16)), y = sat18(rnd(Y[k], 5)).
// One sample per clock: stage A forms C = (everything but the A1 term) * 2^16 + 2^15 (it
// takes Y[k-2], which is already known), stage L closes the loop Y[k] = sat25((A1*Y[k-1] +
// C) >>> 16) (one multiply-add, the DSP's C input), then the output register. Everything
// advances with ce = !m_valid || m_ready.
module notch_iir #(
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic signed [17:0] cfg_b1, cfg_a1, cfg_a2,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready
);
  wire reset_now = rst == RESET_ACTIVE;
  localparam logic signed [24:0] Y_MAX = 25'sd16777215;

  function automatic logic signed [24:0] sat25(input logic signed [45:0] value);
    logic signed [29:0] shifted;
    shifted = 30'(value >>> 16);
    if (shifted[29:24] != {6{shifted[29]}}) return shifted[29] ? 25'sh1000000 : Y_MAX;
    return shifted[24:0];
  endfunction
  function automatic logic signed [17:0] sat18(input logic signed [24:0] value);
    // rnd(value,5) must be formed in 26 bits: value + 16 at 25 bits wraps before the
    // shift when value is at the positive state rail (2^24-1), turning the clamp into
    // the NEGATIVE output rail (demonstrated by the oset stress vectors, case4).
    logic signed [25:0] rounded;
    rounded = (26'(value) + 26'sd16) >>> 5;
    if (rounded[25:17] != {9{rounded[25]}}) return rounded[25] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction
  // rnd(c*v, 16) for an 18-bit coefficient and a 25-bit value.
  function automatic logic signed [27:0] term(input logic signed [17:0] c, input logic signed [24:0] v);
    return 28'((43'(c)*43'(v) + 43'sd32768) >>> 16);
  endfunction

  logic signed [17:0] b1, a1, a2;
  logic in_tx;
  logic [1:0] pos;                       // index of the next sample, saturating at 2
  logic signed [24:0] x1_re, x1_im, x2_re, x2_im, y1_re, y1_im, y2_re, y2_im;
  logic a_valid, a_first, a_last, o_valid;
  logic signed [45:0] c_re, c_im;
  logic signed [17:0] o_re, o_im;
  logic o_last;
  wire ce = !o_valid || m_ready;
  assign cfg_ready = !reset_now && !in_tx && !a_valid && !o_valid;
  assign s_ready = !reset_now && configured && ce;
  wire take = s_valid && s_ready;
  // Stage A operands: missing history is zero; Y[k-2] is y1 while L still holds sample k-1.
  wire signed [24:0] xk_re = 25'(s_re) <<< 5, xk_im = 25'(s_im) <<< 5;
  wire signed [24:0] xa_re = pos >= 2'd1 ? x1_re : 25'sd0, xa_im = pos >= 2'd1 ? x1_im : 25'sd0;
  wire signed [24:0] xb_re = pos == 2'd2 ? x2_re : 25'sd0, xb_im = pos == 2'd2 ? x2_im : 25'sd0;
  wire signed [24:0] yb_re = pos == 2'd2 ? (a_valid ? y1_re : y2_re) : 25'sd0;
  wire signed [24:0] yb_im = pos == 2'd2 ? (a_valid ? y1_im : y2_im) : 25'sd0;
  wire signed [29:0] s_re_sum = 30'(xk_re) + 30'(term(b1, xa_re)) + 30'(xb_re) + 30'(term(a2, yb_re));
  wire signed [29:0] s_im_sum = 30'(xk_im) + 30'(term(b1, xa_im)) + 30'(xb_im) + 30'(term(a2, yb_im));
  // Stage L: the previous output of this transaction (zero for its first sample).
  wire signed [24:0] yp_re = a_first ? 25'sd0 : y1_re, yp_im = a_first ? 25'sd0 : y1_im;
  wire signed [24:0] yn_re = sat25(46'(a1)*46'(yp_re) + c_re), yn_im = sat25(46'(a1)*46'(yp_im) + c_im);
  assign m_valid = o_valid; assign m_last = o_last; assign m_re = o_re; assign m_im = o_im;

  always_ff @(posedge clk) begin
    if (ce) begin
      if (take) begin
        x2_re <= x1_re; x2_im <= x1_im; x1_re <= xk_re; x1_im <= xk_im;
        c_re <= (46'(s_re_sum) <<< 16) + 46'sd32768; c_im <= (46'(s_im_sum) <<< 16) + 46'sd32768;
        a_first <= pos == 2'd0; a_last <= s_last;
      end
      if (a_valid) begin
        y2_re <= yp_re; y2_im <= yp_im; y1_re <= yn_re; y1_im <= yn_im;
        o_re <= sat18(yn_re); o_im <= sat18(yn_im); o_last <= a_last;
      end
    end
    if (reset_now) begin
      configured <= 0; in_tx <= 0; pos <= '0; a_valid <= 0; o_valid <= 0;
    end else begin
      if (cfg_valid && cfg_ready) begin b1 <= cfg_b1; a1 <= cfg_a1; a2 <= cfg_a2; configured <= 1; end
      if (ce) begin a_valid <= take; o_valid <= a_valid; end
      if (take) begin
        in_tx <= !s_last; pos <= s_last ? 2'd0 : pos == 2'd2 ? 2'd2 : pos + 1'b1;
      end
    end
  end
endmodule
