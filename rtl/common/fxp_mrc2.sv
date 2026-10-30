// Two-branch maximal ratio combiner with known branch gains (mrc_fixed.py).
// Configuration: gains Q3.15, variances 1..65535 in a common scale. Weights
//   w_a = conj(g_a)*v_b/D, w_b = conj(g_b)*v_a/D, D = |g_a|^2 v_b + |g_b|^2 v_a
// are computed once per configuration with one shared multiplier and a sequential
// divider (about 310 clocks). Zero variance, D = 0 or a weight outside Q4.14 sets
// error and leaves the combiner unconfigured. Configuration is accepted only when
// no sample is in flight.
// Stream: both branches share valid/last. Output = sum of x*w, rounded to Q3.15
// with saturation (sticky saturated flag): 5 pipeline stages into an 8-word
// output FIFO, latency 6 from input to output transfer.
// The datapath never stalls: input credits bound the samples in flight, so
// m_ready drives only the FIFO, not the DSP clock enables.
module fxp_mrc2 #(parameter bit RESET_ACTIVE = 1'b1)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic signed [17:0] cfg_gain_a_re, cfg_gain_a_im, cfg_gain_b_re, cfg_gain_b_im,
  input logic [15:0] cfg_variance_a, cfg_variance_b,
  output logic cfg_ready, configured, error, saturated,
  input logic s_valid, s_last,
  input logic signed [17:0] s_a_re, s_a_im, s_b_re, s_b_im,
  output logic s_ready,
  output logic m_valid, m_last,
  input logic m_ready,
  output logic signed [17:0] m_re, m_im,
  input logic cfg_enable
);
  localparam int DEPTH = 8;
  wire reset = rst == RESET_ACTIVE;
  // Typedef casts: Quartus Standard rejects size casts and a unary minus before a cast.
  typedef logic signed [34:0] s35_t;
  typedef logic [35:0] u36_t;
  typedef logic [51:0] u52_t;

  // ---- Weight computation ----
  logic multiplying;
  logic signed [17:0] ga_re, ga_im, gb_re, gb_im;
  logic [15:0] va, vb;
  logic [3:0] step;
  logic [1:0] phase, quotient_index;
  logic signed [36:0] mul_a;
  logic signed [17:0] mul_b;
  // Largest product |g|^2*v < 2^51: 52 signed bits.
  logic signed [51:0] product, product_q;
  logic [35:0] power_a, power_b;
  logic [51:0] denominator;
  logic signed [34:0] numerator [0:3];
  logic signed [17:0] weight [0:3];
  logic divider_start, divider_busy, divider_done, weight_range_error;
  logic signed [63:0] divider_result;
  fxp_divide_seq #(.NUM_WIDTH(64),.DEN_WIDTH(52),.RESET_ACTIVE(RESET_ACTIVE)) divider(
    .clk(clk),.rst(rst),.start(divider_start),.numerator({numerator[quotient_index],29'd0}),
    .denominator(denominator),.busy(divider_busy),.done(divider_done),.result(divider_result));
  wire weight_in_range = divider_result >= -64'sd131072 && divider_result <= 64'sd131071;
  logic [3:0] used;
  wire accept = s_valid && s_ready;
  wire pop = m_valid && m_ready;
  assign cfg_ready = cfg_enable && !multiplying && !divider_start && !divider_busy && used == 0 && !reset;

  // Operand table: squares, powers times the other variance, gains times the other variance.
  always_ff @(posedge clk) begin
    case (step)
      4'd0: begin mul_a <= 37'(ga_re); mul_b <= ga_re; end
      4'd1: begin mul_a <= 37'(ga_im); mul_b <= ga_im; end
      4'd2: begin mul_a <= 37'(gb_re); mul_b <= gb_re; end
      4'd3: begin mul_a <= 37'(gb_im); mul_b <= gb_im; end
      4'd4: begin mul_a <= $signed({1'b0,power_a}); mul_b <= $signed({2'b0,vb}); end
      4'd5: begin mul_a <= $signed({1'b0,power_b}); mul_b <= $signed({2'b0,va}); end
      4'd6: begin mul_a <= 37'(ga_re); mul_b <= $signed({2'b0,vb}); end
      4'd7: begin mul_a <= 37'(ga_im); mul_b <= $signed({2'b0,vb}); end
      4'd8: begin mul_a <= 37'(gb_re); mul_b <= $signed({2'b0,va}); end
      default: begin mul_a <= 37'(gb_im); mul_b <= $signed({2'b0,va}); end
    endcase
    product <= 52'(mul_a*mul_b); product_q <= product;
  end

  always_ff @(posedge clk) begin
    if (reset) begin
      multiplying <= 1'b0; configured <= 1'b0; error <= 1'b0; divider_start <= 1'b0; weight_range_error <= 1'b0;
    end else begin
      divider_start <= 1'b0;
      if (cfg_valid && cfg_ready) begin
        ga_re <= cfg_gain_a_re; ga_im <= cfg_gain_a_im; gb_re <= cfg_gain_b_re; gb_im <= cfg_gain_b_im;
        va <= cfg_variance_a; vb <= cfg_variance_b; configured <= 1'b0; error <= 1'b0;
        step <= 4'd0; phase <= 2'd0; weight_range_error <= 1'b0;
        if (cfg_variance_a == 0 || cfg_variance_b == 0) error <= 1'b1;
        else multiplying <= 1'b1;
      end
      if (multiplying) begin
        // Phase 0 selects operands, 1 multiplies, 2 registers, 3 stores.
        phase <= phase + 2'd1;
        if (phase == 2'd3) begin
          case (step)
            4'd0: power_a <= u36_t'(product_q);
            4'd1: power_a <= power_a + u36_t'(product_q);
            4'd2: power_b <= u36_t'(product_q);
            4'd3: power_b <= power_b + u36_t'(product_q);
            4'd4: denominator <= u52_t'(product_q);
            4'd5: denominator <= denominator + u52_t'(product_q);
            4'd6: numerator[0] <= s35_t'(product_q);
            4'd7: numerator[1] <= s35_t'(-product_q);
            4'd8: numerator[2] <= s35_t'(product_q);
            default: numerator[3] <= s35_t'(-product_q);
          endcase
          step <= step + 4'd1;
          if (step == 4'd9) begin
            multiplying <= 1'b0;
            if (denominator == 0) error <= 1'b1;
            else begin quotient_index <= 2'd0; divider_start <= 1'b1; end
          end
        end
      end
      // Divider results arrive only during weight computation.
      if (divider_done) begin
        weight[quotient_index] <= divider_result[17:0];
        if (!weight_in_range) weight_range_error <= 1'b1;
        quotient_index <= quotient_index + 2'd1;
        if (quotient_index != 2'd3) divider_start <= 1'b1;
        else if (weight_range_error || !weight_in_range) error <= 1'b1;
        else configured <= 1'b1;
      end
    end
  end

  // ---- Datapath: input, products, product register, branch sums, total, rounding ----
  logic [4:0] valid_pipe, last_pipe;
  logic signed [17:0] ar, ai, br, bi;
  logic signed [35:0] p_rr [0:1];
  logic signed [35:0] p_ii [0:1];
  logic signed [35:0] p_ri [0:1];
  logic signed [35:0] p_ir [0:1];
  logic signed [35:0] q_rr [0:1];
  logic signed [35:0] q_ii [0:1];
  logic signed [35:0] q_ri [0:1];
  logic signed [35:0] q_ir [0:1];
  (* use_dsp="no" *) logic signed [36:0] branch_re [0:1];
  (* use_dsp="no" *) logic signed [36:0] branch_im [0:1];
  (* use_dsp="no" *) logic signed [37:0] sum_re, sum_im;
  logic signed [17:0] rounded_re, rounded_im;
  logic [1:0] overflow;
  fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(29),.OUT_WIDTH(18),.OUT_FRAC(15))
    round_re(.s_data(sum_re),.m_data(rounded_re),.overflow(overflow[0]));
  fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(29),.OUT_WIDTH(18),.OUT_FRAC(15))
    round_im(.s_data(sum_im),.m_data(rounded_im),.overflow(overflow[1]));
  always_ff @(posedge clk) begin
    if (reset) valid_pipe <= '0;
    else valid_pipe <= {valid_pipe[3:0], accept};
    // Datapath registers have no reset, allowing both vendors to infer DSPs.
    last_pipe <= {last_pipe[3:0], s_last};
    ar <= s_a_re; ai <= s_a_im; br <= s_b_re; bi <= s_b_im;
    p_rr[0] <= ar*weight[0]; p_ii[0] <= ai*weight[1]; p_ri[0] <= ar*weight[1]; p_ir[0] <= ai*weight[0];
    p_rr[1] <= br*weight[2]; p_ii[1] <= bi*weight[3]; p_ri[1] <= br*weight[3]; p_ir[1] <= bi*weight[2];
    for (int k = 0; k < 2; k++) begin
      q_rr[k] <= p_rr[k]; q_ii[k] <= p_ii[k]; q_ri[k] <= p_ri[k]; q_ir[k] <= p_ir[k];
      branch_re[k] <= 37'(q_rr[k]) - 37'(q_ii[k]); branch_im[k] <= 37'(q_ri[k]) + 37'(q_ir[k]);
    end
    sum_re <= 38'(branch_re[0]) + 38'(branch_re[1]); sum_im <= 38'(branch_im[0]) + 38'(branch_im[1]);
  end

  // ---- Output FIFO and credits ----
  // Shifting FIFO: the head is always fifo[0], a plain register; no addressable
  // memory, so neither vendor infers RAM with read-during-write bypass logic.
  logic [36:0] fifo [0:DEPTH-1];
  logic [3:0] fifo_count;
  wire [3:0] write_slot = fifo_count - 4'(pop);
  assign s_ready = configured && used < 4'(DEPTH) && !reset && !(cfg_valid && cfg_ready);
  assign m_valid = fifo_count != 0;
  assign m_last = fifo[0][36];
  assign m_re = fifo[0][35:18];
  assign m_im = fifo[0][17:0];
  always_ff @(posedge clk) begin
    for (int k = 0; k < DEPTH; k++) begin
      if (valid_pipe[4] && write_slot == 4'(k)) fifo[k] <= {last_pipe[4], rounded_re, rounded_im};
      else if (pop && k < DEPTH-1) fifo[k] <= fifo[k < DEPTH-1 ? k+1 : k];
    end
    if (reset) begin
      used <= '0; fifo_count <= '0; saturated <= 1'b0;
    end else begin
      used <= used + 4'(accept) - 4'(pop);
      fifo_count <= fifo_count + 4'(valid_pipe[4]) - 4'(pop);
      if (valid_pipe[4] && |overflow) saturated <= 1'b1;
      else if (cfg_valid && cfg_ready) saturated <= 1'b0;
    end
  end
endmodule
