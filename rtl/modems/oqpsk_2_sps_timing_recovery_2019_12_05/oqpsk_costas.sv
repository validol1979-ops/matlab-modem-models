// OQPSK split Costas data pass (oqpsk_fixed.receive): the I instant is rotated by thetaI
// and contributes `re`, the Q instant is rotated by thetaQ = thetaI + 4*frequency and
// contributes `im`; the label is {im < 0, (re < 0) ^ (im < 0)}. Loop error
// eI = angle(rI*tI), eQ = angle(-j rQ*tQ) clipped to 0.5 rad, error = (eI + eQ) >> 1,
// applied LOOP_DELAY symbols late (default 8): loop_freq += round(error*7, 15),
// loop_phase += loop_freq + round(error*1311, 15), thetaI = phase0 + slope*k + loop_phase
// (all 32-bit wraps). Input: sample pairs zI(k), zQ(k) from cpm_samples lane 0 in order;
// zI(k) is only requested once the error of symbol k-LOOP_DELAY is stored, so error_memory is
// always ready. The loop update after a pair takes six clocks (error, products,
// increments, frequency, phase and angle), the two CORDIC errors 21 more. The RX gate
// also accounts for sample-reader latency before starting the next dependent symbol.
// Everything advances with ce (the output stall);
// start clears the loop state one clock after phase0 is written and sets theta_base.
module oqpsk_costas #(parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",
 parameter int LOOP_DELAY=8)(
 input logic clk,rst,ce,start,
 input logic signed [31:0] phase0,slope,frequency,
 input logic [11:0] symbol_count,
 input logic [383:0] training,          // label k at training[2k+1:2k]
 input logic s_valid,s_sel,             // sample reader lane 0: s_sel 0 = zI, 1 = zQ
 input logic [11:0] s_symbol,
 input logic signed [17:0] s_re,s_im,
 output logic m_valid,m_last,
 output logic [1:0] m_label,
 output logic signed [17:0] m_re,m_im,
 output logic [11:0] error_count,       // number of symbol errors written since start
 output logic done
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 // The error ring holds at most 16 distinct symbol ages. Smaller delays are legal;
 // the RX readiness gate inserts bubbles until the requested error has been stored.
 initial if(LOOP_DELAY<1||LOOP_DELAY>16) $fatal(1,"[PARAMETER] OQPSK LOOP_DELAY must be in 1..16");
 // Loop gains 0.04 (1311) and 0.0002 (7) in Q15; error limit 0.5 rad in 2^-32 turns.
 localparam int TRAIN_KNOWN=188;
 localparam logic signed [31:0] LIMIT=32'sd341782637;
 wire reset_now=rst==RESET_ACTIVE;
 wire pair=s_valid&&s_sel;
 // Loop state and the symbol pipeline (t0 error, t1 products, t2 increments, t3 frequency,
 // t4 phase and angle, t5 the Q rotator input).
 logic signed [31:0] error_memory[0:15];
 logic signed [31:0] loop_phase,loop_frequency,theta_base;
 logic [5:0] t_stage;
 logic signed [31:0] error_q,frequency_step,phase_step;
 logic signed [42:0] frequency_product,phase_product;
 // zI and zQ each held between the pair and then held again (the next pair overwrites
 // hold_i_*/hold_q_* four clocks after the first). zI feeds the thetaI rotation, zQ the
 // thetaQ rotation.
 logic signed [17:0] zi_re,zi_im,hold_i_re,hold_i_im,hold2_i_re,hold2_i_im,hold_q_re,hold_q_im,hold2_q_re,hold2_q_im;
 logic [11:0] hold_symbol,hold2_symbol;
 logic s1_valid;
 logic signed [17:0] s1_re,s1_im;
 logic [11:0] s1_symbol;
 logic s1_sel;
 logic [11:0] s1_phase;
 wire [11:0] theta_i_index=12'((theta_base+loop_phase)>>>20);
 wire [11:0] theta_q_index=12'((theta_base+loop_phase+(frequency<<<2))>>>20);
 logic [11:0] theta_q_hold;
 // Rotator: rI and rQ on consecutive clocks, tag = {19'd0, sel, symbol}.
 wire rot_valid;
 wire signed [17:0] rot_re,rot_im;
 wire [31:0] rot_tag;
 wire r_sel=rot_tag[12];
 wire [11:0] r_symbol=rot_tag[11:0];
 bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
  clk,rst,ce,s1_valid,s1_re,s1_im,s1_phase,25'd1048576,{19'd0,s1_sel,s1_symbol},rot_valid,rot_re,rot_im,rot_tag);
 // Decision and the loop targets: label k of the preamble for k < 188, the decision after.
 logic signed [17:0] r_i_re,r_i_im;
 wire decided_i=r_i_re<0,decided_q=rot_im<0;
 wire [1:0] label={decided_q,decided_i^decided_q};
 wire [8:0] train_index=r_symbol<12'(TRAIN_KNOWN)?{r_symbol[7:0],1'b0}:9'd0;
 wire [1:0] train_label=training[train_index+:2];
 wire [1:0] target=r_symbol<12'(TRAIN_KNOWN)?train_label:label;
 wire neg_i=target[1]^target[0],neg_q=target[1];
 // CORDIC errors (eI on the rQ clock, eQ one clock later), 20-bit inputs.
 logic c_valid,eq_valid;
 logic signed [19:0] c_x,c_y,eq_x,eq_y;
 logic [3:0] eq_symbol;
 logic [4:0] c_tag;
 wire angle_valid;
 wire signed [31:0] angle;
 wire [4:0] angle_tag;
 bpsk_cordic #(.WIDTH(20),.TAG_WIDTH(5),.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,ce,c_valid,c_x,c_y,c_tag,angle_valid,angle,angle_tag);
 wire signed [31:0] clipped=angle>LIMIT?LIMIT:angle< -LIMIT?-LIMIT:angle;
 logic signed [31:0] e_i_hold;
 always_ff @(posedge clk) begin
  if(reset_now) begin
   t_stage<=0;s1_valid<=0;c_valid<=0;eq_valid<=0;m_valid<=0;m_last<=0;done<=0;error_count<=0;
   loop_phase<=0;loop_frequency<=0;theta_base<=0;zi_re<=0;zi_im<=0;
   hold_i_re<=0;hold_i_im<=0;hold_symbol<=0;hold2_i_re<=0;hold2_i_im<=0;hold2_symbol<=0;
   hold_q_re<=0;hold_q_im<=0;hold2_q_re<=0;hold2_q_im<=0;
   r_i_re<=0;r_i_im<=0;e_i_hold<=0;theta_q_hold<=0;
  end else if(ce) begin
   t_stage<={t_stage[4:0],pair};
   done<=0;m_valid<=0;
   // Pair: keep zI, then (on zQ) use the error of symbol k-LOOP_DELAY.
   if(s_valid&&!s_sel) begin zi_re<=s_re;zi_im<=s_im;end
   if(pair) begin
    error_q<=s_symbol>=12'(LOOP_DELAY) ?error_memory[4'(s_symbol-12'(LOOP_DELAY))]:32'sd0;
    hold_i_re<=zi_re;hold_i_im<=zi_im;hold_symbol<=s_symbol;
    hold_q_re<=s_re;hold_q_im<=s_im;
   end
   if(t_stage[0]) begin frequency_product<=b_s43_t'(error_q)*43'sd7;phase_product<=b_s43_t'(error_q)*43'sd1311;end
   if(t_stage[1]) begin
    frequency_step<=b_s32_t'(b_round(b_s64_t'(frequency_product),15));phase_step<=b_s32_t'(b_round(b_s64_t'(phase_product),15));
   end
   if(t_stage[2]) loop_frequency<=loop_frequency+frequency_step;
   if(t_stage[3]) begin loop_phase<=loop_phase+loop_frequency+phase_step;hold2_i_re<=hold_i_re;hold2_i_im<=hold_i_im;hold2_symbol<=hold_symbol;hold2_q_re<=hold_q_re;hold2_q_im<=hold_q_im;end
   // Rotation angles; theta_base advances by slope per symbol (theta_i = base + loop).
   if(t_stage[4]) begin
    theta_base<=theta_base+slope;theta_q_hold<=theta_q_index;
    s1_re<=hold2_i_re;s1_im<=hold2_i_im;s1_symbol<=hold2_symbol;s1_sel<=1'b0;s1_phase<=theta_i_index;
   end
   if(t_stage[5]) begin
    s1_re<=hold2_q_re;s1_im<=hold2_q_im;s1_symbol<=hold2_symbol;s1_sel<=1'b1;s1_phase<=theta_q_hold;
   end
   s1_valid<=t_stage[4]||t_stage[5];
   // Rotator output: hold rI, then decide, feed the two CORDIC errors and emit the symbol.
   c_valid<=eq_valid;
   if(eq_valid) begin c_x<=eq_x;c_y<=eq_y;c_tag<={1'b1,eq_symbol};end
   eq_valid<=0;
   if(rot_valid&&!r_sel) begin r_i_re<=rot_re;r_i_im<=rot_im;end
   if(rot_valid&&r_sel) begin
    c_valid<=1;c_tag<={1'b0,r_symbol[3:0]};
    c_x<=neg_i?20'sd0-b_s20_t'(r_i_re):b_s20_t'(r_i_re);
    c_y<=neg_i?20'sd0-b_s20_t'(r_i_im):b_s20_t'(r_i_im);
    eq_valid<=1;eq_symbol<=r_symbol[3:0];
    eq_x<=neg_q?20'sd0-b_s20_t'(rot_im):b_s20_t'(rot_im);
    eq_y<=neg_q?b_s20_t'(rot_re):20'sd0-b_s20_t'(rot_re);
    m_valid<=1;m_re<=r_i_re;m_im<=rot_im;m_label<=label;m_last<=r_symbol==symbol_count-1'b1;
    // The upper tag bits are zero (only sel and the symbol travel through the rotator).
    if(r_symbol==symbol_count-1'b1&&rot_tag[31:13]==0) done<=1;
   end
   // Loop errors: e = (eI + eQ) >> 1 into the 16-entry memory.
   if(angle_valid) begin
    if(!angle_tag[4]) e_i_hold<=clipped;
    else begin
     error_memory[angle_tag[3:0]]<=b_s32_t'((b_s33_t'(e_i_hold)+b_s33_t'(clipped))>>>1);
     error_count<=error_count+12'd1;
    end
   end
  end
  if(!reset_now&&start) begin
   loop_phase<=0;loop_frequency<=0;theta_base<=phase0;error_count<=0;
  end
 end
endmodule
