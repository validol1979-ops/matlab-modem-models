// Buffered streaming MSK/GMSK receiver (cpm_fixed.receive). Load the 192 public preamble
// bits first; frames need TLAST and 8N..8N+96 samples. Two buffers let acquisition and
// the data pass overlap the capture of the next frame.
// Acquisition, once 1088 samples of the frame are stored (about 2.2k clocks):
//  pass 1: discriminator at integer positions m = 0..1041 (product with the previous
//          sample, CORDIC); corr[j] += round(inc[m],16)*w[m+1-j] for lags j-1 = -1..16,
//          w from a local reference modulator (MSK: sign of f; GMSK: round(f, 8));
//  peak:   first maximum; fraction from the triangle (MSK) or the parabola (GMSK, values
//          >> 5) through the neighbours, shared divider, clipped to +-1/2;
//  pass 2: x(n+delay)*conj(r[n]) for n < 1024 in 8 blocks of 128; block phases (CORDIC),
//          unwrapped, slope = divide(6*sum((2j-7)*p_j), 64512).
//          The intercept gives the phase: divide(sum p_j, 8) - round(slope*1023, 1).
// MSK data: positions n+delay+1/2, increments wrap(atan2(x_n*conj(x_{n-1})) - slope) (0 for
// n = 0), summed per symbol; m_bit = (sum >= 0), m_value = the sum.
// GMSK data (coherent, cpm_coherent): positions n+delay-1/2, Laurent C0 matched filter,
// phase loop, decisions; m_value = the axis-rotated soft value (19 bits, sign-extended).
// The data pass takes two samples per clock (cpm_samples lanes, two CORDICs), so with the
// ~2.2k-clock acquisition a frame is processed faster than it arrives; it stalls with
// m_ready. Acquisition reads one sample per clock (lane 0).
module cpm_rx #(parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter bit GMSK=0)(
 input logic clk,rst,
 input logic cfg_valid,cfg_bit,cfg_last,
 input logic [11:0] cfg_count,
 output logic cfg_ready,configured,error,
 input logic s_valid,s_last,
 input logic signed [17:0] s_re,s_im,
 output logic s_ready,
 output logic m_valid,m_last,m_bit,
 input logic m_ready,
 output logic signed [35:0] m_value,
 output logic acquisition_valid,
 output logic signed [31:0] acquisition_delay,acquisition_frequency,acquisition_phase
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 localparam int CORR=1024,LAGS=18,PASS1=CORR+LAGS;
 wire reset_now=rst==RESET_ACTIVE;
 // Configuration: preamble bit k at training[k].
 logic [191:0] training;
 logic [7:0] config_index;
 logic [11:0] symbol_count;
 // Capture into two frame buffers; sample k of a frame at index k.
 logic capture_active,capture_frame,next_capture,process_frame;
 logic [1:0] occupied,complete,invalid;
 logic [14:0] input_count;
 logic [14:0] written[0:1];
 wire taking=s_valid&&s_ready;
 wire first=taking&&!capture_active;
 wire input_frame=capture_active?capture_frame:next_capture;
 wire [14:0] received_count=input_count+1'b1;
 wire [14:0] expected=b_u15_t'({3'd0,symbol_count}*15'd8);
 assign cfg_ready=!capture_active&&occupied==0&&!reset_now;
 wire cfg_take=cfg_valid&&cfg_ready;
 assign s_ready=configured&&!error&&!reset_now&&!cfg_take&&(capture_active||!occupied[next_capture])&&input_count<15'd16480;
 typedef enum logic [4:0] {WAIT_FRAME,PASS1_SEND,PASS1_WAIT,PEAK,FRACTION,FRACTION_DEN,FRACTION_START,FRACTION_WAIT,FRACTION_ADD,PASS2_SEND,PASS2_WAIT,SLOPE_WAIT,INTERCEPT,PHASE,DATA,RETIRE} state_t;
 state_t state;
 wire pass1=state==PASS1_SEND||state==PASS1_WAIT,pass2=state==PASS2_SEND||state==PASS2_WAIT;
 wire data_ce=!m_valid||m_ready;
 // The sample reader and the CORDIC stall only in the data pass.
 wire stream_ce=state==DATA||state==RETIRE?data_ce:1'b1;
 // Sample reader (cubic interpolator, latency 7, II=1).
 logic q_valid;
 // Request position in samples, 8 fractional bits (the 16-bit fraction rounded down).
 logic signed [23:0] q_position;
 logic [14:0] request;
 logic signed [31:0] delay,slope;
 wire samples_valid;wire signed [17:0] samples_re,samples_im,samples_re1,samples_im1;wire [14:0] samples_tag;
 cpm_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) samples(
  clk,rst,taking,input_frame,input_count,s_re,s_im,stream_ce,q_valid,process_frame,
  q_position,written[process_frame],request,samples_valid,samples_re,samples_im,samples_re1,samples_im1,samples_tag);
 wire [14:0] sample_index=samples_tag[14:0];
 // Reference modulator, issued with the requests of passes 1 and 2 (latency 8).
 wire g_valid=state==PASS1_SEND||state==PASS2_SEND;
 wire signed [1:0] g_d=request<15'd1536 ?(training[request[10:3]]?2'sd1:-2'sd1):2'sd0;
 wire r_valid;wire signed [17:0] r_re,r_im,r_frequency;wire unused_r_tag;
 cpm_modulator #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(GMSK),.TAG_WIDTH(1)) reference(
  .clk(clk),.rst(rst),.ce(1'b1),.s_valid(g_valid),.s_first(request==0),.s_d(g_d),.s_tag(1'b0),
  .m_valid(r_valid),.m_re(r_re),.m_im(r_im),.m_frequency(r_frequency),.m_tag(unused_r_tag));
 // Pass 1 weights w[n] (10 bits), queued until inc[n-1] arrives (shift-register FIFO).
 wire signed [9:0] r_weight=GMSK?b_s10_t'(b_round(b_s64_t'(r_frequency),8)):(r_frequency>=0?10'sd1:-10'sd1);
 logic signed [9:0] weight_fifo[0:31];
 logic [5:0] weight_count;
 logic weight_dropped;
 // Pass 2 phase sum and intercept (declared before the generate blocks that use them).
 logic signed [42:0] phase_sum;
 // slope*1023 mod 2^33: only its low 33 bits reach the 32-bit phase.
 logic signed [32:0] slope_product;
 logic signed [31:0] phase0;
 // Data outputs of the discriminator (MSK) and of the coherent pass (GMSK).
 logic disc_valid,disc_last,disc_bit;
 logic signed [35:0] disc_value;
 wire coh_valid,coh_last,coh_bit,coh_done;
 wire signed [18:0] coh_value;
 // Discriminator: product with the previous sample, then the shared CORDIC.
 logic d_valid,d_first;
 logic [14:0] d_index;
 logic signed [17:0] previous_re,previous_im;
 logic signed [36:0] d_re,d_im;
 logic c_valid;
 logic signed [48:0] c_x,c_y;
 logic [15:0] c_tag;
 wire angle_valid;wire signed [31:0] angle;wire [15:0] angle_tag;
 bpsk_cordic #(.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,stream_ce,c_valid,c_x,c_y,c_tag,angle_valid,angle,angle_tag);
 // Lane 1 (data pass only): x_{n+1}*conj(x_n).
 // Its tag is the index LSB (always 0 for the even data requests), checked with lane 0.
 wire angle1_valid;wire signed [31:0] angle1;wire angle1_tag;
 generate
 if(GMSK) begin:g_coherent
  assign angle1_valid=0;assign angle1=0;assign angle1_tag=0;
  // round(slope*47, 1) for the angle at the C0 window centre; the coherent pass starts one
  // clock after the phase register is written.
  logic signed [31:0] centre;
  logic coherent_start;
  always_ff @(posedge clk) begin
   if(state==INTERCEPT) centre<=b_s32_t'(b_round(b_s64_t'(slope)*64'sd47,1));
   coherent_start<=!reset_now&&state==PHASE;
  end
  cpm_coherent #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) coherent(
   .clk(clk),.rst(rst),.ce(data_ce),.start(coherent_start),.phase0(phase0),.frequency(slope),.centre(centre),.symbol_count(symbol_count),.training(training),.s_valid(state==DATA&&samples_valid),.s_index(sample_index[2:0]),
   .s_re0(samples_re),.s_im0(samples_im),.s_re1(samples_re1),.s_im1(samples_im1),
   .m_valid(coh_valid),.m_last(coh_last),.m_bit(coh_bit),.m_value(coh_value),.done(coh_done));
 end else begin:g_discriminator
  logic signed [36:0] d_re1,d_im1;
  logic signed [48:0] c_x1,c_y1;
  always_ff @(posedge clk) if(stream_ce) begin
   if(samples_valid) begin
    d_re1<=b_s37_t'(samples_re1)*b_s37_t'(samples_re)+b_s37_t'(samples_im1)*b_s37_t'(samples_im);
    d_im1<=b_s37_t'(samples_im1)*b_s37_t'(samples_re)-b_s37_t'(samples_re1)*b_s37_t'(samples_im);
   end
   c_x1<=b_s49_t'(d_re1);c_y1<=b_s49_t'(d_im1);
  end
  bpsk_cordic #(.RESET_ACTIVE(RESET_ACTIVE),.TAG_WIDTH(1)) cordic1(clk,rst,stream_ce,c_valid&&state==DATA,c_x1,c_y1,c_tag[0],angle1_valid,angle1,angle1_tag);
  assign coh_valid=0;assign coh_last=0;assign coh_bit=0;assign coh_value=0;assign coh_done=0;
 end
 endgenerate
 wire inc_valid=pass1&&angle_valid&&!angle_tag[15];
 wire [10:0] inc_index=angle_tag[10:0];
 wire signed [16:0] inc17=b_s17_t'(b_round(b_s64_t'(angle),16));
 // Weight window: weight[j] = w[m-j] before inc[m]; inc[m] uses w[m+1-j] (the window after
 // shifting in w[m+1], which is the FIFO head after w[0] was dropped).
 logic signed [9:0] weight[0:LAGS-2];
 wire signed [9:0] window[0:LAGS-1];
 (* use_dsp="no" *) logic signed [41:0] corr[0:LAGS-1];
 logic [1:0] acc_valid;
 logic [10:0] acc_index[0:1];
 logic signed [16:0] inc_q;
 logic signed [9:0] window_q[0:LAGS-1];
 logic signed [26:0] product_q[0:LAGS-1];
 // Peak and fraction.
 logic [4:0] scan,best;
 logic signed [41:0] best_value,peak_low,peak_mid,peak_high;
 wire signed [41:0] peak_min=peak_low<peak_high?peak_low:peak_high;
 wire signed [43:0] fraction_denominator=GMSK?(b_s44_t'(peak_mid)<<<2)-(b_s44_t'(peak_low)<<<1)-(b_s44_t'(peak_high)<<<1)
                                            :(b_s44_t'(peak_mid)-b_s44_t'(peak_min))<<<1;
 logic divider_start;
 logic signed [63:0] divider_numerator;
 logic [31:0] divider_denominator;
 wire divider_busy,divider_done;
 wire signed [63:0] divider_result;
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE)) divider(clk,rst,divider_start,divider_numerator,divider_denominator,divider_busy,divider_done,divider_result);
 wire signed [31:0] fraction_clipped=divider_result>64'sd32768 ? 32'sd32768 : divider_result< -64'sd32768 ? -32'sd32768 : b_s32_t'(divider_result);
 wire signed [31:0] lag_delay=($signed({27'd0,best})-32'sd1)<<<16;
 logic signed [31:0] fraction_q;
 // The positive denominator stays below 2^32 (MSK |corr| < 2^26, GMSK values >> 5).
 logic [31:0] denominator_q;
 logic signed [63:0] numerator_q;
 logic use_fraction;
 wire signed [31:0] fraction_delay=lag_delay+fraction_q;
 // Pass 2: sample delayed one clock to meet r[n]; u = x*conj(r); blocks of 128.
 logic x2_valid;
 logic signed [17:0] x2_re,x2_im;
 logic u_valid;
 logic [9:0] u_index;
 logic signed [36:0] u_re,u_im;
 logic signed [47:0] block_re,block_im;
 logic signed [31:0] previous_phase;
 logic signed [39:0] unwrapped;
 logic signed [47:0] weighted;
 logic [3:0] phases_seen;
 // Block phases arrive 128 clocks apart: register, unwrap, weight, accumulate.
 wire block_valid=pass2&&angle_valid&&angle_tag[15];
 logic [2:0] block_stage;
 logic signed [31:0] block_angle;
 logic [2:0] block_index;
 logic signed [47:0] block_term;
 wire signed [31:0] phase_step=block_angle-previous_phase;
 // Least-squares weight 2j-7 of block j.
 wire signed [4:0] block_weight=$signed({1'b0,block_index,1'b0})-5'sd7;
 // Data pass.
 // GMSK: the C0 window of the last symbol ends at sample 8N+39.
 wire [14:0] data_total=b_u15_t'({3'd0,symbol_count}*15'd8)+15'(GMSK?40:0);
 // MSK samples half a sample after the delay, GMSK half a sample before it (C0 windows).
 localparam logic signed [31:0] DATA_SHIFT=GMSK?-32'sd32768:32'sd32768;
 wire signed [31:0] data_position=($signed({2'b0,request,15'd0})<<<1)+delay+DATA_SHIFT;
 // Lane 1 reads one sample further: its last tap is base+3 = request + ((delay+1/2)>>16) + 3,
 // with the offset K registered when the data pass starts.
 logic signed [17:0] data_offset;
 wire signed [17:0] last_needed=$signed({3'd0,request})+data_offset;
 wire data_available=complete[process_frame]||last_needed<$signed({3'd0,written[process_frame]});
 wire signed [31:0] data_increment=angle_tag[14:0]==0?32'sd0:angle-slope;
 wire signed [31:0] data_increment1=angle1-slope;
 wire data_angle=!GMSK&&state==DATA&&angle_valid&&angle1_valid&&angle1_tag==angle_tag[0];
 logic signed [35:0] symbol_sum;
 wire signed [35:0] symbol_next=symbol_sum+b_s36_t'(data_increment)+b_s36_t'(data_increment1);
 // Two increments per clock: a symbol takes four pairs.
 logic [1:0] symbol_phase;
 logic [11:0] symbol_index;
 genvar g;
 generate
 for(g=0;g<LAGS;g=g+1) begin:g_window
  if(g==0) begin:g_head
   assign window[g]=weight_fifo[0];
  end else begin:g_shifted
   assign window[g]=weight[g-1];
  end
 end
 endgenerate
 always_comb begin
  q_valid=0;q_position=0;
  case(state)
   PASS1_SEND:begin q_valid=1;q_position=$signed({1'b0,request,8'd0});end
   PASS2_SEND:begin q_valid=1;q_position=b_s24_t'((($signed({2'b0,request,15'd0})<<<1)+delay)>>>8);end
   DATA:begin q_valid=data_available&&request<data_total;q_position=b_s24_t'(data_position>>>8);end
   default:begin end
  endcase
 end
 assign acquisition_delay=delay;assign acquisition_frequency=slope;assign acquisition_phase=phase0;
 assign m_valid=GMSK?coh_valid:disc_valid;assign m_last=GMSK?coh_last:disc_last;assign m_bit=GMSK?coh_bit:disc_bit;
 assign m_value=GMSK?b_s36_t'(coh_value):disc_value;
 always_ff @(posedge clk) begin
  if(reset_now) begin
   configured<=0;error<=0;config_index<=0;capture_active<=0;next_capture<=0;process_frame<=0;
   occupied<=0;complete<=0;invalid<=0;input_count<=0;written[0]<=0;written[1]<=0;state<=WAIT_FRAME;
   divider_start<=0;acquisition_valid<=0;weight_count<=0;d_valid<=0;c_valid<=0;x2_valid<=0;u_valid<=0;
   if(!GMSK) disc_valid<=0;
  end else begin
   divider_start<=0;acquisition_valid<=0;
   if(cfg_valid&&cfg_ready) begin
    configured<=0;training<={cfg_bit,training[191:1]};config_index<=config_index+1'b1;
    if(cfg_last) begin
     config_index<=0;
     if(config_index==191&&cfg_count>=192&&cfg_count<=2048) begin configured<=1;symbol_count<=cfg_count;end
     else begin configured<=0;error<=1;end
    end else if(config_index==191) begin configured<=0;error<=1;config_index<=0;end
   end
   if(first) begin
    capture_active<=1;capture_frame<=next_capture;occupied[next_capture]<=1;complete[next_capture]<=0;invalid[next_capture]<=0;
    written[next_capture]<=1;input_count<=1;
   end else if(taking) begin input_count<=input_count+1'b1;written[input_frame]<=written[input_frame]+1'b1;end
   if(taking&&(s_last||input_count>=expected+15'd95)) begin
    capture_active<=0;next_capture<=!input_frame;input_count<=0;complete[input_frame]<=1;
    if(!s_last||received_count<expected||received_count>expected+15'd96) begin invalid[input_frame]<=1;error<=1;end
   end
   // Pass 1 weight queue: push w[n] from the reference, pop one per increment; w[0] is
   // dropped at once (inc[0] already needs w[1]).
   if(pass1) begin
    if(inc_valid) for(integer j=0;j<31;j=j+1) weight_fifo[j]<=weight_fifo[j+1];
    if(r_valid&&!(weight_count==0&&!weight_dropped)) weight_fifo[5'(inc_valid ? weight_count-6'd1 : weight_count)]<=r_weight;
    weight_count<=weight_count+6'(r_valid&&!(weight_count==0&&!weight_dropped))-6'(inc_valid);
    if(r_valid&&weight_count==0&&!weight_dropped) weight_dropped<=1;
   end
   // Discriminator front end (pass 1 and the data pass).
   if(stream_ce) begin
    // Coherent GMSK does not use the data discriminator. Letting its tokens
    // enter this CORDIC can leak a stalled tail into the next frame's pass1.
    d_valid<=samples_valid&&(pass1||(!GMSK&&state==DATA));d_first<=sample_index==0;d_index<=sample_index;
    if(samples_valid) begin
     // In the data pass the previous sample is lane 1 of the last request.
     previous_re<=state==DATA?samples_re1:samples_re;previous_im<=state==DATA?samples_im1:samples_im;
     d_re<=b_s37_t'(samples_re)*b_s37_t'(previous_re)+b_s37_t'(samples_im)*b_s37_t'(previous_im);
     d_im<=b_s37_t'(samples_im)*b_s37_t'(previous_re)-b_s37_t'(samples_re)*b_s37_t'(previous_im);
    end
    c_valid<=d_valid;c_x<=d_first?49'sd0:b_s49_t'(d_re);c_y<=d_first?49'sd0:b_s49_t'(d_im);c_tag<={1'b0,d_index};
   end
   // Pass 1 accumulation over n = m+1-j in 1..CORR.
   // Pass 1 in three steps: window and increment, products, accumulation.
   if(inc_valid) begin
    for(integer j=LAGS-2;j>0;j=j-1) weight[j]<=weight[j-1];
    weight[0]<=weight_fifo[0];
   end
   acc_valid[0]<=inc_valid;acc_valid[1]<=acc_valid[0];acc_index[0]<=inc_index;acc_index[1]<=acc_index[0];
   inc_q<=inc17;for(integer j=0;j<LAGS;j=j+1) window_q[j]<=window[j];
   for(integer j=0;j<LAGS;j=j+1) product_q[j]<=b_s27_t'(inc_q)*b_s27_t'(window_q[j]);
   if(acc_valid[1]) for(integer j=0;j<LAGS;j=j+1)
    if({5'd0,acc_index[1]}>=16'(j)&&{5'd0,acc_index[1]}<=16'(CORR+j-1)) corr[j]<=corr[j]+b_s42_t'(product_q[j]);
   // Pass 2 products and block sums; a finished block goes to the CORDIC.
   x2_valid<=pass2&&samples_valid;x2_re<=samples_re;x2_im<=samples_im;
   u_valid<=x2_valid&&r_valid;u_index<=u_valid?u_index+1'b1:u_index;
   u_re<=b_s37_t'(x2_re)*b_s37_t'(r_re)+b_s37_t'(x2_im)*b_s37_t'(r_im);
   u_im<=b_s37_t'(x2_im)*b_s37_t'(r_re)-b_s37_t'(x2_re)*b_s37_t'(r_im);
   if(pass2&&u_valid) begin
    if(u_index[6:0]==7'd127) begin
     c_valid<=1;c_x<=b_s49_t'(block_re+b_s48_t'(u_re));c_y<=b_s49_t'(block_im+b_s48_t'(u_im));c_tag<={1'b1,12'd0,u_index[9:7]};
     block_re<=0;block_im<=0;
    end else begin block_re<=block_re+b_s48_t'(u_re);block_im<=block_im+b_s48_t'(u_im);end
   end
   block_stage<={block_stage[1:0],block_valid};
   if(block_valid) begin block_angle<=angle;block_index<=angle_tag[2:0];end
   if(block_stage[0]) begin
    previous_phase<=block_angle;unwrapped<=block_index==0?b_s40_t'(block_angle):unwrapped+b_s40_t'(phase_step);
   end
   if(block_stage[1]) begin block_term<=b_s48_t'(unwrapped)*b_s48_t'(block_weight);phase_sum<=phase_sum+b_s43_t'(unwrapped);end
   if(block_stage[2]) begin weighted<=weighted+block_term;phases_seen<=phases_seen+1'b1;end
   // Data pass output: one sum per symbol.
   if(!GMSK&&data_ce) begin
    disc_valid<=0;
    if(data_angle) begin
     symbol_phase<=symbol_phase+1'b1;
     if(symbol_phase==2'd3) begin
      disc_valid<=1;disc_value<=symbol_next;disc_bit<=symbol_next>=0;disc_last<=symbol_index==symbol_count-1'b1;
      symbol_sum<=0;symbol_index<=symbol_index+1'b1;
     end else symbol_sum<=symbol_next;
    end
   end
   case(state)
    WAIT_FRAME:if(occupied[process_frame]) begin
     if(complete[process_frame]&&invalid[process_frame]) state<=RETIRE;
     else if(written[process_frame]>=15'd1088||complete[process_frame]) begin
      state<=PASS1_SEND;request<=0;weight_count<=0;weight_dropped<=0;scan<=0;
      for(integer j=0;j<LAGS;j=j+1) corr[j]<=0;
      for(integer j=0;j<LAGS-1;j=j+1) weight[j]<=0;
     end
    end
    PASS1_SEND:begin request<=request+1'b1;if(request==15'(PASS1-1)) state<=PASS1_WAIT;end
    PASS1_WAIT:if(acc_valid[1]&&acc_index[1]==11'(PASS1-1)) state<=PEAK;
    PEAK:begin
     // First maximum over the lags (ties keep the smaller lag).
     if(scan==0) begin best<=0;best_value<=corr[0];scan<=1;end
     else begin
      if(corr[scan]>best_value) begin best<=scan;best_value<=corr[scan];end
      if(scan==5'(LAGS-1)) state<=FRACTION;else scan<=scan+1'b1;
     end
    end
    FRACTION:begin
     scan<=0;
     peak_low<=GMSK?corr[best-1'b1]>>>5:corr[best-1'b1];peak_mid<=GMSK?best_value>>>5:best_value;
     peak_high<=GMSK?corr[best+1'b1]>>>5:corr[best+1'b1];state<=FRACTION_DEN;
    end
    FRACTION_DEN:begin
     // Registered denominator, numerator and branch decision.
     denominator_q<=32'(fraction_denominator);use_fraction<=best!=0&&best!=5'(LAGS-1)&&fraction_denominator>0;
     numerator_q<=(b_s64_t'(peak_high)-b_s64_t'(peak_low))<<<16;state<=FRACTION_START;
    end
    FRACTION_START:if(divider_busy) begin end
    else if(use_fraction) begin
     divider_numerator<=numerator_q;divider_denominator<=denominator_q;divider_start<=1;state<=FRACTION_WAIT;
    end else begin
     delay<=lag_delay<0?32'sd0:lag_delay;state<=PASS2_SEND;request<=0;u_index<=0;block_re<=0;block_im<=0;phases_seen<=0;weighted<=0;phase_sum<=0;
    end
    FRACTION_WAIT:if(divider_done) begin fraction_q<=fraction_clipped;state<=FRACTION_ADD;end
    FRACTION_ADD:begin
     delay<=fraction_delay<0?32'sd0:fraction_delay;state<=PASS2_SEND;request<=0;u_index<=0;block_re<=0;block_im<=0;phases_seen<=0;weighted<=0;phase_sum<=0;
    end
    PASS2_SEND:begin request<=request+1'b1;if(request==15'(CORR-1)) state<=PASS2_WAIT;end
    PASS2_WAIT:if(phases_seen==4'd8) begin
     divider_numerator<=b_s64_t'(weighted)*64'sd6;divider_denominator<=32'd64512;divider_start<=1;state<=SLOPE_WAIT;
    end
    SLOPE_WAIT:if(divider_done) begin slope<=b_s32_t'(divider_result);state<=INTERCEPT;end
    INTERCEPT:begin slope_product<=b_s33_t'(b_s43_t'(slope)*43'sd1023);state<=PHASE;end
    PHASE:begin
     phase0<=b_s32_t'(b_round(b_s64_t'(phase_sum),3)-b_round(b_s64_t'(slope_product),1));
     acquisition_valid<=1;state<=DATA;request<=0;
     if(!GMSK) begin symbol_sum<=0;symbol_phase<=0;symbol_index<=0;end
     data_offset<=b_s18_t'((delay+DATA_SHIFT)>>>16)+18'sd3;
    end
    DATA:begin
     if(data_ce&&q_valid) request<=request+15'd2;
     if(!GMSK&&data_ce&&data_angle&&symbol_phase==2'd3&&symbol_index==symbol_count-1'b1) state<=RETIRE;
     if(GMSK&&data_ce&&coh_done) state<=RETIRE;
    end
    RETIRE:if(complete[process_frame]) begin occupied[process_frame]<=0;process_frame<=!process_frame;state<=WAIT_FRAME;end
    default:state<=WAIT_FRAME;
   endcase
  end
 end
endmodule
