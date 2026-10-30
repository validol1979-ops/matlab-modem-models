// Gardner, Costas and AGC with four-symbol carrier/timing delay and eight-symbol AGC delay. Catch-up II=4;
// availability at the capture boundary naturally limits operation to sps=8.
// ORDER=2: BPSK Costas (decision-directed sign, differential labels).
// ORDER=4: diagonal QPSK with AMPLITUDE per axis (16384 or 23170), target-directed phase
// error; for 23170 it is scaled by 1/sqrt(2) in a three-stage pipeline and gain/timing
// errors shift one more bit. DIFFERENTIAL selects Gray-differential labels.
// ORDER=8: unit 8-PSK with targets at 22.5+45k degrees (octant decisions); the phase
// error v1*t0-v0*t1 >> 15 uses a register, product and difference stage.
// FEEDFORWARD: phase-only carrier update (0.03 rad), frequency held from acquisition.
// TIMING_LOOP=0 removes the early-late detector; m_correction is then zero.
// PI4 (ORDER=8): pi/4-QPSK labels, 2 bits: label = gray_inverse(((index-previous-1) mod 8)/2).
// ORDER=16: QAM16, per-axis level decisions; phase and gain errors are normalized by
// |target|^2 through the Q16 reciprocal of n = a^2+b^2 (one more gain-error stage);
// timing is normalized by 2/Es; labels are quadrant-differential.
// ORDER=64: QAM64 with levels +-1..+-7 times AMPLITUDE = T = 2^13 (the receive filter
// output is scaled by 1/4): decisions clamp floor(v/2T) to -4..3, errors shift by
// log2(T)+1 and 2*log2(T)+1, the reciprocal table covers the nine a^2+b^2, 2/Es = 2/42.
// EQUALIZER (ORDER=16): 1 = 7-tap NLMS, 2 = DFE (bpsk_equalizer between the rotator and
// the slicer; it decides the target levels of its own output for the update). Its latency
// would hold the catch-up near one symbol per 8 clocks, so carrier/timing feedback then
// waits 8 symbols instead of 4 (LOOP_DELAY, profile loop_delay).
module bpsk_track #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter int ORDER=2,
 parameter int AMPLITUDE=ORDER==8?32768:ORDER==4?23170:16384,parameter bit DIFFERENTIAL=ORDER==2,parameter bit FEEDFORWARD=0,parameter bit TIMING_LOOP=1,
 parameter bit PI4=0,parameter int EQUALIZER=0
)(
 input logic clk,rst,start,
 input logic [11:0] count,
 input logic [192*(ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1)-1:0] training,
 input logic signed [31:0] delay,initial_frequency,initial_phase,
 input logic [24:0] initial_gain,
 input logic [14:0] available,
 input logic capture_done,
 output logic busy,done,
 output logic ce,q_valid,
 output logic signed [31:0] q_position,
 output logic [13:0] q_tag,
 input logic a_valid,
 input logic signed [17:0] a_re,a_im,
 input logic [13:0] a_tag,
 output logic m_valid,m_last,
 output logic [(ORDER==64?6:ORDER==16?4:ORDER==8?(PI4?2:3):ORDER==4?2:1)-1:0] m_bit,
 output logic [(ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1)-1:0] m_index,
 input logic m_ready,
 output logic signed [17:0] m_re,m_im,
 output logic signed [31:0] m_phase,m_frequency,m_correction,
 output logic [24:0] m_gain
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 localparam int BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
 // |target|^2 = 2*AMPLITUDE^2 is 2^29 for 16384 and about 2^30 for 23170.
 localparam bit WIDE=AMPLITUDE!=16384;
 localparam int GE_SHIFT=WIDE?16:15;
 localparam int TE_SHIFT=ORDER==64?25:WIDE?28:27;
 // QAM: log2(T), phase and gain error shifts, 2/Es in Q16 (round(2^17/Es)).
 localparam int LOG_T=ORDER==64?13:14;
 localparam int QAM_PE_SHIFT=LOG_T+1,QAM_GE_SHIFT=2*LOG_T+1;
 localparam logic [39:0] QAM_TE_MUL=ORDER==64?40'd3121:40'd13107;
 localparam logic signed [18:0] TARGET=b_s19_t'(AMPLITUDE);
 // Phase-error pipeline depth after the rotated sample; feedback waits for it.
 localparam int PE_STAGE=WIDE||ORDER>=16?2:0;
 // Gain-error pipeline depth: QAM16 adds the reciprocal multiplication stage.
 localparam int GE_STAGE=ORDER>=16?6:5;
 localparam logic signed [31:0] PHASE_GAIN=FEEDFORWARD?32'sd626:32'sd834;
 localparam int LOOP_DELAY=EQUALIZER!=0?8:4;
 localparam int SLOT=LOOP_DELAY==8?3:2;
 logic [1:0] subcycle;
 logic [11:0] next_symbol,active_symbol;
 logic signed [31:0] phase_state,frequency_state,active_position,base_position;
 logic [24:0] gain_state;
 (* ram_style="registers",ramstyle="logic" *) logic signed [31:0] meta_phase[0:7],meta_frequency[0:7];
 (* ram_style="registers",ramstyle="logic" *) logic [24:0] meta_gain[0:7];
 logic signed [15:0] pending_pe[0:LOOP_DELAY-1];
 logic signed [31:0] pending_phase[0:LOOP_DELAY-1];
 logic signed [15:0] pending_gain_delta[0:7];
 wire signed [31:0] new_correction;
 logic [LOOP_DELAY-1:0] feedback_ready;
 logic [7:0] gain_ready;
 wire [SLOT-1:0] feedback_slot=next_symbol[SLOT-1:0];
 wire signed [31:0] new_frequency=FEEDFORWARD?frequency_state:frequency_state+b_s32_t'(pending_pe[feedback_slot])*32'sd4;
 wire signed [31:0] new_phase=phase_state+pending_phase[feedback_slot];
 // The clipped next gain and its readiness are registered one clock ahead. They are
 // stale for one clock after a symbol or frame start, which gain_fresh masks; the
 // delta and its ready flag are written together, so the result is unchanged.
 wire signed [25:0] unclipped_gain=$signed({1'b0,gain_state})+b_s26_t'(pending_gain_delta[next_symbol[2:0]]);
 logic [24:0] new_gain;
 logic selected_gain_ready,gain_fresh;
 wire signed [31:0] next_position=base_position+new_correction;
 wire signed [31:0] last_needed=(active_position>>>16)+6;
 wire can_start=next_symbol<count&&feedback_ready[feedback_slot]&&selected_gain_ready&&gain_fresh;
 localparam int INIT_WIDTH=ORDER>=16?3:2;
 logic [INIT_WIDTH-1:0] initialization;
 // QAM16 adds three initialization steps: the 2/Es factor as two narrow products and
 // their sum, then a split rounding.
 typedef logic [INIT_WIDTH-1:0] init_t;
 localparam init_t INIT_STEPS=init_t'(ORDER>=16?5:2);
 wire can_read=capture_done||last_needed<$signed({17'd0,available});
 assign ce=!m_valid||m_ready;
 always_comb begin
  q_valid=busy&&((subcycle==1&&can_read)||subcycle==2||subcycle==3);
  q_position=active_position+(subcycle==1?-32'sd262144:subcycle==3?32'sd262144:32'sd0);
  q_tag={active_symbol,b_u2_t'(subcycle-1'b1)};
 end
 wire [11:0] a_symbol=a_tag[13:2];wire [2:0] a_slot=a_symbol[2:0];
 wire rotate_valid=a_valid&&a_tag[1:0]==1;
 // The training label is looked up before rotation and travels in tag bits 12 (training
 // flag) and 13+ (label), keeping the 192-symbol lookup off the error path.
 wire a_training=a_symbol<188;
 wire [BITS-1:0] a_label;
 generate
 if(BITS==6) begin:g_label6
  // 6*symbol = 4*symbol + 2*symbol.
  assign a_label=training[11'({a_symbol[7:0],2'b0})+11'({a_symbol[7:0],1'b0})+:6];
 end else if(BITS==4) begin:g_label4
  assign a_label=training[{a_symbol[7:0],2'b0}+:4];
 end else if(BITS==3) begin:g_label3
  assign a_label=training[{a_symbol[7:0],1'b0}+{2'b0,a_symbol[7:0]}+:3];
 end else if(BITS==2) begin:g_label2
  assign a_label=training[{a_symbol[7:0],1'b0}+:2];
 end else begin:g_label1
  assign a_label=training[a_symbol[7:0]];
 end
 endgenerate
 wire rotated_valid;wire signed [17:0] rotated_re,rotated_im;wire [31:0] rotated_tag;
 wire rot_valid;wire signed [17:0] rot_re,rot_im;wire [31:0] rot_tag;
 bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
  clk,rst,ce,rotate_valid,a_re,a_im,meta_phase[a_slot][31:20],meta_gain[a_slot],{{(19-BITS){1'b0}},a_label,a_training,a_symbol},rot_valid,rot_re,rot_im,rot_tag);
 generate
 if(EQUALIZER!=0) begin:g_equalizer
  bpsk_equalizer #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.DFE(EQUALIZER==2)) equalizer(
   clk,rst,ce,start,rot_valid,rot_re,rot_im,rot_tag,rotated_valid,rotated_re,rotated_im,rotated_tag);
 end else begin:g_no_equalizer
  assign rotated_valid=rot_valid;assign rotated_re=rot_re;assign rotated_im=rot_im;assign rotated_tag=rot_tag;
 end
 endgenerate
 wire [11:0] r_symbol=rotated_tag[11:0];wire [2:0] r_slot=r_symbol[2:0];
 wire r_training=rotated_tag[12];wire [BITS-1:0] r_label=rotated_tag[13+:BITS];
 wire [BITS-1:0] decision;
 wire signed [18:0] target_re,target_im;
 wire signed [15:0] gain_error;
 logic signed [36:0] gain_error_re,gain_error_im;
 // Write port of pending_pe; BPSK writes with the rotated sample, QPSK two stages later.
 wire pe_write;
 // QAM registers the phase error at its write (one clock before PE_STAGE); the phase step
 // uses it and pending_pe (4 or 8 slots) takes it at PE_STAGE together with the ready flag,
 // keeping the slot write off the rounding path.
 logic signed [15:0] pe_held;
 wire signed [15:0] pe_for_phase;
 wire [SLOT-1:0] pe_slot;
 wire signed [15:0] pe_value;
 logic [GE_STAGE:0] error_valid_pipe;
 logic [2:0] error_symbol[0:GE_STAGE];
 assign pe_for_phase=ORDER>=16 ? pe_held : pending_pe[error_symbol[PE_STAGE][SLOT-1:0]];
 generate
 if(ORDER>=16) begin:g_qam16_decision
  // Level code c = clamp(floor(v/2T), -C, C-1) per axis (C = 2 for QAM16, 4 for QAM64);
  // the decided level is 2c+1 = {c,1}. Training targets take the label levels (tag
  // register). Levels are 4-bit signed; |level| code (|l|-1)/2 is c, or ~c when negative.
  wire signed [3:0] la,lb;
  wire [15:0] target_reciprocal;
  if(ORDER==64) begin:g_qam64_tables
   wire signed [3:0] fa=$signed(rotated_re[17:14]),fb=$signed(rotated_im[17:14]);
   wire signed [2:0] ca=fa < -4'sd4 ? 3'sb100 : fa > 4'sd3 ? 3'sb011 : fa[2:0];
   wire signed [2:0] cb=fb < -4'sd4 ? 3'sb100 : fb > 4'sd3 ? 3'sb011 : fb[2:0];
   assign decision=q64_index(ca,cb);
   wire [7:0] label_levels=q64_levels(r_label);
   assign la=r_training ? $signed(label_levels[7:4]) : $signed({ca,1'b1});
   assign lb=r_training ? $signed(label_levels[3:0]) : $signed({cb,1'b1});
   wire [1:0] ma=la[3] ? ~la[2:1] : la[2:1],mb=lb[3] ? ~lb[2:1] : lb[2:1];
   assign target_reciprocal=q64_magnitude_reciprocal({ma,mb});
  end else begin:g_qam16_tables
   wire signed [2:0] fa=$signed(rotated_re[17:15]),fb=$signed(rotated_im[17:15]);
   // 2'sb10 = -2 (a decimal 2'sd2 overflows the signed 2-bit range in Quartus).
   wire signed [1:0] ca=fa < -3'sd2 ? 2'sb10 : fa > 3'sd1 ? 2'sb01 : fa[1:0];
   wire signed [1:0] cb=fb < -3'sd2 ? 2'sb10 : fb > 3'sd1 ? 2'sb01 : fb[1:0];
   assign decision=q16_index(ca,cb);
   wire [5:0] label_levels=q16_levels(r_label);
   wire [5:0] levels=r_training ? label_levels : {ca,1'b1,cb,1'b1};
   assign la={levels[5],levels[5:3]};assign lb={levels[2],levels[2:0]};
   assign target_reciprocal=q16_reciprocal(levels);
  end
  wire signed [18:0] t0=b_s19_t'(qam_scale(b_s18_t'(AMPLITUDE),la)),t1=b_s19_t'(qam_scale(b_s18_t'(AMPLITUDE),lb));
  assign target_re=t0-(b_s19_t'(rotated_re));
  assign target_im=t1-(b_s19_t'(rotated_im));
  // (a*v1-b*v0)*R(n) >> (log2 T + 1): register, product, round.
  logic signed [22:0] pe_difference;
  logic [15:0] pe_reciprocal;
  logic signed [39:0] pe_product;
  always_ff @(posedge clk) if(ce) begin
   pe_difference<=b_s23_t'(qam_scale(rotated_im,la))-b_s23_t'(qam_scale(rotated_re,lb));pe_reciprocal<=target_reciprocal;
   pe_product<=pe_difference*$signed({1'b0,pe_reciprocal});
  end
  wire pe_round_up=pe_product[QAM_PE_SHIFT-1]&&((|pe_product[QAM_PE_SHIFT-2:0])||pe_product[QAM_PE_SHIFT]);
  wire signed [25:0] pe_rounded=b_s26_t'($signed(pe_product[39:QAM_PE_SHIFT]))+$signed({25'd0,pe_round_up});
  assign pe_value=pe_rounded>26'sd16384 ? 16'sd16384:pe_rounded< -26'sd16384 ? -16'sd16384:pe_rounded[15:0];
  assign pe_write=error_valid_pipe[1];assign pe_slot=error_symbol[1][SLOT-1:0];
  // sum*R(n) >> (2*log2 T + 1) with the reciprocal carried alongside the target.
  // Aligned with gain_target (stage 0), gain_error_re (1) and gain_sum (2).
  logic [15:0] reciprocal_pipe[0:2];
  logic signed [37:0] gain_sum;
  logic signed [54:0] gain_scaled;
  always_ff @(posedge clk) if(ce) begin
   reciprocal_pipe[0]<=target_reciprocal;reciprocal_pipe[1]<=reciprocal_pipe[0];reciprocal_pipe[2]<=reciprocal_pipe[1];
   gain_sum<=b_s38_t'(gain_error_re)+b_s38_t'(gain_error_im);
   gain_scaled<=gain_sum*$signed({1'b0,reciprocal_pipe[2]});
  end
  wire gain_round_up=gain_scaled[QAM_GE_SHIFT-1]&&((|gain_scaled[QAM_GE_SHIFT-2:0])||gain_scaled[QAM_GE_SHIFT]);
  wire signed [28:0] gain_error_rounded=b_s29_t'($signed(gain_scaled[54:QAM_GE_SHIFT]))+$signed({28'd0,gain_round_up});
  assign gain_error=gain_error_rounded>29'sd16384 ? 16'sd16384:gain_error_rounded< -29'sd16384 ? -16'sd16384:gain_error_rounded[15:0];
 end else if(ORDER==8) begin:g_psk8_decision
  // Octant: quadrant from the signs, |I| > |Q| selects the half within it.
  wire sx=rotated_re<0,sy=rotated_im<0;
  wire [18:0] ax=sx?-{rotated_re[17],rotated_re}:{rotated_re[17],rotated_re};
  wire [18:0] ay=sy?-{rotated_im[17],rotated_im}:{rotated_im[17],rotated_im};
  wire larger=ax>ay;
  wire [1:0] quadrant={sy,sx^sy};
  assign decision={quadrant,quadrant[0]?larger:!larger};
  wire [2:0] target=r_training?r_label:decision;
  // Targets at 22.5+45k degrees, Q15: cos 22.5 = 30274, sin 22.5 = 12540.
  logic signed [18:0] t0,t1;
  always_comb case(target)
   3'd0:begin t0=19'sd30274;t1=19'sd12540;end
   3'd1:begin t0=19'sd12540;t1=19'sd30274;end
   3'd2:begin t0=-19'sd12540;t1=19'sd30274;end
   3'd3:begin t0=-19'sd30274;t1=19'sd12540;end
   3'd4:begin t0=-19'sd30274;t1=-19'sd12540;end
   3'd5:begin t0=-19'sd12540;t1=-19'sd30274;end
   3'd6:begin t0=19'sd12540;t1=-19'sd30274;end
   default:begin t0=19'sd30274;t1=-19'sd12540;end
  endcase
  assign target_re=t0-(b_s19_t'(rotated_re));
  assign target_im=t1-(b_s19_t'(rotated_im));
  // |target|^2 = 2^30: imag(value*conj(target)) >> 15 is the Q15 error.
  logic signed [17:0] error_re,error_im;
  logic signed [18:0] error_t0,error_t1;
  logic signed [36:0] product_a,product_b;
  always_ff @(posedge clk) if(ce) begin
   error_re<=rotated_re;error_im<=rotated_im;error_t0<=t0;error_t1<=t1;
   product_a<=error_im*error_t0;product_b<=error_re*error_t1;
  end
  wire signed [37:0] error_difference=b_s38_t'(product_a)-b_s38_t'(product_b);
  wire pe_round_up=error_difference[14]&&((|error_difference[13:0])||error_difference[15]);
  wire signed [23:0] pe_rounded=$signed(error_difference[37:15])+$signed({23'd0,pe_round_up});
  // Same saturation as two full-width compares, but one shallow term: pe_rounded is in
  // [-16384,16383] exactly when [23:14] replicate bit 23, and both clamps are that bit
  // plus 1'b1 (the +16384 boundary truncates to the same 16-bit pattern).
  wire pe_in_range=pe_rounded[23:14]=={10{pe_rounded[23]}};
  wire signed [15:0] pe_clamped=pe_rounded[23]? -16'sd16384 : 16'sd16384;
  assign pe_value=pe_in_range?pe_rounded[15:0]:pe_clamped;
  assign pe_write=error_valid_pipe[1];assign pe_slot=error_symbol[1][SLOT-1:0];
 end else if(ORDER==4) begin:g_qpsk_decision
  // Quadrant label: bit 1 is the Q sign, bit0^bit1 the I sign.
  wire s0=rotated_re<0,s1=rotated_im<0;
  assign decision={s1,s0^s1};
  wire [1:0] target=r_training?r_label:decision;
  wire ta=target[1]^target[0],tb=target[1];
  assign target_re=(ta?-TARGET:TARGET)-(b_s19_t'(rotated_re));
  assign target_im=(tb?-TARGET:TARGET)-(b_s19_t'(rotated_im));
  // imag(value*conj(target)) / T before scaling: a*v1-b*v0.
  wire signed [19:0] av1=ta?-$signed({{2{rotated_im[17]}},rotated_im}):$signed({{2{rotated_im[17]}},rotated_im});
  wire signed [19:0] bv0=tb?-$signed({{2{rotated_re[17]}},rotated_re}):$signed({{2{rotated_re[17]}},rotated_re});
  if(WIDE) begin:g_scaled_error
   logic signed [19:0] pe_difference;
   logic signed [35:0] pe_product;
   always_ff @(posedge clk) if(ce) begin pe_difference<=av1-bv0;pe_product<=pe_difference*36'sd23171;end
   wire pe_round_up=pe_product[14]&&((|pe_product[13:0])||pe_product[15]);
   wire signed [21:0] pe_rounded=$signed(pe_product[35:15])+$signed({21'd0,pe_round_up});
   // Same saturation as two full-width compares, but one shallow term: pe_rounded is
   // inside [-16384,16383] exactly when [20:14] replicate its sign, the +16384 boundary
   // truncates to the same 16-bit pattern, and both clamps are the sign bit plus 1'b1.
   wire pe_in_range=pe_rounded[20:14]=={7{pe_rounded[21]}};
   wire signed [15:0] pe_clamped=pe_rounded[21]? -16'sd16384 : 16'sd16384;
   assign pe_value=pe_in_range?pe_rounded[15:0]:pe_clamped;
   assign pe_write=error_valid_pipe[1];assign pe_slot=error_symbol[1][SLOT-1:0];
  end else begin:g_direct_error
   // 2^29/T = 2^15: the scaled error equals a*v1-b*v0.
   wire signed [19:0] phase_error=av1-bv0;
   assign pe_value=phase_error>20'sd16384 ? 16'sd16384:phase_error< -20'sd16384 ? -16'sd16384:phase_error[15:0];
   assign pe_write=rotated_valid;assign pe_slot=r_symbol[SLOT-1:0];
  end
 end else begin:g_bpsk_decision
  wire signed [18:0] decision_real=$signed(rotated_re)+$signed(rotated_im),decision_im=$signed(rotated_im)-$signed(rotated_re);
  assign decision=decision_real<0;
  wire signed [19:0] phase_error=decision[0]?-$signed({decision_im[18],decision_im}):$signed({decision_im[18],decision_im});
  assign pe_value=phase_error>20'sd16384 ? 16'sd16384:phase_error< -20'sd16384 ? -16'sd16384:phase_error[15:0];
  assign pe_write=rotated_valid;assign pe_slot=r_symbol[SLOT-1:0];
  wire target=r_training?r_label[0]:decision[0];
  assign target_re=(target?-19'sd16384:19'sd16384)-(b_s19_t'(rotated_re));
  assign target_im=(target?-19'sd16384:19'sd16384)-(b_s19_t'(rotated_im));
 end
 endgenerate
 localparam int LABEL_BITS=ORDER==8&&PI4?2:BITS;
 wire [LABEL_BITS-1:0] label;
 generate
 if(ORDER>=16) begin:g_qam16_label
  // Quadrant-differential: gray_inverse(quadrant-previous) and the in-quadrant bits.
  logic [1:0] previous;
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) begin
   if(rotated_valid) previous<=decision[BITS-1:BITS-2];
   if(start) previous<=0;
  end
  wire [1:0] step=decision[BITS-1:BITS-2]-previous;
  assign label={step[1],step[1]^step[0],decision[BITS-3:0]};
 end else if(ORDER==8&&PI4) begin:g_pi4_label
  // Odd index steps 2*gray(label)+1; cleared when a frame starts.
  logic [2:0] previous;
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) begin
   if(rotated_valid) previous<=decision;
   if(start) previous<=0;
  end
  // Bits 2:1 of decision-(previous+1), with the borrow from bit 0.
  wire [2:0] next_previous=previous+3'd1;
  wire [1:0] step=decision[2:1]-next_previous[2:1]-{1'b0,~decision[0]&next_previous[0]};
  assign label={step[1],step[1]^step[0]};
 end else if(ORDER==8&&!DIFFERENTIAL) begin:g_psk8_label
  assign label=decision;
 end else if(ORDER==8) begin:g_psk8_differential_label
  // label = gray_inverse((index-previous) mod 8); cleared when a frame starts.
  logic [2:0] previous;
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) begin
   if(rotated_valid) previous<=decision;
   if(start) previous<=0;
  end
  wire [2:0] step=decision-previous;
  assign label={step[2],step[2]^step[1],step[2]^step[1]^step[0]};
 end else if(ORDER==4&&!DIFFERENTIAL) begin:g_qpsk_label
  assign label=decision;
 end else if(ORDER==4) begin:g_qpsk_differential_label
  // label = gray_inverse((index-previous) mod 4); cleared when a frame starts.
  logic [1:0] previous;
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) begin
   if(rotated_valid) previous<=decision;
   if(start) previous<=0;
  end
  wire [1:0] step=decision-previous;
  assign label={step[1],step[1]^step[0]};
 end else begin:g_bpsk_label
  // Differential BPSK label; cleared when a frame starts.
  logic previous;
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) begin
   if(rotated_valid) previous<=decision[0];
   if(start) previous<=0;
  end
  assign label=decision^previous;
 end
 endgenerate
 (* KEEP="TRUE" *) logic signed [18:0] gain_target_re,gain_target_im;
 logic signed [17:0] gain_value_re,gain_value_im;
 logic signed [23:0] gain_coefficient;
 logic [24:0] gain_for_error[0:GE_STAGE-1];
 logic signed [15:0] gain_error_reg;
 logic signed [49:0] gain_product;
 generate
 if(ORDER<16) begin:g_gain_error
  // Keep this sum in fabric. As a DSP48 cascade (PCIN+(A*B2)') the sum becomes a
  // dedicated zero-delay PCOUT-PCIN net: hold slack then depends only on the clock
  // skew between the two DSP sites and the router has no fabric route to lengthen,
  // which produced a -0.058 ns hold violation on psk8_fb_rx that no placement
  // directive could fix. Width, truncation and rounding below are unchanged.
  (* use_dsp = "no" *) logic signed [38:0] gain_error_sum_reg;
  wire signed [38:0] gain_error_sum=(b_s39_t'(gain_error_re)+b_s39_t'(gain_error_im))*39'sd2;
  // Same enable as the shared pipeline registers (ce outside reset).
  always_ff @(posedge clk) if(rst!=RESET_ACTIVE&&ce) gain_error_sum_reg<=gain_error_sum;
  wire gain_round_up=gain_error_sum_reg[GE_SHIFT-1]&&((|gain_error_sum_reg[GE_SHIFT-2:0])||gain_error_sum_reg[GE_SHIFT]);
  wire signed [24:0] gain_error_rounded=b_s25_t'($signed(gain_error_sum_reg[38:GE_SHIFT]))+$signed({24'd0,gain_round_up});
  assign gain_error=gain_error_rounded>25'sd16384 ? 16'sd16384:gain_error_rounded< -25'sd16384 ? -16'sd16384:gain_error_rounded[15:0];
 end
 endgenerate
 assign done=m_valid&&m_ready&&m_last;
 wire symbol_start=busy&&subcycle==0&&can_start;
 generate
 if(TIMING_LOOP) begin:g_timing
  // Early-late detector: catch-up correction and its per-symbol metadata.
  logic signed [31:0] correction_state;
  (* ram_style="registers",ramstyle="logic" *) logic signed [31:0] meta_correction[0:7];
  logic signed [17:0] early_re[0:7],early_im[0:7],mid_re[0:7],mid_im[0:7];
  logic signed [31:0] pending_timing[0:LOOP_DELAY-1];
  logic signed [49:0] inverse_product;
  logic signed [63:0] inverse_scaled;
  // Constant multiplies by QAM_TE_MUL: keep them in the DSP slice. Left to the
  // fabric Vivado builds an eight-partial-product carry chain of 19 levels.
  (* use_dsp="yes" *) logic [39:0] scaled_low,scaled_high;
  logic [19:0] inverse_quotient;
  logic inverse_half,inverse_sticky;
  logic [20:0] inverse_square;
  logic [4:0] timing_valid_pipe;
  logic [SLOT-1:0] timing_symbol[0:4];
  logic signed [36:0] timing_product_re,timing_product_im;
  logic signed [38:0] timing_sum;
  // QAM64: 2/Es = 3121 keeps inverse_square below 2^17, so the product needs 60 bits.
  localparam int TN_WIDTH=ORDER==64?60:61;
  logic signed [TN_WIDTH-1:0] timing_normalized;
  wire timing_round_up=timing_normalized[TE_SHIFT-1]&&((|timing_normalized[TE_SHIFT-2:0])||timing_normalized[TE_SHIFT]);
  wire signed [34:0] timing_rounded=b_s35_t'($signed(timing_normalized[TN_WIDTH-1:TE_SHIFT]))+$signed({34'd0,timing_round_up});
  wire signed [17:0] bounded_timing_error=timing_rounded>35'sd32768 ? 18'sd32768:timing_rounded< -35'sd32768 ? -18'sd32768:timing_rounded[17:0];
  logic signed [17:0] timing_error;
  logic signed [29:0] timing_delta;
  wire signed [18:0] late_difference_re=$signed(a_re)-$signed(early_re[a_slot]),late_difference_im=$signed(a_im)-$signed(early_im[a_slot]);
  assign new_correction=correction_state+pending_timing[feedback_slot];
  always_ff @(posedge clk) begin
   if(rst==RESET_ACTIVE) timing_valid_pipe<=0;
   else if(ce) begin
    timing_valid_pipe<={timing_valid_pipe[3:0],a_valid&&a_tag[1:0]==2};
    timing_symbol[0]<=a_symbol[SLOT-1:0];for(integer j=1;j<5;j=j+1) timing_symbol[j]<=timing_symbol[j-1];
    timing_product_re<=late_difference_re*mid_re[a_slot];timing_product_im<=late_difference_im*mid_im[a_slot];
    timing_sum<=(b_s39_t'(timing_product_re)+b_s39_t'(timing_product_im))*39'sd2;
    timing_normalized<=timing_sum*$signed({1'b0,inverse_square});
    timing_error<=bounded_timing_error;
    timing_delta<=timing_error*30'sd3932;
    if(timing_valid_pipe[4]) pending_timing[timing_symbol[4]]<=b_s32_t'(b_round(b_s64_t'(timing_delta),17));
    if(a_valid) case(a_tag[1:0])
     0:begin early_re[a_slot]<=a_re;early_im[a_slot]<=a_im;end
     1:begin mid_re[a_slot]<=a_re;mid_im[a_slot]<=a_im;end
     default:begin end
    endcase
    if(initialization==INIT_STEPS) inverse_product<=$signed({1'b0,initial_gain})*$signed({1'b0,initial_gain});
    if(ORDER>=16) begin
     // 2/Es = round(2^17/Es) in Q16 (Es = 10 or 42), folded in before a nearest-even
     // rounding by 44, split into quotient/half/sticky and the increment (gain^2*13107 < 2^62).
     if(initialization==init_t'(4)) begin
      scaled_low<=$unsigned(inverse_product[24:0])*QAM_TE_MUL;scaled_high<=$unsigned(inverse_product[49:25])*QAM_TE_MUL;
     end
     if(initialization==init_t'(3)) inverse_scaled<=b_s64_t'({scaled_high,25'd0})+b_s64_t'({24'd0,scaled_low});
     if(initialization==init_t'(2)) begin inverse_quotient<=inverse_scaled[63:44];inverse_half<=inverse_scaled[43];inverse_sticky<=|inverse_scaled[42:0];end
     if(initialization==init_t'(1)) inverse_square<=b_s21_t'(inverse_quotient)+b_s21_t'(inverse_half&&(inverse_sticky||inverse_quotient[0]));
    end else if(initialization==init_t'(1)) inverse_square<=b_s21_t'(b_round(b_s64_t'(inverse_product),28));
    if(rotated_valid) m_correction<=meta_correction[r_slot];
    if(symbol_start) begin correction_state<=new_correction;meta_correction[next_symbol[2:0]]<=new_correction;end
    if(start) begin correction_state<=0;for(integer j=0;j<LOOP_DELAY;j=j+1) pending_timing[j]<=0;end
   end
  end
 end else begin:g_fixed_timing
  // No timing loop: sampling follows the acquired delay.
  assign new_correction=0;
  assign m_correction=0;
 end
 endgenerate
 always_ff @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin busy<=0;m_valid<=0;error_valid_pipe<=0;initialization<=0;gain_fresh<=0;end
  else if(ce) begin
   new_gain<=unclipped_gain<1?25'd1:(unclipped_gain>16777216?25'd16777216:b_s25_t'(unclipped_gain));
   selected_gain_ready<=gain_ready[next_symbol[2:0]];gain_fresh<=!(symbol_start||start);
   m_valid<=rotated_valid;
   error_valid_pipe<={error_valid_pipe[GE_STAGE-1:0],rotated_valid};
   error_symbol[0]<=r_symbol[2:0];for(integer j=1;j<=GE_STAGE;j=j+1) error_symbol[j]<=error_symbol[j-1];
   gain_target_re<=target_re;gain_target_im<=target_im;gain_value_re<=rotated_re;gain_value_im<=rotated_im;
   gain_error_re<=gain_target_re*gain_value_re;gain_error_im<=gain_target_im*gain_value_im;
   gain_for_error[0]<=meta_gain[r_slot];for(integer j=1;j<GE_STAGE;j=j+1) gain_for_error[j]<=gain_for_error[j-1];
   gain_error_reg<=gain_error;
   gain_coefficient<=b_s24_t'(gain_error_reg)*24'sd262;
   gain_product<=gain_coefficient*$signed({1'b0,gain_for_error[GE_STAGE-1]});
   if(error_valid_pipe[GE_STAGE]) begin
    pending_gain_delta[error_symbol[GE_STAGE]]<=b_s16_t'(b_round(b_s64_t'(gain_product),32));gain_ready[error_symbol[GE_STAGE]]<=1;
   end
   if(error_valid_pipe[PE_STAGE]) begin
    feedback_ready[error_symbol[PE_STAGE][SLOT-1:0]]<=1;
    pending_phase[error_symbol[PE_STAGE][SLOT-1:0]]<=b_s32_t'(pe_for_phase)*PHASE_GAIN;
   end
   if(pe_write) begin
    if(ORDER>=16) pe_held<=pe_value;
    else pending_pe[pe_slot]<=pe_value;
   end
   if(ORDER>=16&&error_valid_pipe[PE_STAGE]) pending_pe[error_symbol[PE_STAGE][SLOT-1:0]]<=pe_held;
   if(rotated_valid) begin
    m_bit<=label;m_index<=decision;m_last<=r_symbol==count-1'b1;
    m_re<=rotated_re;m_im<=rotated_im;m_phase<=meta_phase[r_slot]+meta_frequency[r_slot];m_frequency<=meta_frequency[r_slot];m_gain<=meta_gain[r_slot];
   end
   if(initialization!=0) begin
    initialization<=initialization-1'b1;
    if(initialization==1) busy<=1;
   end
   if(done) busy<=0;
   if(busy) begin
    if(symbol_start) begin
     active_symbol<=next_symbol;active_position<=next_position;next_symbol<=next_symbol+1'b1;subcycle<=1;base_position<=base_position+32'sd524288;
     phase_state<=new_phase+new_frequency;frequency_state<=new_frequency;gain_state<=new_gain;
     meta_phase[next_symbol[2:0]]<=new_phase;meta_frequency[next_symbol[2:0]]<=new_frequency;meta_gain[next_symbol[2:0]]<=new_gain;
     feedback_ready[feedback_slot]<=0;gain_ready[next_symbol[2:0]]<=0;
    end else if(subcycle!=0&&(subcycle!=1||can_read)) subcycle<=subcycle+1'b1;
   end
   if(start) begin
    initialization<=INIT_STEPS;base_position<=delay+(32'sd32<<<16);next_symbol<=0;subcycle<=0;phase_state<=initial_phase;frequency_state<=initial_frequency;gain_state<=initial_gain;
    feedback_ready<='1;gain_ready<=8'hff;
    for(integer j=0;j<8;j=j+1) pending_gain_delta[j]<=0;
    for(integer j=0;j<LOOP_DELAY;j=j+1) begin pending_pe[j]<=0;pending_phase[j]<=0;end
   end
  end
 end
wire [18-BITS:0] unused_rotated_tag=rotated_tag[31:13+BITS];
endmodule
