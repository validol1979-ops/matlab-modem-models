module fxp_round_sat #(
  parameter int IN_WIDTH = 37, IN_FRAC = 30,
  parameter int OUT_WIDTH = 18, OUT_FRAC = 15
)(
  input logic signed [IN_WIDTH-1:0] s_data,
  output logic signed [OUT_WIDTH-1:0] m_data,
  output logic overflow
);
  localparam int DROP = IN_FRAC - OUT_FRAC;
  localparam int LEFT = DROP < 0 ? -DROP : 0;
  localparam int WIDE = (IN_WIDTH+LEFT > OUT_WIDTH ? IN_WIDTH+LEFT : OUT_WIDTH)+1;
  localparam logic signed [WIDE-1:0] ONE = {{(WIDE-1){1'b0}},1'b1};
  localparam logic signed [WIDE-1:0] MAXIMUM = (ONE <<< (OUT_WIDTH-1))-ONE;
  localparam logic signed [WIDE-1:0] MINIMUM = -(ONE <<< (OUT_WIDTH-1));
  logic signed [WIDE-1:0] extended, rounded;
  assign extended = {{(WIDE-IN_WIDTH){s_data[IN_WIDTH-1]}},s_data};
  generate
    if (DROP > 1) begin : g_round
      always_comb begin
        rounded = extended >>> DROP;
        if (extended[DROP-1] && ((|extended[DROP-2:0]) || rounded[0])) rounded = rounded+ONE;
      end
    end else if (DROP == 1) begin : g_half
      always_comb begin
        rounded = extended >>> 1;
        if (extended[0] && rounded[0]) rounded = rounded+ONE;
      end
    end else begin : g_left
      assign rounded = extended <<< LEFT;
    end
  endgenerate
  always_comb begin
    overflow = 1'b0;
    if (rounded > MAXIMUM) begin m_data = MAXIMUM[OUT_WIDTH-1:0]; overflow = 1'b1; end
    else if (rounded < MINIMUM) begin m_data = MINIMUM[OUT_WIDTH-1:0]; overflow = 1'b1; end
    else m_data = rounded[OUT_WIDTH-1:0];
  end
endmodule
