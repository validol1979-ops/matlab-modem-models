// OFDM receiver frame front end: cyclic-prefix removal, N-point FFT and output scaling
// (bit-exact reference common/python/ofdm_fixed.py receive(): fft(frame[cp:])*sqrt(n)).
// A frame is exactly N+CP input samples; the first CP are accepted and dropped, the other
// N go to the forward core fft_r2sdf (s_inverse = 0, FFT/N) with s_valid passed through and
// s_last on the N-th forwarded sample. Frame boundaries come from the input counter, so a
// mispositioned s_last only raises the sticky error.
// Formats: input N+CP samples Q15 18-bit, output N symbols Q15 18-bit. The 20-bit core
// output X is scaled by K*2^-SHIFT_RX (K = 46341 for odd LOG2N, 32768 for even,
// SHIFT_RX = 15 - LOG2N/2): operand register (X), product register (X*K), then one register
// that rounds half up by SHIFT_RX and saturates to 18 bits. The three stages and the core
// m_ready share the enable ce = !m_valid || m_ready; m_last travels with the core m_last.
// Latency (m_ready = 1): about (N-1+4*LOG2N) + N + 3 core clocks plus 3 scaling clocks
// from the first forwarded sample of a frame to its first output symbol.
// error is sticky: s_last not on the (N+CP)-th accepted sample, or the core error.
module ofdm_rx #(
  parameter int LOG2N = 5,
  parameter int CP = 8,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_32.mem"
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int CNTW = LOG2N + 1;               // counts N+CP <= 2N samples per frame
  localparam int FRAME = N + CP;
  localparam int K = (LOG2N % 2) != 0 ? 46341 : 32768;
  localparam int SHIFT_RX = 15 - LOG2N/2;
  localparam int RND = 1 << (SHIFT_RX - 1);
  localparam logic [CNTW-1:0] CP_CNT = CNTW'(CP);
  localparam logic [CNTW-1:0] LAST_CNT = CNTW'(FRAME - 1);
  localparam logic signed [36:0] K_MUL = 37'(K);
  wire reset_now = rst == RESET_ACTIVE;

  // Round half up by SHIFT_RX and saturate to +-(2^17 range), [-131072, 131071].
  // |X*K| < 2^34.5 and SHIFT_RX >= 10, so the shifted value fits 28 bits; saturation is a
  // sign-extension check.
  function automatic logic signed [17:0] round_sat(input logic signed [36:0] value);
    logic signed [27:0] rounded;
    rounded = 28'((38'(value) + 38'(RND)) >>> SHIFT_RX);
    if (rounded[27:17] != {11{rounded[27]}}) return rounded[27] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  // Input side: frame counter over N+CP samples, the first CP are dropped.
  logic [CNTW-1:0] cnt;
  logic in_cp;
  generate
    if (CP == 0) begin : g_no_cp
      assign in_cp = 1'b0;
    end else begin : g_cp
      assign in_cp = cnt < CP_CNT;
    end
  endgenerate
  wire at_last = cnt == LAST_CNT;
  wire f_valid = !in_cp && s_valid;
  logic f_ready, f_m_valid, f_m_last, f_error;
  logic signed [19:0] f_m_re, f_m_im;
  wire take = s_valid && s_ready;
  assign s_ready = reset_now ? 1'b0 : in_cp ? 1'b1 : f_ready;

  // Output scaling: operand, product, rounded/saturated registers, one shared enable.
  wire ce = !m_valid || m_ready;

  // m_inverse is tied off: the core is always used forward (s_inverse = 0).
  /* verilator lint_off PINCONNECTEMPTY */
  fft_r2sdf #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) fft (
    .clk(clk),.rst(rst),
    .s_valid(f_valid),.s_last(s_last),.s_inverse(1'b0),
    .s_re(s_re),.s_im(s_im),.s_ready(f_ready),
    .m_valid(f_m_valid),.m_last(f_m_last),.m_inverse(),
    .m_re(f_m_re),.m_im(f_m_im),.m_ready(ce),
    .error(f_error)
  );
  /* verilator lint_on PINCONNECTEMPTY */

  logic signed [19:0] x_re, x_im;
  logic xv, xl;
  logic signed [36:0] p_re, p_im;
  logic pv, pl;
  logic signed [17:0] o_re, o_im;
  logic ov, ol;
  assign m_valid = ov;
  assign m_last = ol;
  assign m_re = o_re;
  assign m_im = o_im;

  always_ff @(posedge clk) begin
    if (reset_now) begin
      cnt <= '0; error <= 0;
      xv <= 0; xl <= 0; pv <= 0; pl <= 0; ov <= 0; ol <= 0;
    end else begin
      if (take) begin
        cnt <= at_last ? '0 : cnt + 1'b1;
        if (s_last != at_last) error <= 1;
      end
      if (f_error) error <= 1;
      if (ce) begin
        x_re <= f_m_re; x_im <= f_m_im; xv <= f_m_valid; xl <= f_m_last;
        p_re <= x_re*K_MUL; p_im <= x_im*K_MUL; pv <= xv; pl <= xl;
        o_re <= round_sat(p_re); o_im <= round_sat(p_im); ov <= pv; ol <= pl;
      end
    end
  end
endmodule
