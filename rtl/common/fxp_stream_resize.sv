module fxp_stream_resize #(
  parameter int IN_WIDTH = 37, IN_FRAC = 30, OUT_WIDTH = 18, OUT_FRAC = 15,
  parameter bit RESET_ACTIVE = 1'b1
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  output logic s_ready,
  input logic signed [IN_WIDTH-1:0] s_re, s_im,
  output logic m_valid, m_last,
  input logic m_ready,
  output logic signed [OUT_WIDTH-1:0] m_re, m_im,
  output logic [1:0] m_overflow
);
  logic valid_reg, reset;
  logic signed [OUT_WIDTH-1:0] quant_re, quant_im;
  logic [1:0] quant_overflow;
  assign reset = rst == RESET_ACTIVE;
  assign m_valid = valid_reg && !reset;
  assign s_ready = (!valid_reg || m_ready) && !reset;
  fxp_round_sat #(.IN_WIDTH(IN_WIDTH),.IN_FRAC(IN_FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_re(.s_data(s_re),.m_data(quant_re),.overflow(quant_overflow[0]));
  fxp_round_sat #(.IN_WIDTH(IN_WIDTH),.IN_FRAC(IN_FRAC),.OUT_WIDTH(OUT_WIDTH),.OUT_FRAC(OUT_FRAC))
    round_im(.s_data(s_im),.m_data(quant_im),.overflow(quant_overflow[1]));
  always_ff @(posedge clk) begin
    if (reset) valid_reg <= 1'b0;
    else if (s_ready) valid_reg <= s_valid;
    if (!valid_reg || m_ready) begin
      m_re <= quant_re; m_im <= quant_im;
      m_last <= s_last; m_overflow <= quant_overflow;
    end
  end
endmodule
