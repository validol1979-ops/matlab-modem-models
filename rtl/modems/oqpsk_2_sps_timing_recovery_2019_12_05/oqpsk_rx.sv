// OQPSK receiver front end: capture, matched filter, acquisition (oqpsk_fixed.acquire)
// and the split Costas data pass (oqpsk_fixed.receive). Load the 192 public preamble
// labels first (two bits per label); frames need TLAST and 8N..8N+96 samples,
// N = cfg_count in 192..2048.
// Two frame buffers let acquisition overlap the capture of the next frame; the data
// pass takes the samples through cpm_samples exactly like cpm_rx.
// Capture: every accepted input sample goes through bpsk_fir (the same 33-tap RRC as
// the transmitter); after the TLAST sample 32 zeros are pushed with s_ready low, so
// the FIR emits len(wave)+32 samples per frame, matching y = fir(wave) bit-exactly.
// y[n] is written into cpm_samples at index n; the frame is `complete` only when its
// last y sample is stored (the FIR runs un-stalled, latency 8, so complete lags the
// input TLAST by about 40 clocks).
// Acquisition, once 1088 samples of the frame are stored:
//  pass 1 (adds only): 11 requests per symbol k = 0..127 at integer positions
//          p = 31+8k+2i (fraction 0); lane 0 gives offset o = 2i, lane 1 o = 2i+1.
//          The sample at offset o adds sI*y to lag j = o (I, o <= 17) and sQ*(-j)*y
//          to lag j = o-4 (Q, o >= 4) of the current 16-symbol block. At most one
//          term lands on any lag in any clock. When symbol 16b+15 is complete the
//          block is snapshot through (sum >>> 9) and energy[j] += re^2 + im^2 runs
//          over the 18 lags, one lag per clock.
//  peak:   first maximum over j (ties keep the smaller j); fraction from the parabola
//          of the >>> 8 values through the shared bpsk_divide, clipped to +-32768;
//          delay = max(0, ((j-1) << 16) + fraction).
//  pass 2: 256 requests (2 per symbol): zI at ((32+8k) << 16) + delay, zQ at
//          ((36+8k) << 16) + delay. re += sI*zI.re + sQ*zQ.im, im += sI*zI.im -
//          sQ*zQ.re over 16 symbols; the 8 block phases (CORDIC) are unwrapped and
//          fitted: slope = divide(6*weighted, 8064), frequency = divide(slope, 8),
//          phase = divide(sum, 8) - round(slope*127, 1) (nearest-even, as Python).
// acquisition_valid pulses with the three outputs; `slope` (per symbol) is kept for
// the data pass.
// Data pass (oqpsk_costas): two requests per symbol, zI at ((32+8k) << 16) + delay and zQ
// at ((36+8k) << 16) + delay, issued 4 clocks apart and only once the loop error of symbol
// k-LOOP_DELAY is stored (error_count) and the cubic taps of the request are written. The module
// rotates, decides, closes the loop and streams m_* (label, re, im) with m_last; the frame
// retires when it reports done. The sample reader and the module stall on !m_ready.
module oqpsk_rx #(parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",
 parameter int LOOP_DELAY=8)(
 input logic clk,rst,
 input logic cfg_valid,cfg_last,
 input logic [1:0] cfg_label,
 input logic [11:0] cfg_count,
 output logic cfg_ready,configured,error,
 input logic s_valid,s_last,
 input logic signed [17:0] s_re,s_im,
 output logic s_ready,
 output logic m_valid,m_last,
 output logic [1:0] m_label,
 input logic m_ready,
 output logic signed [17:0] m_re,m_im,
 output logic acquisition_valid,
 output logic signed [31:0] acquisition_delay,acquisition_frequency,acquisition_phase
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 localparam int LAGS=18,FIRST=32;
 localparam logic [10:0] P1_BASE=11'(FIRST-1),P2_BASE=11'(FIRST);
 wire reset_now=rst==RESET_ACTIVE;
 // Configuration: label k at training[2k+1:2k]; label -> (sign I, sign Q) is
// (1,1),(-1,1),(-1,-1),(1,-1), so sign I is negative on bit1^bit0 and sign Q on bit1.
 logic [383:0] training;
 logic [7:0] config_index;
 logic [11:0] symbol_count;
 // Input side of the capture: sample count per frame and the two-buffer bookkeeping.
 logic capture_active,capture_frame,next_capture,process_frame;
 logic [1:0] occupied,complete,invalid;
 logic [14:0] input_count;
 logic [5:0] flush;
 logic [14:0] written[0:1];
 wire taking=s_valid&&s_ready;
 wire first=taking&&!capture_active;
 wire input_frame=capture_active?capture_frame:next_capture;
 wire [14:0] received_count=input_count+15'd1;
 wire [14:0] expected=b_u15_t'({3'd0,symbol_count}*15'd8);
 wire frame_end=taking&&(s_last||input_count>=expected+15'd95);
 assign cfg_ready=!capture_active&&occupied==0&&!reset_now;
 wire cfg_take=cfg_valid&&cfg_ready;
 // s_ready is low during the 32-clock FIR flush; the FIR itself never stalls.
 assign s_ready=configured&&!error&&!reset_now&&!cfg_take&&flush==0&&input_count<15'd16480&&(capture_active||!occupied[next_capture]);
 typedef enum logic [3:0] {WAIT_FRAME,PASS1_SEND,PASS1_WAIT,PEAK,FRACTION,FRACTION_DEN,FRACTION_START,FRACTION_WAIT,FRACTION_ADD,PASS2_SEND,PASS2_WAIT,SLOPE_WAIT,PHASE,DATA,RETIRE} state_t;
 state_t state;
 wire pass1=state==PASS1_SEND||state==PASS1_WAIT,pass2=state==PASS2_SEND||state==PASS2_WAIT;
 // The sample reader and the data pass stall only while the output register is full.
 wire data_ce=!m_valid||m_ready;
 wire stream_ce=state==DATA||state==RETIRE?data_ce:1'b1;
 // Matched filter: the frame samples, then 32 zeros; s_last on the final zero.
 wire fir_valid=taking||flush!=0;
 wire signed [17:0] fir_re=taking?s_re:18'sd0,fir_im=taking?s_im:18'sd0;
 wire f_valid,f_last;
 wire signed [17:0] f_re,f_im;
 bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE)) filter(
  .clk(clk),.rst(rst),.ce(1'b1),.s_valid(fir_valid),.s_last(flush==6'd1),.s_first(first),
  .s_re(fir_re),.s_im(fir_im),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(f_im));
 // FIR output side: y[n] at index n of the frame the samples belong to.
 logic out_frame;
 logic [14:0] out_count;
 // The sample reader (cubic interpolation, latency 7, two lanes).
 logic q_valid;
 logic signed [23:0] q_position;
 logic [14:0] q_tag;
 logic signed [31:0] delay,slope,frequency,phase0;
 wire samples_valid;
 wire signed [17:0] samples_re,samples_im,samples_re1,samples_im1;
 wire [14:0] samples_tag;
 cpm_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) samples(
  .clk(clk),.rst(rst),.wr_en(f_valid),.wr_frame(out_frame),.wr_index(out_count),.wr_re(f_re),.wr_im(f_im),
  .ce(stream_ce),.s_valid(q_valid),.s_frame(process_frame),.s_position(q_position),
  .s_length(written[process_frame]),.s_tag(q_tag),.m_valid(samples_valid),
  .m_re0(samples_re),.m_im0(samples_im),.m_re1(samples_re1),.m_im1(samples_im1),.m_tag(samples_tag));
 // Shared divider: the parabola fraction and the least-squares slope.
 logic divider_start;
 logic signed [63:0] divider_numerator;
 logic [31:0] divider_denominator;
 wire divider_busy,divider_done;
 wire signed [63:0] divider_result;
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE)) divider(clk,rst,divider_start,divider_numerator,divider_denominator,divider_busy,divider_done,divider_result);
 // Block phase chain (identical weights to cpm_rx over 8 blocks of 16).
 logic c_valid;
 logic signed [48:0] c_x,c_y;
 logic [3:0] c_tag;
 wire angle_valid;
 wire signed [31:0] angle;
 wire [3:0] angle_tag;
 bpsk_cordic #(.TAG_WIDTH(4),.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,stream_ce,c_valid,c_x,c_y,c_tag,angle_valid,angle,angle_tag);
 logic signed [43:0] phase_sum;
 logic signed [48:0] weighted,block_term;
 logic [3:0] phases_seen;
 wire block_valid=pass2&&angle_valid&&angle_tag[3];
 logic [2:0] block_stage;
 logic signed [31:0] block_angle,previous_phase;
 logic [2:0] block_index;
 wire signed [31:0] phase_step=block_angle-previous_phase;
 wire signed [4:0] block_weight=$signed({1'b0,block_index,1'b0})-5'sd7;
 logic signed [39:0] unwrapped;
 // Pass 1: 128 symbols x 11 two-lane requests; the tag carries k and i.
 logic [6:0] p1_k;
 logic [3:0] p1_i;
 wire [10:0] p1_pos=P1_BASE+{1'b0,p1_k,3'd0}+{6'd0,p1_i,1'b0};
 wire p1_valid=pass1&&samples_valid;
 wire [6:0] r1_k=samples_tag[10:4];
 wire [3:0] r1_i=samples_tag[3:0];
 wire [1:0] label1=training[{1'b0,r1_k,1'b0}+:2];
 wire neg_i1=label1[1]^label1[0],neg_q1=label1[1];
 // One term per lag per clock: lane 0 (o = 2i) hits even lags, lane 1 (o = 2i+1) odd.
 logic signed [18:0] term_re[0:LAGS-1],term_im[0:LAGS-1];
 // Registered terms: the block adders only see the previous clock's terms.
 logic signed [18:0] term_q_re[0:LAGS-1],term_q_im[0:LAGS-1];
 logic p1_valid_q,p1_block_last_q;
 logic [2:0] p1_block_k_q;
 // Adders stay in fabric (like the cpm/cpm_samples sums).
 (* use_dsp="no" *) logic signed [24:0] blk_re[0:LAGS-1],blk_im[0:LAGS-1];
 logic signed [15:0] snap_re[0:LAGS-1],snap_im[0:LAGS-1];
 (* use_dsp="no" *) logic signed [35:0] energy[0:LAGS-1];
 // Energy path: e1 samples the snapshot, e2 the 16x16 products, e3 the sum, e4 the add.
 logic signed [15:0] es_re,es_im;
 logic signed [31:0] ep_re,ep_im;
 (* use_dsp="no" *) logic signed [32:0] esum;
 logic [4:0] e1_index,e2_index,e3_index;
 logic e1_valid,e1_last,e2_valid,e2_last,e3_valid,e3_last;
 logic snap_pending,snap_start,snap_is_last;
 logic [4:0] ej;
 logic e_run,p1_done;
 wire p1_block_last=p1_valid&&r1_i==4'd10&&r1_k[3:0]==4'd15;
 // Peak and fraction.
 logic [4:0] scan,best;
 logic signed [35:0] best_value,peak_low,peak_mid,peak_high;
 wire signed [43:0] fraction_denominator=(b_s44_t'(peak_mid)<<<2)-(b_s44_t'(peak_low)<<<1)-(b_s44_t'(peak_high)<<<1);
 wire signed [31:0] fraction_clipped=divider_result>64'sd32768 ? 32'sd32768 : divider_result< -32768 ? -32'sd32768 : b_s32_t'(divider_result);
 wire signed [31:0] lag_delay=($signed({27'd0,best})-32'sd1)<<<16;
 logic signed [31:0] fraction_q;
 logic [31:0] denominator_q;
 logic signed [63:0] numerator_q;
 logic use_fraction;
 wire signed [31:0] fraction_delay=lag_delay+fraction_q;
 // Pass 2: 2 requests per symbol; the tag carries k and the I/Q select.
 logic [7:0] p2_r;
 wire [6:0] q2_k=p2_r[7:1];
 wire q2_sel=p2_r[0];
 wire [10:0] p2_base=P2_BASE+{1'b0,q2_k,3'd0}+{8'b0,q2_sel,2'b0};
 wire signed [31:0] p2_pos=(b_s32_t'(p2_base)<<<16)+delay;
 wire p2_valid=pass2&&samples_valid;
 wire [6:0] r2_k=samples_tag[7:1];
 wire r2_sel=samples_tag[0];
 wire [1:0] label2=training[{1'b0,r2_k,1'b0}+:2];
 wire neg_i2=label2[1]^label2[0],neg_q2=label2[1];
 wire signed [18:0] p2_term_re=r2_sel?(neg_q2?19'sd0-b_s19_t'(samples_im):b_s19_t'(samples_im)):(neg_i2?19'sd0-b_s19_t'(samples_re):b_s19_t'(samples_re));
 wire signed [18:0] p2_term_im=r2_sel?(neg_q2?b_s19_t'(samples_re):19'sd0-b_s19_t'(samples_re)):(neg_i2?19'sd0-b_s19_t'(samples_im):b_s19_t'(samples_im));
 wire p2_block_last=p2_valid&&r2_k[3:0]==4'd15&&r2_sel;
 (* use_dsp="no" *) logic signed [24:0] blk2_re,blk2_im;
 genvar g;
 generate
 for(g=0;g<LAGS;g=g+1) begin:g_term
  if(g%2==0) begin:g_even
   // Lane 0: I at o = g (i = g/2), Q at o = g+4 (i = g/2+2); both fit i <= 10.
   wire use_i=p1_valid&&r1_i==4'(g/2);
   wire use_q=p1_valid&&r1_i==4'(g/2+2);
    assign term_re[g]=use_i?(neg_i1?19'sd0-b_s19_t'(samples_re):b_s19_t'(samples_re))
                    :use_q?(neg_q1?19'sd0-b_s19_t'(samples_im):b_s19_t'(samples_im)):19'sd0;
    assign term_im[g]=use_i?(neg_i1?19'sd0-b_s19_t'(samples_im):b_s19_t'(samples_im))
                    :use_q?(neg_q1?b_s19_t'(samples_re):19'sd0-b_s19_t'(samples_re)):19'sd0;
  end else begin:g_odd
   // Lane 1: I at o = g (i = (g-1)/2), Q at o = g+4 (i = (g+3)/2).
   wire use_i=p1_valid&&r1_i==4'((g-1)/2);
   wire use_q=p1_valid&&r1_i==4'((g+3)/2);
    assign term_re[g]=use_i?(neg_i1?19'sd0-b_s19_t'(samples_re1):b_s19_t'(samples_re1))
                    :use_q?(neg_q1?19'sd0-b_s19_t'(samples_im1):b_s19_t'(samples_im1)):19'sd0;
    assign term_im[g]=use_i?(neg_i1?19'sd0-b_s19_t'(samples_im1):b_s19_t'(samples_im1))
                    :use_q?(neg_q1?b_s19_t'(samples_re1):19'sd0-b_s19_t'(samples_re1)):19'sd0;
  end
 end
 endgenerate
 // Data pass: request generator (zI, zQ per symbol) and the split Costas loop module.
 logic [11:0] data_k;
 wire [11:0] error_count;
 logic [1:0] data_phase;
 wire [15:0] data_base=16'd32+{1'b0,data_k,3'd0}+{13'd0,data_phase[0],2'b0};
 wire signed [31:0] data_pos=(b_s32_t'(data_base)<<<16)+delay;
 wire signed [17:0] data_last=18'sd38+b_s18_t'({1'b0,data_k,3'd0})+b_s18_t'(delay>>>16);
 wire data_available=complete[process_frame]||data_last<$signed({3'd0,written[process_frame]});
 wire data_gate=data_k<12'(LOOP_DELAY)||error_count>data_k-12'(LOOP_DELAY);
 logic costas_start;
 wire data_valid,data_last_symbol,data_done;
 wire [1:0] data_label;
 wire signed [17:0] data_re,data_im;
 // Data tags are {2'd0, k, sel}; the zero top bits are checked so every tag bit is read.
 oqpsk_costas #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.LOOP_DELAY(LOOP_DELAY)) costas(
  .clk(clk),.rst(rst),.ce(data_ce),.start(costas_start),.phase0(phase0),.slope(slope),.frequency(frequency),
  .symbol_count(symbol_count),.training(training),.s_valid(state==DATA&&samples_valid&&samples_tag[14:13]==2'd0),.s_sel(samples_tag[0]),
  .s_symbol(samples_tag[12:1]),.s_re(samples_re),.s_im(samples_im),
  .m_valid(data_valid),.m_last(data_last_symbol),.m_label(data_label),.m_re(data_re),.m_im(data_im),
  .error_count(error_count),.done(data_done));
 // Reader requests: pass 1 integer positions, pass 2 positions at the found delay,
 // the data pass alternating zI (phase 0) and zQ (phase 1) with two idle clocks.
 always_comb begin
  q_valid=0;q_position=0;q_tag=0;
  case(state)
   PASS1_SEND:begin q_valid=1;q_position=b_s24_t'({5'd0,p1_pos,8'd0});q_tag={4'd0,p1_k,p1_i};end
   PASS2_SEND:begin q_valid=1;q_position=b_s24_t'(p2_pos>>>8);q_tag={7'd0,p2_r};end
   DATA:begin
    q_valid=(data_phase==2'd0&&data_k<symbol_count&&data_available&&data_gate)||data_phase==2'd1;
    q_position=b_s24_t'(data_pos>>>8);q_tag={2'd0,data_k,data_phase[0]};
   end
   default:begin end
  endcase
 end
 assign acquisition_delay=delay;assign acquisition_frequency=frequency;assign acquisition_phase=phase0;
 assign m_valid=data_valid;assign m_last=data_last_symbol;assign m_label=data_label;assign m_re=data_re;assign m_im=data_im;
 // The loop clears one clock after PHASE writes the acquisition phase.
 always_ff @(posedge clk) costas_start<=!reset_now&&state==PHASE;
 always_ff @(posedge clk) begin
  if(reset_now) begin
   configured<=0;error<=0;config_index<=0;capture_active<=0;next_capture<=0;process_frame<=0;
   occupied<=0;complete<=0;invalid<=0;input_count<=0;flush<=0;written[0]<=0;written[1]<=0;
   out_frame<=0;out_count<=0;state<=WAIT_FRAME;divider_start<=0;acquisition_valid<=0;
   c_valid<=0;snap_pending<=0;snap_start<=0;e_run<=0;p1_done<=0;data_k<=0;data_phase<=0;
   e1_valid<=0;e2_valid<=0;e3_valid<=0;e1_last<=0;e2_last<=0;e3_last<=0;
   p1_valid_q<=0;p1_block_last_q<=0;
  end else begin
   divider_start<=0;acquisition_valid<=0;c_valid<=0;
   if(cfg_valid&&cfg_ready) begin
    configured<=0;training<={cfg_label,training[383:2]};config_index<=config_index+1'b1;
    if(cfg_last) begin
     config_index<=0;
     if(config_index==8'd191&&cfg_count>=12'd192&&cfg_count<=12'd2048) begin configured<=1;symbol_count<=cfg_count;end
     else begin configured<=0;error<=1;end
    end else if(config_index==8'd191) begin configured<=0;error<=1;config_index<=0;end
   end
   // Capture bookkeeping (input side); frames follow without a reset.
   if(first) begin
    capture_active<=1;capture_frame<=next_capture;occupied[next_capture]<=1;complete[next_capture]<=0;
    invalid[next_capture]<=0;written[next_capture]<=0;input_count<=1;
   end else if(taking) input_count<=input_count+1'b1;
   if(frame_end) begin
    capture_active<=0;next_capture<=!input_frame;input_count<=0;flush<=6'd32;
    if(!s_last||received_count<expected||received_count>expected+15'd96) begin invalid[input_frame]<=1;error<=1;end
   end else if(flush!=0) flush<=flush-1'b1;
   // Matched filter outputs: written count and completion of the frame being stored.
   if(f_valid) begin
    out_count<=f_last?15'd0:out_count+15'd1;
    written[out_frame]<=written[out_frame]+15'd1;
    if(f_last) begin complete[out_frame]<=1;out_frame<=!out_frame;end
   end
   // Pass 1 block accumulation. Terms are registered first; a snapshot lands the clock
   // after the last add of the block; the next block's first add then starts from zero
   // in the same clock.
   for(integer j=0;j<LAGS;j=j+1) begin
    term_q_re[j]<=term_re[j];term_q_im[j]<=term_im[j];
   end
   p1_valid_q<=p1_valid;
   p1_block_last_q<=p1_block_last;
   if(p1_block_last) p1_block_k_q<=r1_k[6:4];
   snap_pending<=p1_block_last_q;
   if(p1_block_last_q) snap_is_last<=p1_block_k_q==3'd7;
   snap_start<=snap_pending;
   if(snap_pending) for(integer j=0;j<LAGS;j=j+1) begin
    snap_re[j]<=b_s16_t'(blk_re[j]>>>9);snap_im[j]<=b_s16_t'(blk_im[j]>>>9);
   end
   if(snap_pending) for(integer j=0;j<LAGS;j=j+1) begin
    blk_re[j]<=b_s25_t'(term_q_re[j]);blk_im[j]<=b_s25_t'(term_q_im[j]);
   end else if(p1_valid_q) for(integer j=0;j<LAGS;j=j+1) begin
    blk_re[j]<=blk_re[j]+b_s25_t'(term_q_re[j]);blk_im[j]<=blk_im[j]+b_s25_t'(term_q_im[j]);
   end
   // One lag per clock: e1..e3 pipeline the squares, e4 does energy[e3_index] += sum.
   es_re<=snap_re[ej];es_im<=snap_im[ej];e1_index<=ej;e1_valid<=e_run;
   e1_last<=e_run&&ej==5'(LAGS-1);
   ep_re<=es_re*es_re;ep_im<=es_im*es_im;
   e2_index<=e1_index;e2_valid<=e1_valid;e2_last<=e1_last;
   esum<=b_s33_t'(ep_re)+b_s33_t'(ep_im);
   e3_index<=e2_index;e3_valid<=e2_valid;e3_last<=e2_last;
   if(e3_valid) energy[e3_index]<=energy[e3_index]+b_s36_t'(esum);
   if(e3_valid&&e3_last) p1_done<=snap_is_last;
   if(snap_start) begin ej<=0;e_run<=1;end
   else if(e_run) begin
    if(ej==5'(LAGS-1)) e_run<=0;
    else ej<=ej+1'b1;
   end
   // Pass 2 products and block sums; a finished block goes to the CORDIC.
   if(p2_valid) begin
    if(p2_block_last) begin
     c_valid<=1;c_x<=b_s49_t'(b_s49_t'(blk2_re)+b_s49_t'(p2_term_re));c_y<=b_s49_t'(b_s49_t'(blk2_im)+b_s49_t'(p2_term_im));
     c_tag<={1'b1,r2_k[6:4]};blk2_re<=0;blk2_im<=0;
    end else begin
     blk2_re<=blk2_re+b_s25_t'(p2_term_re);blk2_im<=blk2_im+b_s25_t'(p2_term_im);
    end
   end
   // Block phases: register, unwrap, weight, accumulate (as cpm_rx).
   block_stage<={block_stage[1:0],block_valid};
   if(block_valid) begin block_angle<=angle;block_index<=angle_tag[2:0];end
   if(block_stage[0]) begin
    previous_phase<=block_angle;unwrapped<=block_index==0?b_s40_t'(block_angle):unwrapped+b_s40_t'(phase_step);
   end
   if(block_stage[1]) begin block_term<=b_s48_t'(unwrapped)*b_s48_t'(block_weight);phase_sum<=phase_sum+b_s43_t'(unwrapped);end
   if(block_stage[2]) begin weighted<=weighted+block_term;phases_seen<=phases_seen+1'b1;end
   case(state)
    WAIT_FRAME:if(occupied[process_frame]) begin
     if(complete[process_frame]&&invalid[process_frame]) state<=RETIRE;
     else if(written[process_frame]>=15'd1088||complete[process_frame]) begin
      state<=PASS1_SEND;p1_k<=0;p1_i<=0;ej<=0;e_run<=0;p1_done<=0;scan<=0;
      for(integer j=0;j<LAGS;j=j+1) begin blk_re[j]<=0;blk_im[j]<=0;energy[j]<=0;end
     end
    end
    PASS1_SEND:if(p1_i==4'd10) begin
     p1_i<=0;p1_k<=p1_k+1'b1;
     if(p1_k==7'd127) state<=PASS1_WAIT;
    end else p1_i<=p1_i+1'b1;
    PASS1_WAIT:if(p1_done) begin p1_done<=0;state<=PEAK;end
    PEAK:begin
     // First maximum over the lags (ties keep the smaller lag).
     if(scan==0) begin best<=0;best_value<=energy[0];scan<=1;end
     else begin
      if(energy[scan]>best_value) begin best<=scan;best_value<=energy[scan];end
      if(scan==5'(LAGS-1)) state<=FRACTION;else scan<=scan+1'b1;
     end
    end
    FRACTION:begin
     peak_low<=best!=0?energy[best-1'b1]>>>8:36'sd0;
     peak_mid<=energy[best]>>>8;
     peak_high<=best!=5'(LAGS-1)?energy[best+1'b1]>>>8:36'sd0;
     state<=FRACTION_DEN;
    end
    FRACTION_DEN:begin
     // The positive denominator stays below 2^32 (energy < 2^36, values >> 8).
     denominator_q<=32'(fraction_denominator);
     use_fraction<=best!=0&&best!=5'(LAGS-1)&&fraction_denominator>0;
     numerator_q<=(b_s64_t'(peak_high)-b_s64_t'(peak_low))<<<16;state<=FRACTION_START;
    end
    FRACTION_START:if(divider_busy) begin end
    else if(use_fraction) begin
     divider_numerator<=numerator_q;divider_denominator<=denominator_q;divider_start<=1;state<=FRACTION_WAIT;
    end else begin
     delay<=lag_delay<0?32'sd0:lag_delay;
     state<=PASS2_SEND;p2_r<=0;blk2_re<=0;blk2_im<=0;phases_seen<=0;weighted<=0;phase_sum<=0;
    end
    FRACTION_WAIT:if(divider_done) begin fraction_q<=fraction_clipped;state<=FRACTION_ADD;end
    FRACTION_ADD:begin
     delay<=fraction_delay<0?32'sd0:fraction_delay;
     state<=PASS2_SEND;p2_r<=0;blk2_re<=0;blk2_im<=0;phases_seen<=0;weighted<=0;phase_sum<=0;
    end
    PASS2_SEND:begin p2_r<=p2_r+1'b1;if(p2_r==8'd255) state<=PASS2_WAIT;end
    PASS2_WAIT:if(phases_seen==4'd8) begin
     divider_numerator<=b_s64_t'(weighted)*64'sd6;divider_denominator<=32'd8064;divider_start<=1;state<=SLOPE_WAIT;
    end
    SLOPE_WAIT:if(divider_done) begin
     // slope per symbol; the frequency is divide(slope, 8), nearest-even.
     slope<=b_s32_t'(divider_result);frequency<=b_s32_t'(b_round(b_s64_t'(b_s32_t'(divider_result)),3));state<=PHASE;
    end
    PHASE:begin
     phase0<=b_s32_t'(b_round(b_s64_t'(phase_sum),3)-b_round(b_s64_t'(slope)*64'sd127,1));
     acquisition_valid<=1;state<=DATA;data_k<=0;data_phase<=0;
    end
    DATA:if(data_ce) begin
     // zI (phase 0) and zQ (phase 1) on consecutive clocks, then two idle clocks; the
     // zI request waits for the loop error of symbol k-LOOP_DELAY and the written taps.
     if(data_phase==2'd0) begin if(q_valid) data_phase<=2'd1;end
     else if(data_phase==2'd3) begin data_phase<=0;data_k<=data_k+12'd1;end
     else data_phase<=data_phase+2'd1;
     if(data_done) state<=RETIRE;
    end
    RETIRE:if(complete[process_frame]) begin occupied[process_frame]<=0;process_frame<=!process_frame;state<=WAIT_FRAME;end
    default:state<=WAIT_FRAME;
   endcase
  end
 end
endmodule
