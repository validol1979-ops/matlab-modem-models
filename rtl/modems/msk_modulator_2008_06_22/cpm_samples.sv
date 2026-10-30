// Two frame buffers in eight sample banks (index mod 8), synchronous reads. One request
// gives the cubic interpolation at position p (lane 0) and at p + 1 sample (lane 1, same
// fraction): the five taps base-1..base+3 always fall in distinct banks. Latency 7,
// II=1; arithmetic as in bpsk_samples (taps outside 0..length-1 read as zero).
// Per bank and frame: 2048 main rows plus a 16-row tail (frames up to 16512 samples).
module cpm_samples #(
 parameter bit RESET_ACTIVE=1,
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables"
)(
 input logic clk,rst,
 input logic wr_en,wr_frame,
 input logic [14:0] wr_index,
 input logic signed [17:0] wr_re,wr_im,
 input logic ce,s_valid,s_frame,
 input logic signed [23:0] s_position,
 input logic [14:0] s_length,
 input logic [14:0] s_tag,
 output logic m_valid,
 output logic signed [17:0] m_re0,m_im0,m_re1,m_im1,
 output logic [14:0] m_tag
);
 `include "bpsk_types.svh"
 wire reset_now=rst==RESET_ACTIVE;
 logic [5:0] valid_pipe;
 logic [14:0] tag_pipe[0:5];
 logic [2:0] start_bank;
 logic [4:0] present;
 wire signed [17:0] coef[0:3];
 wire signed [17:0] read_re[0:7],read_im[0:7];
 logic signed [17:0] ordered_re[0:4],ordered_im[0:4],coef_pipe[0:3];
 logic signed [35:0] prod_re[0:1][0:3],prod_im[0:1][0:3];
 // Adders stay in fabric: DSP cascades (PCOUT->PCIN) left no hold margin on Artix-7.
 (* use_dsp="no" *) logic signed [36:0] pair_re[0:1][0:1],pair_im[0:1][0:1];
 (* use_dsp="no" *) logic signed [37:0] sum_re[0:1],sum_im[0:1];
 wire signed [17:0] quant_re[0:1],quant_im[0:1];
 wire unused_overflow[0:1][0:1];
 logic p_valid,p_frame;
 logic signed [23:0] p_position;
 logic [14:0] p_length;
 logic [14:0] p_tag;
 wire signed [31:0] base=(b_s32_t'(p_position)>>>8)-1;
 genvar g,bank,lane;
 generate
 for(lane=0;lane<2;lane=lane+1) begin:g_lane
  fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(31),.OUT_WIDTH(18),.OUT_FRAC(15)) qr(sum_re[lane],quant_re[lane],unused_overflow[lane][0]);
  fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(31),.OUT_WIDTH(18),.OUT_FRAC(15)) qi(sum_im[lane],quant_im[lane],unused_overflow[lane][1]);
 end
 for(g=0;g<4;g=g+1) begin:g_weights
  (* rom_style="block",romstyle="M10K" *) logic signed [17:0] weights[0:255];
  logic signed [17:0] coefficient;
  if(g==0) begin:g_init0
   initial $readmemb({TABLE_DIR,"/cubic0.mem"},weights);
  end
  if(g==1) begin:g_init1
   initial $readmemb({TABLE_DIR,"/cubic1.mem"},weights);
  end
  if(g==2) begin:g_init2
   initial $readmemb({TABLE_DIR,"/cubic2.mem"},weights);
  end
  if(g==3) begin:g_init3
   initial $readmemb({TABLE_DIR,"/cubic3.mem"},weights);
  end
  always_ff @(posedge clk) if(ce) coefficient<=weights[p_position[7:0]];
  assign coef[g]=coefficient;
 end
 for(bank=0;bank<8;bank=bank+1) begin:g_bank
  // Separate sync_ram instances (Quartus expands two arrays in one process to registers).
  logic [35:0] rd_main,rd_tail;
  logic select_tail;
  wire [35:0] rd_data=select_tail?rd_tail:rd_main;
  wire [2:0] delta=b_u3_t'(bank)-base[2:0];
  wire [11:0] row=b_s12_t'((base+b_s32_t'({29'd0,delta}))>>>3);
  wire write_bank=wr_en&&wr_index[2:0]==b_u3_t'(bank);
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(12)) main_memory(.clk(clk),.wr_en(write_bank&&!wr_index[14]),.rd_en(ce),
   .wr_addr({wr_frame,wr_index[13:3]}),.rd_addr({p_frame,row[10:0]}),.wr_data({wr_im,wr_re}),.rd_data(rd_main));
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(5)) tail_memory(.clk(clk),.wr_en(write_bank&&wr_index[14]),.rd_en(ce),
   .wr_addr({wr_frame,wr_index[6:3]}),.rd_addr({p_frame,row[3:0]}),.wr_data({wr_im,wr_re}),.rd_data(rd_tail));
  always_ff @(posedge clk) if(ce) select_tail<=row[11];
  assign read_re[bank]=$signed(rd_data[17:0]);assign read_im[bank]=$signed(rd_data[35:18]);
 end
 endgenerate
 assign m_valid=valid_pipe[5]&&!reset_now;assign m_tag=tag_pipe[5];
 always_ff @(posedge clk) begin
  if(reset_now) begin valid_pipe<=0;p_valid<=0;end
  else if(ce) begin
   p_valid<=s_valid;p_frame<=s_frame;p_position<=s_position;p_length<=s_length;p_tag<=s_tag;
   valid_pipe<={valid_pipe[4:0],p_valid};tag_pipe[0]<=p_tag;
   for(integer j=1;j<6;j=j+1) tag_pipe[j]<=tag_pipe[j-1];
   start_bank<=base[2:0];
   for(integer j=0;j<5;j=j+1) begin
    present[j]<=base+j>=0&&base+j<$signed({17'd0,p_length});
    ordered_re[j]<=present[j]?read_re[b_u3_t'(start_bank+b_u3_t'(j))]:18'sd0;
    ordered_im[j]<=present[j]?read_im[b_u3_t'(start_bank+b_u3_t'(j))]:18'sd0;
   end
   for(integer j=0;j<4;j=j+1) begin
    coef_pipe[j]<=coef[j];
    prod_re[0][j]<=ordered_re[j]*coef_pipe[j];prod_im[0][j]<=ordered_im[j]*coef_pipe[j];
    prod_re[1][j]<=ordered_re[j+1]*coef_pipe[j];prod_im[1][j]<=ordered_im[j+1]*coef_pipe[j];
   end
   for(integer l=0;l<2;l=l+1) begin
    for(integer j=0;j<2;j=j+1) begin
     pair_re[l][j]<=$signed(prod_re[l][2*j])+$signed(prod_re[l][2*j+1]);pair_im[l][j]<=$signed(prod_im[l][2*j])+$signed(prod_im[l][2*j+1]);
    end
    sum_re[l]<=$signed(pair_re[l][0])+$signed(pair_re[l][1]);sum_im[l]<=$signed(pair_im[l][0])+$signed(pair_im[l][1]);
   end
   m_re0<=quant_re[0];m_im0<=quant_im[0];m_re1<=quant_re[1];m_im1<=quant_im[1];
  end
 end
endmodule
