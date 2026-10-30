// Coherent GMSK data pass (cpm_fixed.receive_coherent): Laurent C0 matched filter and a
// decision-directed phase loop. Input: sample pairs n, n+1 (n even) at positions
// n + delay - 1/2. Symbol k is z_k = sum_{m<48} x[8k+m]*C0[m], rounded by 20 and saturated:
// six sliding accumulators (one per symbol in flight) take both samples of a pair, so the
// filter needs 24 products per clock. Per symbol: loop update with the error of symbol
// k-10 (0 before), theta = phase + frequency*8k + round(frequency*47, 1) + loop phase,
// rotation (bpsk_rotate), axis rotation by (-j)^(k+1), decision beta = (re >= 0), target
// (preamble beta or the decision), loop error angle(r*target) clipped to 0.5 rad (own
// CORDIC), data bit = (beta_k == beta_{k-1}). The loop update after z_k takes five clocks
// (error, products, increments, frequency, phase and angle); the error of symbol k is
// ready about 38 clocks after its last product, before symbol k+10 (40 clocks later at
// the earliest) reads it.
// Everything advances with ce (the output stall); start clears the state for a frame.
module cpm_coherent #(parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables")(
 input logic clk,rst,ce,start,
 input logic signed [31:0] phase0,frequency,centre,   // centre = round(frequency*47, 1)
 input logic [11:0] symbol_count,
 input logic [191:0] training,
 input logic s_valid,
 input logic [2:0] s_index,   // n mod 8 of the pair's first sample
 input logic signed [17:0] s_re0,s_im0,s_re1,s_im1,
 output logic m_valid,m_last,m_bit,
 output logic signed [18:0] m_value,
 output logic done
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 `include "bpsk_constants.svh"
 localparam int SLOTS=6;
 // Loop gains 0.04 (1311) and 0.0002 (7) in Q15; error limit 0.5 rad in 2^-32 turns.
 localparam logic signed [31:0] LIMIT=32'sd341782637;
 wire reset_now=rst==RESET_ACTIVE;
 // Stage 0: slot bookkeeping on each pair.
 logic [SLOTS-1:0] active;
 logic [5:0] tap[0:SLOTS-1];
 logic [11:0] slot_symbol[0:SLOTS-1];
 logic [2:0] next_slot;
 logic [11:0] next_symbol;
 wire start_symbol=s_valid&&s_index==3'd0&&next_symbol<symbol_count;
 logic [SLOTS-1:0] starting;
 logic signed [43:0] sum_re[0:SLOTS-1],sum_im[0:SLOTS-1];
 // Stage 1: coefficients and samples; stage 2: products; stage 3: accumulation.
 logic p1_valid,p2_valid;
 logic [SLOTS-1:0] p1_use,p1_first,p1_last,p2_use,p2_first,p2_last;
 logic [11:0] p1_symbol[0:SLOTS-1],p2_symbol[0:SLOTS-1];
 logic signed [17:0] p1_re0,p1_im0,p1_re1,p1_im1;
 logic signed [17:0] c_a[0:SLOTS-1],c_b[0:SLOTS-1];
 logic signed [36:0] prod_re[0:SLOTS-1],prod_im[0:SLOTS-1];
 (* use_dsp="no" *) logic signed [43:0] acc_re[0:SLOTS-1],acc_im[0:SLOTS-1];
 // Symbol emission (z_k) and the symbol pipeline.
 logic z_valid,sum_valid;
 logic signed [43:0] z_sum_re,z_sum_im;
 logic [11:0] sum_symbol;
 logic signed [17:0] z_re,z_im;
 logic [11:0] z_symbol;
 logic signed [31:0] error_memory[0:15];
 logic signed [31:0] loop_phase,loop_frequency,theta_base;
 logic [4:0] t_stage;
 logic signed [31:0] error_q,frequency_step,phase_step;
 logic signed [42:0] frequency_product,phase_product;
 // z_k is held twice: symbol k+1 can arrive four clocks after symbol k.
 logic signed [17:0] hold_re,hold_im,hold2_re,hold2_im;
 logic [11:0] hold_symbol,hold2_symbol;
 logic s1_valid;
 logic signed [17:0] s1_re,s1_im;
 logic [11:0] s1_symbol;
 logic [11:0] theta;          // rotation angle, table index (top 12 bits)
 wire signed [31:0] error_now=z_symbol>=12'd10 ?error_memory[4'(z_symbol-12'd10)]:32'sd0;
 wire rotated_valid;wire signed [17:0] rotated_re,rotated_im;wire [31:0] rotated_tag;
 bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
  clk,rst,ce,s1_valid,s1_re,s1_im,theta,25'd1048576,{20'd0,s1_symbol},rotated_valid,rotated_re,rotated_im,rotated_tag);
 wire [11:0] r_symbol=rotated_tag[11:0];
 // Axis rotation by (-j)^(k+1): 1 -> (im,-re), 2 -> (-re,-im), 3 -> (-im,re), 0 -> (re,im).
 wire [1:0] axis_index=2'(r_symbol+12'd1);
 wire signed [18:0] ext_re=b_s19_t'(rotated_re),ext_im=b_s19_t'(rotated_im);
 wire signed [18:0] axis_re=axis_index==2'd1 ?ext_im:axis_index==2'd2 ?19'sd0-ext_re:axis_index==2'd3 ?19'sd0-ext_im:ext_re;
 wire signed [18:0] axis_im=axis_index==2'd1 ?19'sd0-ext_re:axis_index==2'd2 ?19'sd0-ext_im:axis_index==2'd3 ?ext_re:ext_im;
 wire decided=axis_re>=0;
 // Preamble targets beta_k = product of the label signs up to k.
 logic known;
 wire known_next=r_symbol==0?training[0]:known~^training[r_symbol[7:0]];
 wire target=r_symbol<12'd188 ?known_next:decided;
 logic previous;
 logic c_valid;
 logic signed [19:0] c_x,c_y;
 logic [3:0] c_tag;
 wire angle_valid;wire signed [31:0] angle;wire [3:0] angle_tag;
 bpsk_cordic #(.WIDTH(20),.TAG_WIDTH(4),.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,ce,c_valid,c_x,c_y,c_tag,angle_valid,angle,angle_tag);
 wire signed [31:0] clipped=angle>LIMIT?LIMIT:angle< -LIMIT?-LIMIT:angle;
 always_comb for(integer s=0;s<SLOTS;s=s+1) begin
  starting[s]=start_symbol&&next_slot==3'(s);
  sum_re[s]=(p2_first[s]?44'sd0:acc_re[s])+b_s44_t'(prod_re[s]);sum_im[s]=(p2_first[s]?44'sd0:acc_im[s])+b_s44_t'(prod_im[s]);
 end
 always_ff @(posedge clk) begin
  if(reset_now) begin
   p1_valid<=0;p2_valid<=0;z_valid<=0;sum_valid<=0;s1_valid<=0;t_stage<=0;c_valid<=0;m_valid<=0;done<=0;active<=0;
  end else if(ce) begin
   done<=0;
   // Stage 0: per-slot tap index of this pair; a new symbol starts at n = 8k.
   p1_valid<=s_valid;p1_re0<=s_re0;p1_im0<=s_im0;p1_re1<=s_re1;p1_im1<=s_im1;
   for(integer s=0;s<SLOTS;s=s+1) begin
    p1_use[s]<=s_valid&&(active[s]||starting[s]);p1_first[s]<=starting[s];
    p1_last[s]<=s_valid&&active[s]&&!starting[s]&&tap[s]==6'd46;
    p1_symbol[s]<=starting[s]?next_symbol:slot_symbol[s];
    c_a[s]<=c0_coefficient(starting[s]?0:int'(tap[s]));c_b[s]<=c0_coefficient(starting[s]?1:int'(tap[s])+1);
    if(s_valid) begin
     if(starting[s]) begin active[s]<=1;tap[s]<=6'd2;slot_symbol[s]<=next_symbol;end
     else if(active[s]) begin tap[s]<=tap[s]+6'd2;if(tap[s]==6'd46) active[s]<=0;end
    end
   end
   if(start_symbol) begin next_symbol<=next_symbol+1'b1;next_slot<=next_slot==3'(SLOTS-1)?3'd0:next_slot+1'b1;end
   // Stage 1 -> 2: products of the two samples with their taps.
   p2_valid<=p1_valid;p2_use<=p1_use;p2_first<=p1_first;p2_last<=p1_last;
   for(integer s=0;s<SLOTS;s=s+1) begin
    p2_symbol[s]<=p1_symbol[s];
    prod_re[s]<=b_s37_t'(p1_re0)*b_s37_t'(c_a[s])+b_s37_t'(p1_re1)*b_s37_t'(c_b[s]);
    prod_im[s]<=b_s37_t'(p1_im0)*b_s37_t'(c_a[s])+b_s37_t'(p1_im1)*b_s37_t'(c_b[s]);
   end
   // Stage 3: accumulation; the slot that takes tap 46/47 emits z_k.
   // The finished sum is rounded and saturated one clock later.
   sum_valid<=0;
   for(integer s=0;s<SLOTS;s=s+1) if(p2_valid&&p2_use[s]) begin
    acc_re[s]<=sum_re[s];acc_im[s]<=sum_im[s];
    if(p2_last[s]) begin sum_valid<=1;sum_symbol<=p2_symbol[s];z_sum_re<=sum_re[s];z_sum_im<=sum_im[s];end
   end
   z_valid<=sum_valid;
   if(sum_valid) begin
    z_symbol<=sum_symbol;z_re<=b_sat(b_round(b_s64_t'(z_sum_re),20));z_im<=b_sat(b_round(b_s64_t'(z_sum_im),20));
   end
   // Symbol stage: loop update with the error of k-10, rotation angle.
   // t0: error of k-10; t1: products; t2: rounded increments; t3: frequency; t4: phase and angle.
   t_stage<={t_stage[3:0],z_valid};
   if(z_valid) begin error_q<=error_now;hold_re<=z_re;hold_im<=z_im;hold_symbol<=z_symbol;end
   if(t_stage[0]) begin frequency_product<=b_s43_t'(error_q)*43'sd7;phase_product<=b_s43_t'(error_q)*43'sd1311;end
   if(t_stage[1]) begin
    frequency_step<=b_s32_t'(b_round(b_s64_t'(frequency_product),15));phase_step<=b_s32_t'(b_round(b_s64_t'(phase_product),15));
   end
   if(t_stage[2]) loop_frequency<=loop_frequency+frequency_step;
   if(t_stage[3]) begin loop_phase<=loop_phase+loop_frequency+phase_step;hold2_re<=hold_re;hold2_im<=hold_im;hold2_symbol<=hold_symbol;end
   s1_valid<=t_stage[4];
   if(t_stage[4]) begin
    theta<=12'((theta_base+loop_phase)>>>20);theta_base<=theta_base+(frequency<<<3);
    s1_re<=hold2_re;s1_im<=hold2_im;s1_symbol<=hold2_symbol;
   end
   // After the rotator: decision, target, loop error input, output.
   c_valid<=rotated_valid;
   m_valid<=0;
   if(rotated_valid) begin
    known<=known_next;previous<=decided;
    c_x<=target?b_s20_t'(axis_re):20'sd0-b_s20_t'(axis_re);c_y<=target?b_s20_t'(axis_im):20'sd0-b_s20_t'(axis_im);c_tag<=r_symbol[3:0];
    m_valid<=1;m_value<=axis_re;m_bit<=decided==(r_symbol==0?1'b1:previous);m_last<=r_symbol==symbol_count-1'b1;
    // The upper tag bits are zero (only the symbol travels through the rotator).
    if(r_symbol==symbol_count-1'b1&&rotated_tag[31:12]==0) done<=1;
   end
   if(angle_valid) error_memory[angle_tag]<=clipped;
  end
  if(!reset_now&&start) begin
   active<=0;next_slot<=0;next_symbol<=0;loop_phase<=0;loop_frequency<=0;
   theta_base<=phase0+centre;
  end
 end
endmodule
