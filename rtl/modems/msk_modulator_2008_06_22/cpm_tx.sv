// Streaming MSK/GMSK transmitter (cpm_fixed.transmit): one bit expands to 8 samples of
// frequency +-1; GMSK appends the 32-sample tail of the Gaussian convolution, so a frame
// of N bits gives 8N (MSK) or 8N+32 (GMSK) samples. Input TLAST ends the frame; the next
// frame restarts the phase at 0. The mapped sample is registered before the modulator and
// a two-entry output buffer keeps m_ready off its clock enable (as in bpsk_tx).
module cpm_tx #(parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter bit GMSK=0)(
 input logic clk,rst,s_valid,
 input logic s_bit,
 input logic s_last,
 output logic s_ready,
 input logic m_ready,
 output logic m_valid,m_last,
 output logic signed [17:0] m_re,m_im
);
 `include "bpsk_types.svh"
 logic [2:0] phase;
 logic [5:0] tail;
 logic first_sample,ending,current;
 wire reset_now=rst==RESET_ACTIVE;
 logic [1:0] buffered;
 logic [35:0] entry_data[0:1];
 logic [1:0] entry_last;
 wire ce=buffered!=2;
 wire f_valid,f_last;
 wire signed [17:0] f_re,f_im,unused_frequency;
 wire push=f_valid&&ce,pop=m_valid&&m_ready;
 assign m_valid=buffered!=0;
 assign m_re=$signed(entry_data[0][17:0]);assign m_im=$signed(entry_data[0][35:18]);assign m_last=entry_last[0];
 wire taking=s_valid&&s_ready;
 assign s_ready=ce&&phase==0&&tail==0&&!ending&&!reset_now;
 // Sample stream: +-1 while a bit lasts (8 samples), 0 in the GMSK tail.
 wire sample_valid=taking||phase!=0||tail!=0;
 wire signed [1:0] sample_d=taking?(s_bit?2'sd1:-2'sd1):phase!=0?(current?2'sd1:-2'sd1):2'sd0;
 wire sample_last=GMSK?tail==1:(phase==7&&ending);
 logic stage_valid,stage_first,stage_last;
 logic signed [1:0] stage_d;
 always_ff @(posedge clk) begin
  if(reset_now) stage_valid<=0;
  else if(ce) begin stage_valid<=sample_valid;stage_first<=first_sample&&taking;stage_last<=sample_last;stage_d<=sample_d;end
 end
 cpm_modulator #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(GMSK),.TAG_WIDTH(1)) modulator(
  .clk(clk),.rst(rst),.ce(ce),.s_valid(stage_valid),.s_first(stage_first),.s_d(stage_d),.s_tag(stage_last),
  .m_valid(f_valid),.m_re(f_re),.m_im(f_im),.m_frequency(unused_frequency),.m_tag(f_last));
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
   if(taking) begin phase<=1;first_sample<=0;ending<=s_last;current<=s_bit;end
   else if(phase!=0) begin
    phase<=phase+1'b1;
    if(phase==7&&ending) begin
     if(GMSK) tail<=32;
     else begin first_sample<=1;ending<=0;end
    end
   end else if(tail!=0) begin
    tail<=tail-1'b1;
    if(tail==1) begin first_sample<=1;ending<=0;end
   end
  end
 end
endmodule
