module fxp_complex_mul #(
  parameter int WIDTH = 18, FRAC = 15, OUT_WIDTH = 18, OUT_FRAC = 15,
  parameter bit RESET_ACTIVE = 1'b1
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  output logic s_ready,
  input logic signed [WIDTH-1:0] s_ar, s_ai, s_br, s_bi,
  output logic m_valid, m_last,
  input logic m_ready,
  output logic signed [OUT_WIDTH-1:0] m_re, m_im,
  output logic [1:0] m_overflow
);
  localparam int PRODUCT = 2*WIDTH;
  localparam int SUM = PRODUCT+1;
  logic [3:0] valid_pipe, last_pipe;
  logic advance, reset;
  logic signed [WIDTH-1:0] ar, ai, br, bi;
  logic signed [PRODUCT-1:0] rr, ii, ri, ir;
  logic signed [SUM-1:0] sum_re, sum_im;
  logic signed [OUT_WIDTH-1:0] quant_re, quant_im;
  logic [1:0] quant_overflow;
  assign reset = rst == RESET_ACTIVE;
  assign m_valid = valid_pipe[3] && !reset;
  assign m_last = last_pipe[3];
  assign advance = !valid_pipe[3] || m_ready;
  assign s_ready = advance && !reset;
  fxp_round_sat #(.IN_WIDTH(SUM),.IN_FRAC(2*FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_re(.s_data(sum_re),.m_data(quant_re),.overflow(quant_overflow[0]));
  fxp_round_sat #(.IN_WIDTH(SUM),.IN_FRAC(2*FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_im(.s_data(sum_im),.m_data(quant_im),.overflow(quant_overflow[1]));
  always_ff @(posedge clk) begin
    if (reset) valid_pipe <= '0;
    else if (advance) valid_pipe <= {valid_pipe[2:0],s_valid};
    // Datapath registers have no reset, allowing both vendors to infer DSPs.
    if (advance) begin
      last_pipe <= {last_pipe[2:0],s_last};
      ar <= s_ar; ai <= s_ai; br <= s_br; bi <= s_bi;
      rr <= ar*br; ii <= ai*bi; ri <= ar*bi; ir <= ai*br;
      sum_re <= $signed({rr[PRODUCT-1],rr})-$signed({ii[PRODUCT-1],ii});
      sum_im <= $signed({ri[PRODUCT-1],ri})+$signed({ir[PRODUCT-1],ir});
      m_re <= quant_re; m_im <= quant_im; m_overflow <= quant_overflow;
    end
  end
endmodule
