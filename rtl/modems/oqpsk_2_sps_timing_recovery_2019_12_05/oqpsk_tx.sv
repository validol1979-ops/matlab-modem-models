// Streaming OQPSK transmitter (oqpsk_fixed.transmit): one label per 8 samples, the I
// impulse at sample 8k and the Q impulse at 8k+4 (half-symbol offset), per-axis Q15
// amplitude 23170; label 0..3 = (+,+),(-,+),(-,-),(+,-) so the I sign is negative when
// bit1^bit0 and the Q sign when bit1. A frame of N labels is the same 33-tap RRC as BPSK
// applied to 8N+4 mapped samples, so the frame outputs 8N+4+32 samples: the tail counter
// becomes 36 instead of the 32 of bpsk_tx. Input TLAST ends the frame; frames may follow
// without reset. As in bpsk_tx the mapped sample is registered before the FIR and a
// two-entry output buffer keeps m_ready off the FIR clock-enable path.
module oqpsk_tx #(parameter bit RESET_ACTIVE=1)(
 input logic clk,rst,s_valid,
 input logic [1:0] s_bit,
 input logic s_last,
 output logic s_ready,
 input logic m_ready,
 output logic m_valid,m_last,
 output logic signed [17:0] m_re,m_im
);
 `include "bpsk_types.svh"
 logic [2:0] phase;
 logic [5:0] tail;
 logic first_sample,ending;
 // Q impulse of the symbol taken, emitted half a symbol later at phase 4.
 logic signed [17:0] q_held;
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
 localparam logic signed [17:0] POINT=b_s18_t'(23170);
 // Sample stream: I impulse when the symbol is taken, Q impulse four samples later.
 wire signed [17:0] sample_re=taking?(s_bit[1]^s_bit[0]?-POINT:POINT):18'sd0;
 wire signed [17:0] sample_im=(phase==3'd4)?q_held:18'sd0;
 // Input stage of the FIR, advanced by the same enable.
 logic stage_valid,stage_last,stage_first;
 logic signed [17:0] stage_re,stage_im;
 always_ff @(posedge clk) begin
  if(reset_now) stage_valid<=0;
  else if(ce) begin
   stage_valid<=fir_valid;stage_last<=fir_last;stage_first<=first_sample&&taking;
   stage_re<=sample_re;stage_im<=sample_im;
  end
 end
 assign s_ready=ce&&phase==0&&tail==0&&!ending&&!reset_now;
 bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE)) filter(
  .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_last(stage_last),.s_first(stage_first),
  .s_re(stage_re),.s_im(stage_im),.m_valid(f_valid),.m_last(f_last),.m_re(f_re),.m_im(f_im));
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
  if(reset_now) begin phase<=0;tail<=0;first_sample<=1;ending<=0;q_held<=0;end
  else if(ce) begin
   if(taking) begin
    phase<=1;first_sample<=0;ending<=s_last;
    q_held<=s_bit[1]?-POINT:POINT;
   end else if(phase!=0) begin
    phase<=phase+1'b1;
    if(phase==7&&ending) tail<=36;
   end else if(tail!=0) begin
    tail<=tail-1'b1;
    if(tail==1) begin first_sample<=1;ending<=0;end
   end
  end
 end
endmodule
