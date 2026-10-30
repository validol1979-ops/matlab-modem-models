// Beamformer y = X conj(a) / (a^H a) (research_core beamform; bit-exact reference
// beam_fixed.beamform). Configuration (between transactions): the M <= 2^LOG2M Q15 weights,
// one per transfer (cfg_last on the last); the energy E is summed exactly and inverted once
// (norm_reciprocal, about 70 clocks) before `configured` rises. A transaction is whole
// snapshots of M Q15 samples (channel 0..M-1, s_last on the last sample) and gives one Q15
// output per snapshot (m_last on the last): acc = sum_m x_m conj(a_m) exactly (one complex
// multiply-accumulate per sample, one sample per clock), y = sat18(round(acc*R, Z - 15)).
// The pipeline never stalls; an 8-entry FIFO with the snapshots in flight gives m_ready
// backpressure. error is sticky: E = 0, too many weights, or s_last inside a snapshot.
module beamform #(
  parameter int LOG2M = 3,
  parameter bit RESET_ACTIVE = 1,
  parameter int ENERGY_WIDTH = 36 + LOG2M
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
  localparam int M = 1 << LOG2M;
  localparam int MB = LOG2M > 0 ? LOG2M : 1;
  localparam int AW = 37 + LOG2M;
  // Both signed18 MIN components contribute +2^35 per coefficient.
  initial if (ENERGY_WIDTH < 36 + LOG2M || ENERGY_WIDTH > 63)
    $fatal(1,"[PARAMETER] BEAM ENERGY_WIDTH must be in %0d..63",36+LOG2M);
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [17:0] sat18(input logic signed [AW+24:0] value, input logic [6:0] shift);
    logic signed [AW+24:0] rounded;
    rounded = (value + ((AW+25)'(1) <<< (shift - 1'b1))) >>> shift;
    if (rounded[AW+24:17] != {(AW+8){rounded[AW+24]}}) return rounded[AW+24] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  logic signed [17:0] w_re [0:M-1], w_im [0:M-1];
  logic [LOG2M:0] count, loaded, c;
  logic [ENERGY_WIDTH-1:0] energy;
  logic norm_start, norm_done, norm_zero, waiting;
  logic [23:0] r;
  logic [6:0] shift;
  norm_reciprocal #(.WIDTH(ENERGY_WIDTH),.RESET_ACTIVE(RESET_ACTIVE)) norm(
    .clk(clk),.rst(rst),.start(norm_start),.energy(energy),.done(norm_done),.zero(norm_zero),.r(r),.shift(shift));
  logic [3:0] fifo_count, pending;
  logic [36:0] fifo [0:7];
  logic [2:0] fifo_head, fifo_tail;
  assign cfg_ready = !reset_now && !waiting && pending == '0 && c == '0;
  assign s_ready = !reset_now && configured && !(cfg_valid && cfg_ready) && {1'b0, fifo_count} + {1'b0, pending} < 5'd8;
  wire take = s_valid && s_ready;
  wire snapshot_end = c == loaded - 1'b1;
  wire pop = m_valid && m_ready;
  // Pipeline: a (operands), b (products), accumulation/snapshot (d), scaling (q), rounding (e).
  logic a_valid, a_first, a_end, a_last, b_valid, b_first, b_end, b_last, d_valid, t_last, q_valid, q_last, e_valid, e_last;
  logic signed [17:0] a_xr, a_xi, a_wr, a_wi;
  logic signed [35:0] p_rr, p_ii, p_ir, p_ri;
  (* use_dsp="no" *) logic signed [AW-1:0] acc_re, acc_im;
  logic signed [AW-1:0] t_re, t_im;
  logic signed [AW+24:0] q_re, q_im;
  logic signed [17:0] y_re, y_im;
  wire signed [AW-1:0] sum_re = AW'(p_rr) + AW'(p_ii), sum_im = AW'(p_ir) - AW'(p_ri);
  wire signed [AW-1:0] next_re = b_first ? sum_re : acc_re + sum_re, next_im = b_first ? sum_im : acc_im + sum_im;
  assign m_valid = fifo_count != 4'd0;
  assign m_re = fifo[fifo_head][36:19]; assign m_im = fifo[fifo_head][18:1]; assign m_last = fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    if (take) begin a_xr <= s_re; a_xi <= s_im; a_wr <= w_re[MB'(c)]; a_wi <= w_im[MB'(c)]; a_first <= c == '0; a_end <= snapshot_end; a_last <= s_last; end
    // x conj(a): (xr ar + xi ai) + j (xi ar - xr ai)
    p_rr <= a_xr*a_wr; p_ii <= a_xi*a_wi; p_ir <= a_xi*a_wr; p_ri <= a_xr*a_wi;
    b_first <= a_first; b_end <= a_end; b_last <= a_last;
    if (b_valid) begin acc_re <= next_re; acc_im <= next_im; if (b_end) begin t_re <= next_re; t_im <= next_im; t_last <= b_last; end end
    q_re <= (AW+25)'(t_re)*(AW+25)'($signed({1'b0, r})); q_im <= (AW+25)'(t_im)*(AW+25)'($signed({1'b0, r}));
    q_last <= t_last; y_re <= sat18(q_re, shift); y_im <= sat18(q_im, shift); e_last <= q_last;
    if (reset_now) begin
      configured <= 0; error <= 0; count <= '0; loaded <= '0; c <= '0; energy <= '0; norm_start <= 0; waiting <= 0;
      a_valid <= 0; b_valid <= 0; d_valid <= 0; q_valid <= 0; e_valid <= 0; pending <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
    end else begin
      norm_start <= 0;
      if (cfg_valid && cfg_ready) begin
        configured <= 0; count <= count + 1'b1;
        energy <= (count == '0 ? ENERGY_WIDTH'(0) : energy) + ENERGY_WIDTH'(37'(cfg_re*cfg_re) + 37'(cfg_im*cfg_im));
        if (count < (LOG2M+1)'(M)) begin w_re[MB'(count)] <= cfg_re; w_im[MB'(count)] <= cfg_im; end else error <= 1;
        if (cfg_last) begin
          count <= '0; loaded <= count + 1'b1;
          if (count < (LOG2M+1)'(M)) begin norm_start <= 1; waiting <= 1; end
        end
      end
      if (waiting && (norm_done || norm_zero && !norm_start)) begin
        waiting <= 0;
        if (norm_zero) error <= 1; else configured <= 1;
      end
      if (take) begin
        c <= snapshot_end ? '0 : c + 1'b1;
        if (s_last && !snapshot_end) error <= 1;
      end
      // d: the snapshot sum is registered; q: scaled; e: rounded (pushed the next clock).
      a_valid <= take; b_valid <= a_valid; d_valid <= b_valid && b_end; q_valid <= d_valid; e_valid <= q_valid;
      if (e_valid) begin fifo[fifo_tail] <= {y_re, y_im, e_last}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {3'd0, e_valid} - {3'd0, pop};
      pending <= pending + {3'd0, take && snapshot_end} - {3'd0, e_valid};
    end
  end
endmodule
