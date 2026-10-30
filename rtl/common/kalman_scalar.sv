// Scalar Kalman filter (research_core kalman; bit-exact reference oset_fixed.kalman).
// Parameters from the configuration port (one transfer, between transactions): Qn, R, P0 in
// Q24 (32 bit unsigned, R > 0). A transaction is one Q15 signal (s_last on its last sample),
// as many outputs; each transaction restarts from P = P0 and value 0.
// Gain engine (the gains do not depend on the data): P += Qn; K = divide(P*2^17, P + R)
// (fxp_divide_seq, nearest-even, Q17); P = rnd(P*(2^17 - K), 17). The gains go into a
// 4-entry FIFO, about 70 clocks each; when P stops changing the gain is constant and the
// engine stops (steady gain) - for the research case after 116 samples.
// Data, two clocks per sample: d = (x << 8) - V, then V += rnd(K*d, 17) (8 guard bits, 27 bit),
// y = sat18(rnd(V, 8)) into the output register (m_ready backpressure).
// error is sticky: a configuration with R = 0, or a gain above 1 (divider self-check).
module kalman_scalar #(
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [31:0] cfg_q, cfg_r, cfg_p0,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [17:0] sat18(input logic signed [26:0] value);
    logic signed [26:0] rounded;
    rounded = (value + 27'sd128) >>> 8;
    if (rounded[26:17] != {10{rounded[26]}}) return rounded[26] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  logic [31:0] q, r, p0;
  // Gain engine.
  typedef enum logic [2:0] {G_START, G_DIVIDE, G_MULTIPLY, G_UPDATE, G_STOP} gstate_t;
  gstate_t gstate;
  logic [31:0] p;
  logic [32:0] p_pred;
  logic [17:0] gain, steady;
  logic converged;
  logic [17:0] gfifo [0:3];
  logic [1:0] ghead, gtail;
  logic [2:0] gcount;
  logic div_start;
  wire div_busy, div_done;
  wire signed [63:0] div_result;
  fxp_divide_seq #(.NUM_WIDTH(64),.DEN_WIDTH(34),.RESET_ACTIVE(RESET_ACTIVE)) divider(
    .clk(clk),.rst(rst),.start(div_start),.numerator(64'({p_pred, 17'd0})),.denominator(34'(p_pred) + 34'(r)),
    .busy(div_busy),.done(div_done),.result(div_result));
  logic signed [51:0] p_product;
  wire [31:0] p_next = 32'((p_product + 52'sd65536) >>> 17);
  // Data path.
  logic phase, in_tx, o_valid, o_last, d_last;
  logic signed [26:0] v_re, v_im, d_re, d_im;
  logic [17:0] k;
  logic signed [17:0] o_re, o_im;
  wire gain_ready = gcount != 3'd0 || converged;
  wire [17:0] gain_now = gcount != 3'd0 ? gfifo[ghead] : steady;
  assign cfg_ready = !reset_now && !in_tx && !phase && !o_valid;
  wire cfg_take = cfg_valid && cfg_ready;
  // A new configuration invalidates every prefetched gain. A held data offer waits
  // for the new gain sequence; it cannot use the previous configuration's FIFO.
  assign s_ready = !reset_now && configured && !phase && gain_ready && !cfg_take;
  wire take = s_valid && s_ready;
  wire update = phase && (!o_valid || m_ready);
  wire signed [26:0] vn_re = v_re + 27'((46'($signed({1'b0, k}))*46'(d_re) + 46'sd65536) >>> 17);
  wire signed [26:0] vn_im = v_im + 27'((46'($signed({1'b0, k}))*46'(d_im) + 46'sd65536) >>> 17);
  assign m_valid = o_valid; assign m_last = o_last; assign m_re = o_re; assign m_im = o_im;
  wire tx_end = update && d_last;

  always_ff @(posedge clk) begin
    if (take) begin
      d_re <= (27'(s_re) <<< 8) - v_re; d_im <= (27'(s_im) <<< 8) - v_im; k <= gain_now; d_last <= s_last;
    end
    if (update) begin o_re <= sat18(vn_re); o_im <= sat18(vn_im); o_last <= d_last; end
    if (div_done) gain <= div_result[17:0];
    p_product <= 52'(p_pred)*52'({1'b0, 18'd131072 - gain});
    if (reset_now) begin
      configured <= 0; error <= 0; gstate <= G_STOP; converged <= 0; gcount <= '0; ghead <= '0; gtail <= '0;
      div_start <= 0; phase <= 0; in_tx <= 0; o_valid <= 0; v_re <= '0; v_im <= '0;
    end else begin
      div_start <= 0;
      // K = P/(P+R) <= 1: an upper quotient bit would be a divider fault.
      if (div_done && div_result[63:18] != '0) error <= 1;
      if (cfg_take) begin
        q <= cfg_q; r <= cfg_r; p0 <= cfg_p0;
        if (cfg_r != 32'd0) begin configured <= 1; gstate <= G_START; end else begin configured <= 0; error <= 1; gstate <= G_STOP; end
        p <= cfg_p0; converged <= 0; gcount <= '0; ghead <= '0; gtail <= '0;
        v_re <= '0; v_im <= '0;
      end else begin
      // Configuration reset is exclusive: the old engine cannot overwrite its
      // state/FIFO reset. An already-started divider may finish; G_START waits for
      // it to become idle before issuing a division with the new parameters.
      // Gain engine: one gain per division until P is a fixed point.
      case (gstate)
        G_START: if (gcount != 3'd4 && !div_busy) begin p_pred <= 33'(p) + 33'(q); gstate <= G_DIVIDE; div_start <= 1; end
        G_DIVIDE: if (div_done) gstate <= G_MULTIPLY;
        // The product p_pred*(2^17 - K) is registered one clock after the gain.
        G_MULTIPLY: gstate <= G_UPDATE;
        G_UPDATE: begin
          gfifo[gtail] <= gain; gtail <= gtail + 1'b1;
          if (p_next == p) begin converged <= 1; steady <= gain; gstate <= G_STOP; end
          else begin p <= p_next; gstate <= G_START; end
        end
        default: begin end
      endcase
      // Data: a sample takes a gain (FIFO first, then the steady one).
      if (take) begin
        phase <= 1; in_tx <= !s_last;
        if (gcount != 3'd0) ghead <= ghead + 1'b1;
      end
      gcount <= gcount + {2'd0, gstate == G_UPDATE} - {2'd0, take && gcount != 3'd0};
      if (update) begin phase <= 0; o_valid <= 1; v_re <= vn_re; v_im <= vn_im; end
      else if (m_ready) o_valid <= 0;
      // A finished transaction restarts the value and the gain sequence.
      if (tx_end) begin
        v_re <= '0; v_im <= '0; p <= p0; converged <= 0; gcount <= '0; ghead <= '0; gtail <= '0; gstate <= G_START;
      end
      end
    end
  end
endmodule
