module fxp_complex_add #(
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
  logic [1:0] valid_pipe, last_pipe;
  logic advance, reset;
  logic signed [WIDTH:0] sum_re, sum_im;
  logic signed [OUT_WIDTH-1:0] quant_re, quant_im;
  logic [1:0] quant_overflow;
  assign reset = rst == RESET_ACTIVE;
  assign m_valid = valid_pipe[1] && !reset;
  assign m_last = last_pipe[1];
  assign advance = !valid_pipe[1] || m_ready;
  assign s_ready = advance && !reset;
  fxp_round_sat #(.IN_WIDTH(WIDTH+1),.IN_FRAC(FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_re(.s_data(sum_re),.m_data(quant_re),.overflow(quant_overflow[0]));
  fxp_round_sat #(.IN_WIDTH(WIDTH+1),.IN_FRAC(FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_im(.s_data(sum_im),.m_data(quant_im),.overflow(quant_overflow[1]));
  always_ff @(posedge clk) begin
    if (reset) valid_pipe <= '0;
    else if (advance) valid_pipe <= {valid_pipe[0],s_valid};
    if (advance) begin
      last_pipe <= {last_pipe[0],s_last};
      sum_re <= $signed({s_ar[WIDTH-1],s_ar})+$signed({s_br[WIDTH-1],s_br});
      sum_im <= $signed({s_ai[WIDTH-1],s_ai})+$signed({s_bi[WIDTH-1],s_bi});
      m_re <= quant_re; m_im <= quant_im; m_overflow <= quant_overflow;
    end
  end
endmodule
