// Phase LUT, complex rotation, optional AGC. Latency=7, II=1.
module bpsk_rotate #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables"
)(
 input logic clk,rst,ce,s_valid,
 input logic signed [17:0] s_re,s_im,
 input logic [11:0] s_phase,
 input logic [24:0] s_gain,
 input logic [31:0] s_tag,
 output logic m_valid,
 output logic signed [17:0] m_re,m_im,
 output logic [31:0] m_tag
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 wire signed [17:0] c,s;
 logic signed [17:0] re0,im0;
 sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) cosine_real(clk,ce,s_phase,c);
 sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) cosine_imag(clk,ce,b_s12_t'(s_phase-12'd1024),s);
 logic signed [35:0] ac,bs,bc,as_product;
 // Sums stay in fabric: a DSP PCOUT->PCIN cascade gave negative hold in Artix-7.
 (* use_dsp="no" *) logic signed [36:0] sum_re,sum_im;
 logic signed [17:0] rotated_re,rotated_im;
 logic signed [42:0] gained_re,gained_im;
 logic signed [23:0] rounded_re,rounded_im;
 logic [24:0] gain_pipe[0:3];
 logic [31:0] tag_pipe[0:6];
 logic [6:0] valid_pipe;
 assign m_valid=valid_pipe[6]&&(rst!=RESET_ACTIVE);assign m_tag=tag_pipe[6];
 always_ff @(posedge clk) begin
  if(rst==RESET_ACTIVE) valid_pipe<=0;
  else if(ce) begin
   valid_pipe<={valid_pipe[5:0],s_valid};tag_pipe[0]<=s_tag;gain_pipe[0]<=s_gain;
   for(integer j=1;j<7;j=j+1) tag_pipe[j]<=tag_pipe[j-1];
   for(integer j=1;j<4;j=j+1) gain_pipe[j]<=gain_pipe[j-1];
   re0<=s_re;im0<=s_im;
   ac<=re0*c;bs<=im0*s;bc<=im0*c;as_product<=re0*s;
   sum_re<=$signed(ac)+$signed(bs);sum_im<=$signed(bc)-$signed(as_product);
   rotated_re<=b_sat(b_round(b_s64_t'(sum_re),17));rotated_im<=b_sat(b_round(b_s64_t'(sum_im),17));
   gained_re<=rotated_re*$signed({1'b0,gain_pipe[3]});gained_im<=rotated_im*$signed({1'b0,gain_pipe[3]});
   rounded_re<=b_s24_t'(b_round(b_s64_t'(gained_re),20));rounded_im<=b_s24_t'(b_round(b_s64_t'(gained_im),20));
   m_re<=b_sat(b_s64_t'(rounded_re));m_im<=b_sat(b_s64_t'(rounded_im));
  end
 end
endmodule
