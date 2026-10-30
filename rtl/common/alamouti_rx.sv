// Alamouti decoder (research_core alamouti; bit-exact reference beam_fixed.alamouti).
// Configuration (between transactions): h0 then h1 (Q15, cfg_last on h1); E = |h0|^2 + |h1|^2
// is inverted once (norm_reciprocal) before `configured` rises. A transaction is sample pairs
// (r0, r1) (s_last on the last r1) and gives y0, y1 per pair (m_last on the very last):
//   y0 = (conj(h0) r0 + h1 conj(r1))/E, y1 = (conj(h1) r0 - h0 conj(r1))/E,
// each sum exact (16 products when r1 arrives), then y = sat18(round(sum*R, Z - 15)).
// One sample per clock; the pipeline never stalls and pushes both outputs of a pair into an
// 8-entry FIFO (m_ready backpressure, the pairs in flight are counted).
// error is sticky: E = 0, not exactly two taps, or s_last on an r0.
module alamouti_rx #(
  parameter bit RESET_ACTIVE = 1,
  parameter int SUM_WIDTH = 38,
  parameter int ENERGY_WIDTH = 37,
  parameter int SCALE_WIDTH = 61
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic signed [17:0] cfg_re, cfg_im,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int AW = SUM_WIDTH;
  // Four signed18 products reach +2^36; energy reaches 2^36 unsigned.
  // |sum*R| <= 2^59, rounding adds at most 2^43, so signed61 suffices.
  initial if (SUM_WIDTH<38 || SUM_WIDTH>63 || ENERGY_WIDTH<37 || ENERGY_WIDTH>63 || SCALE_WIDTH<61 || SCALE_WIDTH>96)
    $fatal(1,"[PARAMETER] ALAMOUTI requires SUM_WIDTH=38..63, ENERGY_WIDTH=37..63, SCALE_WIDTH=61..96");
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [17:0] sat18(input logic signed [SCALE_WIDTH-1:0] value, input logic [6:0] shift);
    logic signed [SCALE_WIDTH-1:0] rounded;
    rounded = (value + (SCALE_WIDTH'(1) <<< (shift - 1'b1))) >>> shift;
    if (rounded[SCALE_WIDTH-1:17] != {(SCALE_WIDTH-17){rounded[SCALE_WIDTH-1]}}) return rounded[SCALE_WIDTH-1] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  logic signed [17:0] h0r, h0i, h1r, h1i;
  logic [1:0] count;
  logic [ENERGY_WIDTH-1:0] energy;
  logic norm_start, norm_done, norm_zero, waiting;
  logic [23:0] r;
  logic [6:0] shift;
  norm_reciprocal #(.WIDTH(ENERGY_WIDTH),.RESET_ACTIVE(RESET_ACTIVE)) norm(
    .clk(clk),.rst(rst),.start(norm_start),.energy(energy),.done(norm_done),.zero(norm_zero),.r(r),.shift(shift));
  logic second;                               // the next sample is an r1
  logic signed [17:0] ar, ai;                 // r0 of the pair
  logic [3:0] fifo_count, pending;
  logic [36:0] fifo [0:7];
  logic [2:0] fifo_head, fifo_tail;
  assign cfg_ready = !reset_now && !waiting && pending == '0 && !second;
  assign s_ready = !reset_now && configured && !(cfg_valid && cfg_ready) && {1'b0, fifo_count} + {pending, 1'b0} < 5'd7;
  wire take = s_valid && s_ready;
  wire pop = m_valid && m_ready;
  // Pipeline: p (16 products), s (sums), q (scaled), e (rounded) -> two FIFO entries.
  logic p_valid, p_last, s_valid_q, s_last_q, q_valid, q_last, e_valid, e_last;
  logic signed [35:0] p [0:15];
  logic signed [AW-1:0] y0r, y0i, y1r, y1i;
  logic signed [SCALE_WIDTH-1:0] q0r, q0i, q1r, q1i;
  logic signed [17:0] e0r, e0i, e1r, e1i;
  wire signed [SCALE_WIDTH-1:0] rs = SCALE_WIDTH'($signed({1'b0, r}));
  function automatic logic signed [AW-1:0] sum4(input logic signed [35:0] a, b, c, d);
    return AW'(a) + AW'(b) + AW'(c) + AW'(d);
  endfunction
  assign m_valid = fifo_count != 4'd0;
  assign m_re = fifo[fifo_head][36:19]; assign m_im = fifo[fifo_head][18:1]; assign m_last = fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    if (take && !second) begin ar <= s_re; ai <= s_im; end
    if (take && second) begin
      // r0 = (ar, ai), r1 = (br, bi) = s
      p[0] <= h0r*ar; p[1] <= h0i*ai; p[2] <= h1r*s_re; p[3] <= h1i*s_im;     // y0 re
      p[4] <= h0r*ai; p[5] <= h0i*ar; p[6] <= h1i*s_re; p[7] <= h1r*s_im;     // y0 im: p4 - p5 + p6 - p7
      p[8] <= h1r*ar; p[9] <= h1i*ai; p[10] <= h0r*s_re; p[11] <= h0i*s_im;   // y1 re: p8 + p9 - p10 - p11
      p[12] <= h1r*ai; p[13] <= h1i*ar; p[14] <= h0i*s_re; p[15] <= h0r*s_im; // y1 im: p12 - p13 - p14 + p15
      p_last <= s_last;
    end
    y0r <= sum4(p[0], p[1], p[2], p[3]); y0i <= sum4(p[4], 36'sd0 - p[5], p[6], 36'sd0 - p[7]);
    y1r <= sum4(p[8], p[9], 36'sd0 - p[10], 36'sd0 - p[11]); y1i <= sum4(p[12], 36'sd0 - p[13], 36'sd0 - p[14], p[15]);
    s_last_q <= p_last;
    q0r <= SCALE_WIDTH'(y0r)*rs; q0i <= SCALE_WIDTH'(y0i)*rs; q1r <= SCALE_WIDTH'(y1r)*rs; q1i <= SCALE_WIDTH'(y1i)*rs; q_last <= s_last_q;
    e0r <= sat18(q0r, shift); e0i <= sat18(q0i, shift); e1r <= sat18(q1r, shift); e1i <= sat18(q1i, shift); e_last <= q_last;
    if (reset_now) begin
      configured <= 0; error <= 0; count <= '0; energy <= '0; norm_start <= 0; waiting <= 0; second <= 0;
      p_valid <= 0; s_valid_q <= 0; q_valid <= 0; e_valid <= 0; pending <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
    end else begin
      norm_start <= 0;
      if (cfg_valid && cfg_ready) begin
        configured <= 0; count <= count + 1'b1;
        energy <= (count == '0 ? ENERGY_WIDTH'(0) : energy) + ENERGY_WIDTH'(37'(cfg_re*cfg_re) + 37'(cfg_im*cfg_im));
        if (count == 2'd0) begin h0r <= cfg_re; h0i <= cfg_im; end
        if (count == 2'd1) begin h1r <= cfg_re; h1i <= cfg_im; end
        if (cfg_last) begin
          count <= '0;
          if (count == 2'd1) begin norm_start <= 1; waiting <= 1; end else error <= 1;
        end else if (count == 2'd1) begin error <= 1; count <= '0; end
      end
      if (waiting && (norm_done || norm_zero && !norm_start)) begin
        waiting <= 0;
        if (norm_zero) error <= 1; else configured <= 1;
      end
      if (take) begin second <= !second; if (s_last && !second) error <= 1; end
      p_valid <= take && second; s_valid_q <= p_valid; q_valid <= s_valid_q; e_valid <= q_valid;
      if (e_valid) begin
        fifo[fifo_tail] <= {e0r, e0i, 1'b0}; fifo[3'(fifo_tail + 1'b1)] <= {e1r, e1i, e_last}; fifo_tail <= fifo_tail + 3'd2;
      end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {2'd0, e_valid, 1'b0} - {3'd0, pop};
      pending <= pending + {3'd0, take && second} - {3'd0, e_valid};
    end
  end
endmodule
