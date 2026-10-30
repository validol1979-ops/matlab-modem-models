// ORDER=2: differential BPSK on the diagonal (+-0.5+-0.5j).
// ORDER=4: QPSK, table index k counter-clockwise. Diagonal points use +-AMPLITUDE per axis
// in the order (+,+),(-,+),(-,-),(+,-); TX_AXIS=1 places unit points on the axes (k*90 degrees).
// ORDER=8: unit 8-PSK; TX_AXIS=1 places points at k*45 degrees, otherwise at 22.5+k*45.
// DIFFERENTIAL=1 advances the index by gray(label) per symbol; the state clears per frame.
// PI4 (ORDER=8, TX_AXIS=1): pi/4-QPSK, 2-bit labels, index advances by 2*gray(label)+1.
// ORDER=16: QAM16 at levels (+-1,+-3)*AMPLITUDE; the quadrant label[3:2] advances by its
// Gray code (quadrant-differential), label[1:0] is sent as is.
// ORDER=64: QAM64 at levels +-1..+-7 times 2^14 (half scale, inside 18 bits); the FIR
// rounds by 16 instead of 17, so the waveform is the exact Q15 one (peak 3.64).
// sps=8, 33-tap RRC. Output length = 8*symbols+32. Input TLAST ends the frame;
// frames may follow without reset. s_bit carries the symbol label (log2(ORDER) bits).
// A two-entry output buffer keeps m_ready off the FIR clock-enable path; the mapped
// symbol is registered before the FIR so s_valid/s_bit do not reach the DSP inputs.
module bpsk_tx #(parameter bit RESET_ACTIVE=1,parameter int ORDER=2,parameter int AMPLITUDE=ORDER==8?32768:ORDER==4?23170:16384,
 parameter bit DIFFERENTIAL=ORDER==2,parameter bit TX_AXIS=0,parameter bit PI4=0)(
 input logic clk,rst,s_valid,
 input logic [(ORDER==64?6:ORDER==16?4:ORDER==8?(PI4?2:3):ORDER==4?2:1)-1:0] s_bit,
 input logic s_last,
 output logic s_ready,
 input logic m_ready,
 output logic m_valid,m_last,
 output logic signed [17:0] m_re,m_im
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 logic [2:0] phase;
 logic [5:0] tail;
 logic first_sample,ending;
 wire reset_now=rst==RESET_ACTIVE;
 // Output buffer: entry 0 is the head. The FIR advances only while a slot is free.
 logic [1:0] buffered;
 logic [35:0] entry_data[0:1];
 logic [1:0] entry_last;
 wire ce=buffered!=2;
 wire f_valid,f_last;
 wire signed [17:0] f_re,f_im;
 wire push=f_valid&&ce,pop=m_valid&&m_ready;
 assign m_valid=buffered!=0;
 assign m_re=$signed(entry_data[0][17:0]);assign m_im=$signed(entry_data[0][35:18]);assign m_last=entry_last[0];
 wire taking=s_valid&&s_ready;
 wire fir_valid=taking||phase!=0||tail!=0;
 wire fir_last=tail==1;
 // Input stage of the FIR, advanced by the same enable.
 logic stage_valid,stage_last,stage_first;
 logic signed [17:0] stage_re;
 wire signed [17:0] sample_re;
 always_ff @(posedge clk) begin
  if(reset_now) stage_valid<=0;
  else if(ce) begin stage_valid<=fir_valid;stage_last<=fir_last;stage_first<=first_sample&&taking;stage_re<=sample_re;end
 end
 assign s_ready=ce&&phase==0&&tail==0&&!ending&&!reset_now;
 generate
 if(ORDER>=16) begin:g_qam16
  localparam int B=ORDER==64?6:4;
  logic [1:0] state;
  wire [1:0] quadrant=state+{s_bit[B-1],s_bit[B-1]^s_bit[B-2]};
  wire [B-1:0] index={quadrant,s_bit[B-3:0]};
  always_ff @(posedge clk) begin
   if(reset_now) state<=0;
   else if(ce) begin
    if(taking) state<=quadrant;
    else if(phase==0&&tail==1) state<=0;
   end
  end
  wire signed [3:0] la,lb;
  if(ORDER==64) begin:g_qam64_levels
   wire [7:0] levels=q64_levels(index);
   assign la=$signed(levels[7:4]);assign lb=$signed(levels[3:0]);
  end else begin:g_qam16_levels
   wire [5:0] levels=q16_levels(index);
   assign la={levels[5],levels[5:3]};assign lb={levels[2],levels[2:0]};
  end
  wire signed [17:0] point_re=b_s18_t'(qam_scale(18'sd16384,la)),point_im=b_s18_t'(qam_scale(18'sd16384,lb));
  assign sample_re=taking?point_re:18'sd0;
  wire signed [17:0] sample_im=taking?point_im:18'sd0;
  logic signed [17:0] stage_im;
  always_ff @(posedge clk) if(ce) stage_im<=sample_im;
  bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE),.SHIFT(ORDER==64?16:17)) filter(
   .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_last(stage_last),.s_first(stage_first),
   .s_re(stage_re),.s_im(stage_im),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(f_im));
 end else if(ORDER==8) begin:g_psk8
  wire [2:0] index;
  if(PI4) begin:g_pi4
   logic [2:0] state;
   assign index=state+{s_bit[1],s_bit[1]^s_bit[0],1'b1};
   always_ff @(posedge clk) begin
    if(reset_now) state<=0;
    else if(ce) begin
     if(taking) state<=index;
     else if(phase==0&&tail==1) state<=0;
    end
   end
  end else if(DIFFERENTIAL) begin:g_differential
   logic [2:0] state;
   assign index=state+{s_bit[2],s_bit[2]^s_bit[1],s_bit[1]^s_bit[0]};
   always_ff @(posedge clk) begin
    if(reset_now) state<=0;
    else if(ce) begin
     if(taking) state<=index;
     else if(phase==0&&tail==1) state<=0;
    end
   end
  end else begin:g_direct
   assign index=s_bit;
  end
  // Q15: unit, 1/sqrt(2), cos and sin of 22.5 degrees.
  localparam logic signed [17:0] A=18'sd32768,Q=18'sd23170,C=18'sd30274,S=18'sd12540;
  logic signed [17:0] point_re,point_im;
  always_comb begin
   if(TX_AXIS) case(index)
    3'd0:begin point_re=A;point_im=0;end
    3'd1:begin point_re=Q;point_im=Q;end
    3'd2:begin point_re=0;point_im=A;end
    3'd3:begin point_re=-Q;point_im=Q;end
    3'd4:begin point_re=-A;point_im=0;end
    3'd5:begin point_re=-Q;point_im=-Q;end
    3'd6:begin point_re=0;point_im=-A;end
    default:begin point_re=Q;point_im=-Q;end
   endcase else case(index)
    3'd0:begin point_re=C;point_im=S;end
    3'd1:begin point_re=S;point_im=C;end
    3'd2:begin point_re=-S;point_im=C;end
    3'd3:begin point_re=-C;point_im=S;end
    3'd4:begin point_re=-C;point_im=-S;end
    3'd5:begin point_re=-S;point_im=-C;end
    3'd6:begin point_re=S;point_im=-C;end
    default:begin point_re=C;point_im=-S;end
   endcase
  end
  assign sample_re=taking?point_re:18'sd0;
  wire signed [17:0] sample_im=taking?point_im:18'sd0;
  logic signed [17:0] stage_im;
  always_ff @(posedge clk) if(ce) stage_im<=sample_im;
  bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE)) filter(
   .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_last(stage_last),.s_first(stage_first),
   .s_re(stage_re),.s_im(stage_im),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(f_im));
 end else if(ORDER==4) begin:g_qpsk
  wire [1:0] index;
  if(DIFFERENTIAL) begin:g_differential
   logic [1:0] state;
   assign index=state+{s_bit[1],s_bit[1]^s_bit[0]};
   always_ff @(posedge clk) begin
    if(reset_now) state<=0;
    else if(ce) begin
     if(taking) state<=index;
     else if(phase==0&&tail==1) state<=0;
    end
   end
  end else begin:g_direct
   assign index=s_bit;
  end
  wire signed [17:0] point_re,point_im;
  if(TX_AXIS) begin:g_axis
   assign point_re=index[0]?18'sd0:(index[1]?-18'sd32768:18'sd32768);
   assign point_im=index[0]?(index[1]?-18'sd32768:18'sd32768):18'sd0;
  end else begin:g_diagonal
   // Index bit 1 is the Q sign, bit0^bit1 the I sign.
   localparam logic signed [17:0] POINT=b_s18_t'(AMPLITUDE);
   assign point_re=index[1]^index[0]?-POINT:POINT;
   assign point_im=index[1]?-POINT:POINT;
  end
  assign sample_re=taking?point_re:18'sd0;
  wire signed [17:0] sample_im=taking?point_im:18'sd0;
  logic signed [17:0] stage_im;
  always_ff @(posedge clk) if(ce) stage_im<=sample_im;
  bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE)) filter(
   .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_last(stage_last),.s_first(stage_first),
   .s_re(stage_re),.s_im(stage_im),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(f_im));
 end else begin:g_bpsk
  logic previous;
  always_ff @(posedge clk) begin
   if(reset_now) previous<=0;
   else if(ce) begin
    if(taking) previous<=previous^s_bit[0];
    else if(phase==0&&tail==1) previous<=0;
   end
  end
  assign sample_re=taking?(previous^s_bit[0]?-18'sd16384:18'sd16384):18'sd0;
  wire signed [17:0] unused_filter_im;
  assign f_im=f_re;
  bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE),.REAL_ONLY(1)) filter(
   .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_last(stage_last),.s_first(stage_first),
   .s_re(stage_re),.s_im(18'sd0),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(unused_filter_im));
 end
 endgenerate
 // push implies a free slot (buffered<2); push with pop implies buffered==1.
 always_ff @(posedge clk) begin
  if(reset_now) buffered<=0;
  else case({push,pop})
   2'b10:begin entry_data[buffered[0]]<={f_im,f_re};entry_last[buffered[0]]<=f_last;buffered<=buffered+1'b1;end
   2'b01:begin entry_data[0]<=entry_data[1];entry_last[0]<=entry_last[1];buffered<=buffered-1'b1;end
   2'b11:begin entry_data[0]<={f_im,f_re};entry_last[0]<=f_last;end
   default:begin end
  endcase
 end
 always_ff @(posedge clk) begin
  if(reset_now) begin phase<=0;tail<=0;first_sample<=1;ending<=0;end
  else if(ce) begin
   if(taking) begin phase<=1;first_sample<=0;ending<=s_last;end
   else if(phase!=0) begin
    phase<=phase+1'b1;
    if(phase==7&&ending) tail<=32;
   end else if(tail!=0) begin
    tail<=tail-1'b1;
    if(tail==1) begin first_sample<=1;ending<=0;end
   end
  end
 end
endmodule
