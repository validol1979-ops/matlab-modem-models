// Public-preamble acquisition: cyclic energy, three symbol offsets, phase fit,
// residual score and coherent gain. No payload labels enter this module.
// ORDER=2: BPSK (+-0.5+-0.5j); ORDER=4: diagonal QPSK, AMPLITUDE per axis. The training
// label of each request travels in tag bits [8+:BITS]; the per-symbol phase is
// angle(z*conj(a+jb)) with the axis signs (a,b) of the label. ORDER=8: unit 8-PSK, the
// phase is angle(z) minus the target angle (2k+1)*2^28 and the coherent amplitude is the
// real part after rotating by that angle as well.
// ORDER=16: QAM16, label levels (a,b) in +-1/+-3: phase angle(z*conj(a+jb)); amplitude
// divide(2*sum(a*re+b*im), sum(a^2+b^2)) with the shared divider. ORDER=64: the same with
// levels +-1..+-7 (label in tag bits 8..13).
// BLOCK_FIT (QAM16 with equalizers): the fit terms are summed over 8 blocks of 16
// symbols and only the block sums enter the CORDIC; the unwrapping, the weighted sums
// and the residual run over the 8 block phases (psk_fixed.fit_blocks).
module bpsk_acquire #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter int ORDER=2,
 parameter int AMPLITUDE=ORDER==8?32768:ORDER==4?23170:16384,parameter bit BLOCK_FIT=0
)(
 input logic clk,rst,start,
 input logic [335:0] energies,
 // Training labels of the fit symbols 32..159 only (label k-32 at [(k-32)*BITS +: BITS]).
 input logic [128*(ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1)-1:0] training,
 output logic busy,done,confidence,
 output logic signed [31:0] delay,frequency,phase,
 output logic [24:0] gain,
 output logic [63:0] score,
 output logic q_valid,
 output logic signed [31:0] q_position,
 output logic [31:0] q_tag,
 input logic a_valid,
 input logic signed [17:0] a_re,a_im,
 input logic [31:0] a_tag
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 typedef enum logic [4:0] {IDLE,ENERGY,DFT,DFT_DRAIN,ANGLE_START,ANGLE_WAIT,CANDIDATE,
  FIT_SEND,FIT_WAIT,DIV_START,DIV_WAIT,INTERCEPT,SCORE_SEND,SCORE_WAIT,SCORE_PICK,NEXT_CANDIDATE,
  GAIN_SEND,GAIN_WAIT,GAIN_SCALE,AMP_DIV_WAIT,GAIN_ABS,GAIN_DIV_START,GAIN_DIV_WAIT,COMPLETE} state_t;
 state_t state;
 logic [3:0] e_index;
 logic [7:0] send_index;
 logic [1:0] candidate_index;
 logic signed [31:0] candidate_delay,base_delay;
 logic [63:0] best_score;
 logic [63:0] candidate_score;
 logic signed [31:0] best_delay,best_slope,best_phase;
 logic signed [17:0] energy[0:7];
 logic [41:0] raw_energy[0:7];
 logic signed [35:0] dft_product_re,dft_product_im;
 logic signed [39:0] dft_re,dft_im;
 logic dft_product_valid;
 wire signed [17:0] dft_cos[0:7],dft_sin[0:7];
 assign dft_cos[0]=18'sd131071;assign dft_cos[1]=18'sd92682;assign dft_cos[2]=0;assign dft_cos[3]=-18'sd92682;
 assign dft_cos[4]=18'sh20000;assign dft_cos[5]=-18'sd92682;assign dft_cos[6]=0;assign dft_cos[7]=18'sd92682;
 assign dft_sin[0]=0;assign dft_sin[1]=18'sd92682;assign dft_sin[2]=18'sd131071;assign dft_sin[3]=18'sd92682;
 assign dft_sin[4]=0;assign dft_sin[5]=-18'sd92682;assign dft_sin[6]=18'sh20000;assign dft_sin[7]=-18'sd92682;
 logic cordic_valid;
 logic signed [48:0] cordic_x,cordic_y;
 logic [15:0] cordic_tag;
 wire angle_valid;
 wire signed [31:0] angle;
 wire [15:0] angle_tag;
 localparam int BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
 // Index of the last fitted phase: 8 block phases or 128 symbol phases.
 localparam logic [6:0] FIT_LAST=BLOCK_FIT?7'd7:7'd127;
 // 2*T*2^20: unit gain maps the coherent amplitude a*re+b*im to the symbol value.
 localparam longint GAIN_NUMERATOR=ORDER==8?longint'(AMPLITUDE)<<20:longint'(AMPLITUDE)<<21;
 wire signed [48:0] fit_x,fit_y;
 // Requests cover symbols 32..159: the 128-entry label table is indexed by send_index
 // directly (no +32 and *BITS address arithmetic before the mux).
 wire [BITS-1:0] fit_labels[0:127];
 genvar k;
 generate
 for(k=0;k<128;k=k+1) begin:g_fit_labels
  assign fit_labels[k]=training[k*BITS+:BITS];
 end
 endgenerate
 wire [BITS-1:0] request_label=fit_labels[send_index[6:0]];
 wire [2:0] cordic_label;
 // Fit request into the CORDIC; QAM16 registers it one clock after the sample.
 wire fit_request_valid;
 wire [7:0] fit_request_symbol;
 generate
 if(ORDER>=16) begin:g_qam16
  assign cordic_label=0;
  wire signed [3:0] la,lb;
  qam_label_levels #(.ORDER(ORDER)) fit_levels(a_tag[8+:BITS],la,lb);
  // z*conj(a+jb) = (a*re+b*im) + j(a*im-b*re), registered before the CORDIC: the
  // level scaling and sum would otherwise chain into its first stage.
  logic signed [48:0] x_q,y_q;
  logic valid_q;
  logic [7:0] symbol_q;
  always_ff @(posedge clk) begin
   if(rst==RESET_ACTIVE) valid_q<=0;
   else valid_q<=(state==FIT_SEND||state==FIT_WAIT)&&a_valid;
   x_q<=b_s49_t'(qam_scale(a_re,la))+b_s49_t'(qam_scale(a_im,lb));
   y_q<=b_s49_t'(qam_scale(a_im,la))-b_s49_t'(qam_scale(a_re,lb));
   symbol_q<=a_tag[7:0];
  end
  if(BLOCK_FIT) begin:g_blocks
   // Block j = symbol/16: the sum is complete with symbol 16j+15 and leaves as request j.
   logic signed [48:0] block_x,block_y;
   logic block_valid;
   logic [7:0] block_symbol;
   always_ff @(posedge clk) begin
    if(rst==RESET_ACTIVE) block_valid<=0;
    else block_valid<=valid_q&&symbol_q[3:0]==4'd15;
    if(valid_q) begin
     block_x<=(symbol_q[3:0]==0?49'sd0:block_x)+x_q;block_y<=(symbol_q[3:0]==0?49'sd0:block_y)+y_q;
     block_symbol<={4'd0,symbol_q[7:4]};
    end
   end
   assign fit_x=block_x;assign fit_y=block_y;assign fit_request_valid=block_valid;assign fit_request_symbol=block_symbol;
  end else begin:g_symbols
   assign fit_x=x_q;assign fit_y=y_q;assign fit_request_valid=valid_q;assign fit_request_symbol=symbol_q;
  end
 end else if(ORDER==8) begin:g_psk8
  assign fit_request_valid=(state==FIT_SEND||state==FIT_WAIT)&&a_valid;assign fit_request_symbol=a_tag[7:0];
  assign fit_x=b_s49_t'(a_re);assign fit_y=b_s49_t'(a_im);
  assign cordic_label=a_tag[10:8];
 end else if(ORDER==4) begin:g_qpsk
  assign fit_request_valid=(state==FIT_SEND||state==FIT_WAIT)&&a_valid;assign fit_request_symbol=a_tag[7:0];
  assign cordic_label=0;
  // Label bit 1 is the Q sign, bit0^bit1 the I sign.
  wire sa=a_tag[9]^a_tag[8],sb=a_tag[9];
  wire signed [18:0] xr=sa?-$signed({a_re[17],a_re}):$signed({a_re[17],a_re}),xi=sb?-$signed({a_im[17],a_im}):$signed({a_im[17],a_im});
  wire signed [18:0] yi=sa?-$signed({a_im[17],a_im}):$signed({a_im[17],a_im}),yr=sb?-$signed({a_re[17],a_re}):$signed({a_re[17],a_re});
  assign fit_x=b_s49_t'(xr)+b_s49_t'(xi);assign fit_y=b_s49_t'(yi)-b_s49_t'(yr);
 end else begin:g_bpsk
  assign fit_request_valid=(state==FIT_SEND||state==FIT_WAIT)&&a_valid;assign fit_request_symbol=a_tag[7:0];
  wire signed [18:0] sum_sample=$signed(a_re)+$signed(a_im),diff_sample=$signed(a_im)-$signed(a_re);
  assign fit_x=a_tag[8]?-(b_s49_t'(sum_sample)):b_s49_t'(sum_sample);assign fit_y=a_tag[8]?-(b_s49_t'(diff_sample)):b_s49_t'(diff_sample);
  assign cordic_label=0;
 end
 endgenerate
 always_comb begin
  cordic_valid=state==ANGLE_START||fit_request_valid;
  if(state==ANGLE_START) begin cordic_x=b_s49_t'(dft_re);cordic_y=b_s49_t'(dft_im);cordic_tag=16'h8000;end
  else begin
   cordic_x=fit_x;cordic_y=fit_y;
   cordic_tag={5'd0,cordic_label,fit_request_symbol};
  end
 end
 bpsk_cordic #(.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,1'b1,cordic_valid,cordic_x,cordic_y,cordic_tag,angle_valid,angle,angle_tag);
 logic signed [31:0] previous_phase,slope;
 logic signed [39:0] unwrapped;
 // Fit phase: 8-PSK subtracts the target angle carried in the CORDIC tag.
 wire signed [31:0] fit_angle=ORDER==8?angle-$signed({angle_tag[10:8],1'b1,28'd0}):angle;
 wire signed [31:0] phase_difference=fit_angle-previous_phase;
 wire signed [39:0] next_unwrapped=angle_tag[6:0]==0?b_s40_t'(fit_angle):unwrapped+b_s40_t'(phase_difference);
 logic signed [47:0] phase_sum;
 logic signed [55:0] weighted_sum;
 wire signed [8:0] weight=$signed({1'b0,angle_tag[6:0],1'b0})-$signed({2'b0,FIT_LAST});
 // Register the weighted multiplication before the accumulation.
 logic [2:0] fit_valid_pipe,fit_last_pipe;
 logic signed [39:0] fit_phase;
 logic signed [48:0] fit_product;
 logic signed [8:0] fit_weight;
 (* KEEP="TRUE" *) logic signed [26:0] fit_product_low;
 (* KEEP="TRUE" *) logic signed [31:0] fit_product_high;
 logic signed [39:0] phase_memory[0:127];
 logic signed [63:0] intercept;
 // Intercept terms registered in DIV_WAIT. The exact 41-bit product keeps the
 // multiplier narrow; rounding and subtraction follow in INTERCEPT.
 logic signed [63:0] phase_mean;
 logic signed [40:0] slope_product;
 logic divider_start;
 logic signed [63:0] divider_numerator;
 logic [31:0] divider_denominator;
 wire divider_busy,divider_done;
 wire signed [63:0] divider_result;
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE)) divider(clk,rst,divider_start,divider_numerator,divider_denominator,divider_busy,divider_done,divider_result);
 wire signed [40:0] next_slope_product=$signed(divider_result[31:0])*41'sd191;
 logic [3:0] score_valid_pipe,score_last_pipe;
 logic signed [39:0] score_phase;
 logic signed [41:0] score_prediction;
 logic signed [63:0] score_offset;
 (* KEEP="TRUE" *) logic signed [31:0] residual;
 logic [63:0] residual_square,score_sum;
 wire [63:0] score_total=score_sum+residual_square;
 wire gain_rotation_input=(state==GAIN_SEND||state==GAIN_WAIT)&&a_valid;
 logic [1:0] gain_valid_pipe;
 logic signed [31:0] gain_phase_product,gain_rotation_phase;
 wire signed [31:0] gain_theta;
 generate
 if(ORDER==8) begin:g_gain_theta
  // Target angle of the training label, aligned with gain_phase_product.
  logic signed [31:0] theta;
  always_ff @(posedge clk) theta<={a_tag[10:8],1'b1,28'd0};
  assign gain_theta=theta;
 end else begin:g_no_gain_theta
  assign gain_theta=0;
 end
 endgenerate
 logic signed [17:0] gain_re_pipe[0:1],gain_im_pipe[0:1];
 logic [31:0] gain_tag_pipe[0:1];

 wire rotated_valid;
 wire signed [17:0] rotated_re,rotated_im;
 wire [31:0] rotated_tag;
 bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
  clk,rst,1'b1,gain_valid_pipe[1],gain_re_pipe[1],gain_im_pipe[1],gain_rotation_phase[31:20],25'd1048576,gain_tag_pipe[1],rotated_valid,rotated_re,rotated_im,rotated_tag);
 wire signed [31:0] amplitude_term;
 // QAM16: sum of squared training levels over the fit; other orders do not use it.
 wire [13:0] energy_sum;
 // Accumulation strobe and last-symbol flag; QAM16 registers its terms first.
 wire amplitude_valid,amplitude_last;
 generate
 if(ORDER>=16) begin:g_qam16_amplitude
  wire signed [3:0] la,lb;
  qam_label_levels #(.ORDER(ORDER)) amplitude_levels(rotated_tag[8+:BITS],la,lb);
  wire [3:0] ma=la<0?4'(-la):4'(la),mb=lb<0?4'(-lb):4'(lb);
  // Terms are registered before accumulation: the tag leaves a RAM-based shift register.
  logic signed [31:0] term_q;
  logic [6:0] energy_q;
  logic valid_q,last_q;
  always_ff @(posedge clk) begin
   if(rst==RESET_ACTIVE) begin valid_q<=0;last_q<=0;end
   else begin valid_q<=rotated_valid;last_q<=rotated_valid&&rotated_tag[7:0]==127;end
   term_q<=b_s32_t'(qam_scale(rotated_re,la))+b_s32_t'(qam_scale(rotated_im,lb));
   energy_q<=7'(ma)*7'(ma)+7'(mb)*7'(mb);
  end
  assign amplitude_term=term_q;assign amplitude_valid=valid_q;assign amplitude_last=last_q;
  logic [13:0] energy_accumulator;
  always_ff @(posedge clk) begin
   if(state==NEXT_CANDIDATE&&candidate_index==2) energy_accumulator<=0;
   else if(valid_q) energy_accumulator<=energy_accumulator+14'(energy_q);
  end
  assign energy_sum=energy_accumulator;
  wire [23-BITS:0] unused_rotated_tag=rotated_tag[31:8+BITS];
 end else if(ORDER==8) begin:g_psk8_amplitude
  assign energy_sum=14'd1;
  assign amplitude_valid=rotated_valid;assign amplitude_last=rotated_valid&&rotated_tag[7:0]==127;
  // The gain rotation already includes the target angle: the amplitude is the real part.
  assign amplitude_term=b_s32_t'(rotated_re);
  wire [41:0] unused_rotated_tag={rotated_tag[31:8],rotated_im};
 end else if(ORDER==4) begin:g_qpsk_amplitude
  assign energy_sum=14'd1;
  assign amplitude_valid=rotated_valid;assign amplitude_last=rotated_valid&&rotated_tag[7:0]==127;
  wire ra=rotated_tag[9]^rotated_tag[8],rb=rotated_tag[9];
  wire signed [18:0] amp_re=ra?-$signed({rotated_re[17],rotated_re}):$signed({rotated_re[17],rotated_re});
  wire signed [18:0] amp_im=rb?-$signed({rotated_im[17],rotated_im}):$signed({rotated_im[17],rotated_im});
  assign amplitude_term=b_s32_t'(amp_re)+b_s32_t'(amp_im);
  wire [21:0] unused_rotated_tag=rotated_tag[31:10];
 end else begin:g_bpsk_amplitude
  assign energy_sum=14'd1;
  assign amplitude_valid=rotated_valid;assign amplitude_last=rotated_valid&&rotated_tag[7:0]==127;
  wire signed [18:0] rotated_sum=$signed(rotated_re)+$signed(rotated_im);
  assign amplitude_term=rotated_tag[8]?-(b_s32_t'(rotated_sum)):b_s32_t'(rotated_sum);
  wire [22:0] unused_rotated_tag=rotated_tag[31:9];
 end
 endgenerate
 logic signed [31:0] amplitude_sum;
 wire signed [31:0] amplitude_next=amplitude_sum+amplitude_term;
 logic [18:0] amplitude;
 logic signed [18:0] amplitude_signed;
 assign busy=state!=IDLE;
 always_comb begin
  q_valid=state==FIT_SEND||state==GAIN_SEND;
  q_position=(32'sd32<<<16)+(state==GAIN_SEND?best_delay:candidate_delay)+(b_s32_t'({24'd0,send_index})+32'sd32)*32'sd524288;
  q_tag=32'({request_label,send_index});
 end
 always_ff @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin state<=IDLE;done<=0;dft_product_valid<=0;fit_valid_pipe<=0;score_valid_pipe<=0;divider_start<=0;gain_valid_pipe<=0;end
  else begin
   done<=0;divider_start<=0;
   gain_valid_pipe<={gain_valid_pipe[0],gain_rotation_input};
   gain_phase_product<=best_slope*$signed({1'b0,a_tag[7:0]}+9'd32);gain_rotation_phase<=best_phase+gain_phase_product+gain_theta;
   gain_re_pipe[0]<=a_re;gain_im_pipe[0]<=a_im;gain_tag_pipe[0]<=a_tag;
   gain_re_pipe[1]<=gain_re_pipe[0];gain_im_pipe[1]<=gain_im_pipe[0];gain_tag_pipe[1]<=gain_tag_pipe[0];
   dft_product_valid<=state==DFT;
   if(state==DFT) begin dft_product_re<=energy[e_index[2:0]]*dft_cos[e_index[2:0]];dft_product_im<=energy[e_index[2:0]]*dft_sin[e_index[2:0]];end
   if(dft_product_valid) begin dft_re<=dft_re+b_s40_t'(dft_product_re);dft_im<=dft_im+b_s40_t'(dft_product_im);end
   fit_valid_pipe<={fit_valid_pipe[1:0],angle_valid&&!angle_tag[15]};fit_last_pipe<={fit_last_pipe[1:0],angle_tag[6:0]==FIT_LAST};
   fit_product_low<=$signed({1'b0,fit_phase[16:0]})*fit_weight;fit_product_high<=$signed(fit_phase[39:17])*fit_weight;
   fit_product<=b_s49_t'(fit_product_low)+(b_s49_t'(fit_product_high)<<<17);
   if(angle_valid&&!angle_tag[15]) begin
    previous_phase<=fit_angle;unwrapped<=next_unwrapped;phase_memory[angle_tag[6:0]]<=next_unwrapped;
    fit_phase<=next_unwrapped;fit_weight<=weight;
   end
   if(fit_valid_pipe[0]) phase_sum<=phase_sum+b_s48_t'(fit_phase);
   if(fit_valid_pipe[2]) weighted_sum<=weighted_sum+b_s56_t'(fit_product);
   score_valid_pipe<={score_valid_pipe[2:0],state==SCORE_SEND};score_last_pipe<={score_last_pipe[2:0],send_index[6:0]==FIT_LAST};
   if(state==SCORE_SEND) begin
    score_phase<=phase_memory[send_index[6:0]];
    // Blocks: twice the centre 2*(32+16j)+15 = 79+32j against twice the phase.
    score_prediction<=BLOCK_FIT?slope*$signed({1'b0,send_index[2:0],5'd0}+10'd79):slope*$signed({1'b0,send_index}+9'd32);
   end
   score_offset<=BLOCK_FIT?(b_s64_t'(score_phase)-intercept)*64'sd2-b_s64_t'(score_prediction):b_s64_t'(score_phase)-intercept-b_s64_t'(score_prediction);
   residual<=b_s32_t'(b_round(score_offset,BLOCK_FIT?17:16));
   residual_square<=$unsigned(b_s64_t'(residual)*b_s64_t'(residual));
   // Stages: read, offset, rounded residual, square.
   if(score_valid_pipe[3]) score_sum<=score_total;
   if(amplitude_valid) amplitude_sum<=amplitude_next;
   case(state)
    IDLE:if(start) begin
     e_index<=0;best_score<='1;candidate_index<=0;dft_re<=0;dft_im<=0;state<=ENERGY;
     // Parallel, constant-index normalization avoids a 16-way energy mux
     // followed by rounding/clipping on the critical path.
     for(integer j=0;j<8;j=j+1) raw_energy[j]<=energies[j*42+:42];
    end
    ENERGY:begin
     for(integer j=0;j<8;j=j+1) energy[j]<=b_sat(b_round($signed({22'd0,raw_energy[j]}),19));
     state<=DFT;
    end
    DFT:begin e_index<=e_index+1'b1;if(e_index==7) state<=DFT_DRAIN;end
    DFT_DRAIN:state<=ANGLE_START;
    ANGLE_START:state<=ANGLE_WAIT;
    ANGLE_WAIT:if(angle_valid&&angle_tag[15]) begin base_delay<=b_s32_t'(b_round(b_s64_t'(angle),13));state<=CANDIDATE;end
    CANDIDATE:begin
     candidate_delay<=base_delay+$signed({30'd0,candidate_index})*32'sd524288;
     phase_sum<=0;weighted_sum<=0;send_index<=0;score_sum<=0;state<=FIT_SEND;
     if(base_delay+$signed({30'd0,candidate_index})*32'sd524288< -32768||base_delay+$signed({30'd0,candidate_index})*32'sd524288>1081344) state<=NEXT_CANDIDATE;
    end
    FIT_SEND:begin send_index<=send_index+1'b1;if(send_index==127) state<=FIT_WAIT;end
    FIT_WAIT:if(fit_valid_pipe[2]&&fit_last_pipe[2]) state<=DIV_START;
    DIV_START:begin divider_numerator<=b_s64_t'(weighted_sum)*64'sd6;divider_denominator<=BLOCK_FIT?32'd8064:32'd2097024;divider_start<=1;state<=DIV_WAIT;end
    DIV_WAIT:if(divider_done) begin
     slope<=b_s32_t'(divider_result);phase_mean<=b_round(b_s64_t'(phase_sum),BLOCK_FIT?3:7);
     slope_product<=next_slope_product;state<=INTERCEPT;
    end
    INTERCEPT:begin intercept<=phase_mean-b_round(b_s64_t'(slope_product),1);send_index<=0;state<=SCORE_SEND;end
    SCORE_SEND:begin send_index<=send_index+1'b1;if(send_index[6:0]==FIT_LAST) state<=SCORE_WAIT;end
    SCORE_WAIT:if(score_valid_pipe[3]&&score_last_pipe[3]) begin
     candidate_score<=score_total;state<=SCORE_PICK;
    end
    SCORE_PICK:begin
     if(candidate_score<best_score) begin best_score<=candidate_score;best_delay<=candidate_delay;best_slope<=slope;best_phase<=b_s32_t'(intercept);end
     state<=NEXT_CANDIDATE;
    end
    NEXT_CANDIDATE:begin
     if(candidate_index==2) begin send_index<=0;amplitude_sum<=0;state<=GAIN_SEND;end
     else begin candidate_index<=candidate_index+1'b1;state<=CANDIDATE;end
    end
    GAIN_SEND:begin send_index<=send_index+1'b1;if(send_index==127) state<=GAIN_WAIT;end
    GAIN_WAIT:if(amplitude_last) state<=GAIN_SCALE;
    GAIN_SCALE:if(ORDER>=16) begin
     divider_numerator<=b_s64_t'(amplitude_sum)*64'sd2;divider_denominator<=32'(energy_sum);divider_start<=1;state<=AMP_DIV_WAIT;
    end else begin amplitude_signed<=b_s19_t'(b_round(b_s64_t'(amplitude_sum),7));state<=GAIN_ABS;end
    AMP_DIV_WAIT:if(divider_done) begin amplitude_signed<=b_s19_t'(divider_result);state<=GAIN_ABS;end
    GAIN_ABS:begin
     if(amplitude_signed<0) begin best_phase<=best_phase+32'sh80000000;amplitude<=$unsigned(-amplitude_signed);end
     else amplitude<=$unsigned(amplitude_signed);
     state<=GAIN_DIV_START;
    end
    GAIN_DIV_START:begin confidence<=amplitude>=32;divider_numerator<=GAIN_NUMERATOR;divider_denominator<=amplitude<32?32'd32:{13'd0,amplitude};divider_start<=1;state<=GAIN_DIV_WAIT;end
    GAIN_DIV_WAIT:if(divider_done) begin gain<=divider_result>16777216?25'd16777216:b_s25_t'(divider_result);delay<=best_delay;frequency<=best_slope;phase<=best_phase;score<=best_score;state<=COMPLETE;end
    COMPLETE:begin done<=1;state<=IDLE;end
    default:state<=IDLE;
   endcase
  end
 end
 wire [19:0] unused_gain_rotation_phase=gain_rotation_phase[19:0];
 wire unused_divider_busy=divider_busy;
 wire [7:0] unused_angle_tag=angle_tag[14:7];
endmodule
