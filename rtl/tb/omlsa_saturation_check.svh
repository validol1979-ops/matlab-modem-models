// Actual per-bin gain limiter inputs of the RTL (its narrowed wires), including arbitrary nonzero floors.
localparam logic signed [127:0] MAX_RANGE={1'b0,{127{1'b1}}};
wire omlsa_clamps_done=out_total>0&&out_checked==out_total&&dut.len_count==0&&dut.index==0;
logic sat_noise_valid[0:0];
logic signed [127:0] sat_noise_raw[0:0];
always_comb begin sat_noise_valid[0]=(dut.gain.state==dut.gain.NDIVW && dut.gain.div_done);sat_noise_raw[0]=128'(dut.gain.div_result);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd1),.HIGH_BOUND(MAX_RANGE),.NAME("omlsa_noise"),.EXPECTED_FILE("omlsa_noise_expected.txt")) check_noise
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_noise_valid),.rounded(sat_noise_raw));
logic sat_gamma_valid[0:0];
logic signed [127:0] sat_gamma_raw[0:0];
always_comb begin sat_gamma_valid[0]=(dut.gain.state==dut.gain.G2);sat_gamma_raw[0]=128'(dut.gain.gamma_round);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(128'sd2147483647),.NAME("omlsa_gamma"),.EXPECTED_FILE("omlsa_gamma_expected.txt")) check_gamma
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_gamma_valid),.rounded(sat_gamma_raw));
logic sat_excess_valid[0:0];
logic signed [127:0] sat_excess_raw[0:0];
always_comb begin sat_excess_valid[0]=(dut.gain.state==dut.gain.G3);sat_excess_raw[0]=128'(dut.gain.gamma)-128'sd65536;end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(MAX_RANGE),.NAME("omlsa_excess"),.EXPECTED_FILE("omlsa_excess_expected.txt")) check_excess
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_excess_valid),.rounded(sat_excess_raw));
logic sat_xi_valid[0:0];
logic signed [127:0] sat_xi_raw[0:0];
always_comb begin sat_xi_valid[0]=(dut.gain.state==dut.gain.G3);sat_xi_raw[0]=128'(dut.gain.xi_round);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd1),.HIGH_BOUND(128'sd2147483647),.NAME("omlsa_xi"),.EXPECTED_FILE("omlsa_xi_expected.txt")) check_xi
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_xi_valid),.rounded(sat_xi_raw));
logic sat_v_valid[0:0];
logic signed [127:0] sat_v_raw[0:0];
always_comb begin sat_v_valid[0]=(dut.gain.state==dut.gain.G7);sat_v_raw[0]=128'(dut.gain.v_round);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(128'sd2147483647),.NAME("omlsa_v"),.EXPECTED_FILE("omlsa_v_expected.txt")) check_v
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_v_valid),.rounded(sat_v_raw));
logic sat_g1_valid[0:0];
logic signed [127:0] sat_g1_raw[0:0];
always_comb begin sat_g1_valid[0]=(dut.gain.state==dut.gain.G10);sat_g1_raw[0]=128'(dut.gain.g1_next);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd3277),.HIGH_BOUND(128'sd65536),.NAME("omlsa_g1"),.EXPECTED_FILE("omlsa_g1_expected.txt")) check_g1
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_g1_valid),.rounded(sat_g1_raw));
logic sat_t_valid[0:0];
logic signed [127:0] sat_t_raw[0:0];
always_comb begin sat_t_valid[0]=(dut.gain.state==dut.gain.G10);sat_t_raw[0]=128'(dut.gain.t_round);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(128'sd2147483647),.NAME("omlsa_t"),.EXPECTED_FILE("omlsa_t_expected.txt")) check_t
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_t_valid),.rounded(sat_t_raw));
logic sat_exp_index_valid[0:0];
logic signed [127:0] sat_exp_index_raw[0:0];
always_comb begin sat_exp_index_valid[0]=(dut.gain.state==dut.gain.G15);sat_exp_index_raw[0]=(128'sd0-128'(dut.gain.a))>>>6;end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(128'sd4095),.NAME("omlsa_exp_index"),.EXPECTED_FILE("omlsa_exp_index_expected.txt")) check_exp_index
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_exp_index_valid),.rounded(sat_exp_index_raw));
logic sat_prev_valid[0:0];
logic signed [127:0] sat_prev_raw[0:0];
always_comb begin sat_prev_valid[0]=(dut.gain.state==dut.gain.G18 && (!dut.gain.m_valid || dut.gain.m_ready));sat_prev_raw[0]=128'(dut.gain.prev_round);end
sat_group_check #(.VALUES(1),.FIELDS(1),.OUT_WIDTH(32),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(128'sd0),.HIGH_BOUND(128'sd2147483647),.NAME("omlsa_prev"),.EXPECTED_FILE("omlsa_prev_expected.txt")) check_prev
  (.clk(clk),.rst(rst),.scoring(scoring),.done(omlsa_clamps_done),.valid(sat_prev_valid),.rounded(sat_prev_raw));
int sy_bounds_checks;
`define SYNTH_DUT dut.g64.synthesis
generate if(LOG2N==6) begin : g64_observer
  localparam string check_prefix="omlsa_istft";
  wire check_done=omlsa_clamps_done;
  `include "istft_observer.svh"
end endgenerate
`undef SYNTH_DUT
`define SYNTH_DUT dut.g16.synthesis
generate if(LOG2N==4) begin : g16_observer
  localparam string check_prefix="omlsa_istft";
  wire check_done=omlsa_clamps_done;
  `include "istft_observer.svh"
end endgenerate
`undef SYNTH_DUT
`define SYNTH_DUT dut.g32.synthesis
generate if(LOG2N==5) begin : g32_observer
  localparam string check_prefix="omlsa_istft";
  wire check_done=omlsa_clamps_done;
  `include "istft_observer.svh"
end endgenerate
`undef SYNTH_DUT
`define ANALYSIS_DUT dut.analysis
`include "stft_analysis_bounds.svh"
`undef ANALYSIS_DUT
`include "omlsa_bounds_check.svh"

