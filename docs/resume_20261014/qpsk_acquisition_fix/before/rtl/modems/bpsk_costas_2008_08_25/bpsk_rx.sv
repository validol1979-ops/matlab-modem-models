// Buffered streaming BPSK receiver. Load the 192 PUBLIC training bits before
// frames. Two buffers let preamble acquisition and catch-up overlap capture.
// Configuration is accepted only while idle. TLAST is required per waveform.
// ORDER=2: differential BPSK; ORDER=4: QPSK; ORDER=8: unit 8-PSK (see bpsk_track for AMPLITUDE, DIFFERENTIAL,
// FEEDFORWARD and TIMING_LOOP). Points on the axes need no receiver option: acquisition
// absorbs the 45 degree offset. cfg_bit and m_bit carry symbol labels of log2(ORDER) bits.
// PI4 (ORDER=8): pi/4-QPSK over the 8-point table, 2-bit labels; m_index stays 3 bits.
// EQUALIZER (ORDER=16): 1 = NLMS, 2 = DFE; acquisition then fits block phases (BLOCK_FIT).
// ORDER=64: QAM64, AMPLITUDE = T = 8192 after the 1/4-scaled receive filter, 6-bit labels.
// Input limit: peak 3.64 per axis at unit channel gain; tested up to gain 1.2.
module bpsk_rx #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter int ORDER=2,
 parameter int AMPLITUDE=ORDER==8?32768:ORDER==4?23170:16384,parameter bit DIFFERENTIAL=ORDER==2,parameter bit FEEDFORWARD=0,parameter bit TIMING_LOOP=1,
 parameter bit PI4=0,parameter int EQUALIZER=0
)(
 input logic clk,rst,
 input logic cfg_valid,
 input logic [(ORDER==64?6:ORDER==16?4:ORDER==8?(PI4?2:3):ORDER==4?2:1)-1:0] cfg_bit,
 input logic cfg_last,
 input logic [11:0] cfg_count,
 output logic cfg_ready,configured,error,
 input logic s_valid,s_last,
 input logic signed [17:0] s_re,s_im,
 output logic s_ready,
 output logic m_valid,m_last,
 output logic [(ORDER==64?6:ORDER==16?4:ORDER==8?(PI4?2:3):ORDER==4?2:1)-1:0] m_bit,
 output logic [(ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1)-1:0] m_index,
 input logic m_ready,
 output logic signed [17:0] m_re,m_im,
 output logic signed [31:0] m_phase,m_frequency,m_correction,
 output logic [24:0] m_gain,
 output logic acquisition_valid,acquisition_confidence,
 output logic signed [31:0] acquisition_delay,acquisition_frequency,acquisition_phase,
 output logic [24:0] acquisition_gain,
 output logic [63:0] acquisition_score
);
 `include "bpsk_types.svh"
 wire reset_now=rst==RESET_ACTIVE;
 localparam int BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
 logic [192*BITS-1:0] training;
 logic [7:0] config_index;
 wire [BITS-1:0] config_label;
 generate
 if(ORDER>=16) begin:g_qam16_config
  // Stored training index: quadrant = running sum of gray(top two label bits) mod 4,
  // then the in-quadrant bits.
  logic [1:0] config_state;
  always_ff @(posedge clk) begin
   if(reset_now) config_state<=0;
   else if(cfg_valid&&cfg_ready) config_state<=(cfg_last||config_index==191)?2'd0:config_label[BITS-1:BITS-2];
  end
  assign config_label={config_state+{cfg_bit[BITS-1],cfg_bit[BITS-1]^cfg_bit[BITS-2]},cfg_bit[BITS-3:0]};
 end else if(ORDER==8&&PI4) begin:g_pi4_config
  // Stored training index = running sum of 2*gray(label)+1 mod 8.
  logic [2:0] config_state;
  always_ff @(posedge clk) begin
   if(reset_now) config_state<=0;
   else if(cfg_valid&&cfg_ready) config_state<=(cfg_last||config_index==191)?3'd0:config_label;
  end
  assign config_label=config_state+{cfg_bit[1],cfg_bit[1]^cfg_bit[0],1'b1};
 end else if(ORDER==8&&!DIFFERENTIAL) begin:g_psk8_config
  assign config_label=cfg_bit;
 end else if(ORDER==8) begin:g_psk8_differential_config
  // Stored training index = running sum of gray(label) mod 8.
  logic [2:0] config_state;
  always_ff @(posedge clk) begin
   if(reset_now) config_state<=0;
   else if(cfg_valid&&cfg_ready) config_state<=(cfg_last||config_index==191)?3'd0:config_label;
  end
  assign config_label=config_state+{cfg_bit[2],cfg_bit[2]^cfg_bit[1],cfg_bit[1]^cfg_bit[0]};
 end else if(ORDER==4&&!DIFFERENTIAL) begin:g_qpsk_config
  // QPSK labels are stored as sent; no differential coding.
  assign config_label=cfg_bit;
 end else if(ORDER==4) begin:g_qpsk_differential_config
  // Stored training index = running sum of gray(label) mod 4.
  logic [1:0] config_state;
  always_ff @(posedge clk) begin
   if(reset_now) config_state<=0;
   else if(cfg_valid&&cfg_ready) config_state<=(cfg_last||config_index==191)?2'd0:config_label;
  end
  assign config_label=config_state+{cfg_bit[1],cfg_bit[1]^cfg_bit[0]};
 end else begin:g_bpsk_config
  // Differential BPSK: the stored training label is the running XOR.
  logic config_previous;
  always_ff @(posedge clk) begin
   if(reset_now) config_previous<=0;
   else if(cfg_valid&&cfg_ready) config_previous<=(cfg_last||config_index==191)?1'b0:config_previous^cfg_bit[0];
  end
  assign config_label=config_previous^cfg_bit[0];
 end
 endgenerate
 logic [11:0] symbol_count;
 logic capture_active,capture_frame,next_capture,process_frame;
 logic [1:0] occupied,complete,invalid;
 logic [5:0] tail;
 logic [14:0] input_count;
 // input_count is zero whenever capture is idle, including the first sample.
 wire [14:0] received_count=input_count+1'b1;
 logic [14:0] written[0:1];
 wire taking=s_valid&&s_ready;
 wire first=taking&&!capture_active;
 wire fir_input_valid=taking||tail!=0;
 wire fir_input_last=tail==1;
 wire input_frame=capture_active?capture_frame:next_capture;
 wire signed [17:0] fir_input_re=tail!=0?18'sd0:s_re,fir_input_im=tail!=0?18'sd0:s_im;
 wire fv,fl;wire signed [17:0] fre,fim;
 logic [7:0] frame_pipe;
 wire write_frame=frame_pipe[7];
 assign cfg_ready=!capture_active&&occupied==0&&!reset_now;
 assign s_ready=configured&&!error&&!reset_now&&tail==0&&(capture_active||!occupied[next_capture])&&input_count<16608;
 // QAM64: the matched filter output is scaled by 1/4 (levels up to +-7 would saturate Q3.15).
 bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE),.SHIFT(ORDER==64?19:17)) filter(clk,rst,1'b1,fir_input_valid,fir_input_last,!capture_active,fir_input_re,fir_input_im,fv,fl,fre,fim);
 logic [41:0] energy[0:1][0:7];
 logic [1:0] clear_energy;
 logic power_valid,power_frame;
 logic [2:0] power_phase;
 logic [35:0] power_re,power_im;
 wire [36:0] power_sum={1'b0,power_re}+{1'b0,power_im};
 wire [335:0] energy_bus;
 genvar g;
 generate
 for(g=0;g<8;g=g+1) begin:g_energy
  assign energy_bus[g*42+:42]=energy[process_frame][g];
 end
 endgenerate
 typedef enum logic [2:0] {WAIT_FRAME,ACQUIRING,TRACKING,RETIRE} state_t;
 state_t state;
 logic acquisition_start,tracking_start;
 wire acquisition_busy,acquisition_done,tracking_busy,tracking_done;
 wire acq_qv,track_qv;
 wire signed [31:0] acq_pos,track_pos;
 wire [31:0] acq_tag;
 // Tracking tags: symbol and subcycle (14 bits), zero-extended for the sample reader.
 wire [13:0] track_tag;
 wire samples_valid;wire signed [17:0] samples_re,samples_im;wire [31:0] samples_tag;
 wire track_ce;
 wire reading_track=state==TRACKING||state==RETIRE;
 wire backend_rst=invalid[process_frame]?RESET_ACTIVE:rst;
 wire signed [31:0] sample_position=reading_track?track_pos:acq_pos;
 wire [7:0] unused_position_fraction=sample_position[7:0];
 wire sample_ce=reading_track?track_ce:1'b1;
 bpsk_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) samples(
  clk,backend_rst,fv,write_frame,written[write_frame],fre,fim,sample_ce,reading_track?track_qv:acq_qv,process_frame,
  sample_position[31:8],written[process_frame],reading_track?{18'd0,track_tag}:acq_tag,samples_valid,samples_re,samples_im,samples_tag);
 bpsk_acquire #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(ORDER),.AMPLITUDE(AMPLITUDE),.BLOCK_FIT(EQUALIZER!=0)) acquisition(
  clk,backend_rst,acquisition_start,energy_bus,training[160*BITS-1:32*BITS],acquisition_busy,acquisition_done,acquisition_confidence,
  acquisition_delay,acquisition_frequency,acquisition_phase,acquisition_gain,acquisition_score,
  acq_qv,acq_pos,acq_tag,samples_valid&&!reading_track,samples_re,samples_im,samples_tag);
 bpsk_track #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(ORDER),.AMPLITUDE(AMPLITUDE),
  .DIFFERENTIAL(DIFFERENTIAL),.FEEDFORWARD(FEEDFORWARD),.TIMING_LOOP(TIMING_LOOP),.PI4(PI4),.EQUALIZER(EQUALIZER)) tracking(
  clk,backend_rst,tracking_start,symbol_count,training,acquisition_delay,acquisition_frequency,acquisition_phase,acquisition_gain,
  written[process_frame],complete[process_frame],tracking_busy,tracking_done,track_ce,track_qv,track_pos,track_tag,
  samples_valid&&reading_track,samples_re,samples_im,samples_tag[13:0],
  m_valid,m_last,m_bit,m_index,m_ready,m_re,m_im,m_phase,m_frequency,m_correction,m_gain);
 assign acquisition_valid=acquisition_done;
 always_ff @(posedge clk) begin
  if(reset_now) begin
   configured<=0;error<=0;config_index<=0;capture_active<=0;next_capture<=0;process_frame<=0;
   occupied<=0;complete<=0;invalid<=0;tail<=0;input_count<=0;written[0]<=0;written[1]<=0;state<=WAIT_FRAME;
   power_valid<=0;clear_energy<=0;acquisition_start<=0;tracking_start<=0;
  end else begin
   acquisition_start<=0;tracking_start<=0;frame_pipe<={frame_pipe[6:0],input_frame};
   // Clear one clock after reservation, before the first FIR result arrives.
   // Registered enables keep the input handshake out of the energy reset path.
   clear_energy<={first&&input_frame,first&&!input_frame};
   for(integer j=0;j<8;j=j+1) begin
    if(clear_energy[0]) energy[0][j]<=0;
    if(clear_energy[1]) energy[1][j]<=0;
   end
   if(cfg_valid&&cfg_ready) begin
    configured<=0;
    // Shift in: after the 192 labels a complete configuration requires, label k sits at
    // [k*BITS +: BITS], where acquisition and tracking read it. No write-address decoder.
    training<={config_label,training[192*BITS-1:BITS]};
    config_index<=config_index+1'b1;
    if(cfg_last) begin
     config_index<=0;
     if(config_index==191&&cfg_count>=192&&cfg_count<=2048) begin configured<=1;symbol_count<=cfg_count;end
     else begin configured<=0;error<=1;end
    end else if(config_index==191) begin configured<=0;error<=1;config_index<=0;end
   end
   if(first) begin
    capture_active<=1;capture_frame<=next_capture;occupied[next_capture]<=1;complete[next_capture]<=0;invalid[next_capture]<=0;
    written[next_capture]<=0;input_count<=1;
   end else if(taking) input_count<=input_count+1'b1;
   if(taking&&(s_last||input_count>=b_u15_t'({3'd0,symbol_count}*15'd8+15'd63))) begin
    tail<=32;
    if(!s_last) begin invalid[input_frame]<=1;error<=1;end
    if(received_count<b_u15_t'({3'd0,symbol_count}*15'd8)||received_count>b_u15_t'({3'd0,symbol_count}*15'd8+15'd64)) begin invalid[input_frame]<=1;error<=1;end
   end else if(tail!=0) begin
    tail<=tail-1'b1;
    if(tail==1) begin capture_active<=0;next_capture<=!capture_frame;input_count<=0;end
   end
   if(fv) begin written[write_frame]<=written[write_frame]+1'b1;if(fl) complete[write_frame]<=1;end
   power_valid<=fv&&written[write_frame]>=64&&written[write_frame]<320;power_frame<=write_frame;power_phase<=written[write_frame][2:0];
   power_re<=$unsigned(b_s36_t'(fre)*b_s36_t'(fre));power_im<=$unsigned(b_s36_t'(fim)*b_s36_t'(fim));
   if(power_valid) energy[power_frame][power_phase]<=energy[power_frame][power_phase]+b_s42_t'(power_sum);
   case(state)
    WAIT_FRAME:if(occupied[process_frame]) begin
     if(complete[process_frame]&&invalid[process_frame]) state<=RETIRE;
     else if(written[process_frame]>=1344) begin acquisition_start<=1;state<=ACQUIRING;end
    end
    ACQUIRING:if(invalid[process_frame]) state<=RETIRE;else if(acquisition_done) begin tracking_start<=1;state<=TRACKING;end
    TRACKING:if(invalid[process_frame]) state<=RETIRE;else if(tracking_done) state<=RETIRE;
    RETIRE:if(complete[process_frame]) begin occupied[process_frame]<=0;process_frame<=!process_frame;state<=WAIT_FRAME;end
    default:state<=WAIT_FRAME;
   endcase
  end
 end
 wire unused_acquisition_busy=acquisition_busy,unused_tracking_busy=tracking_busy;
endmodule
