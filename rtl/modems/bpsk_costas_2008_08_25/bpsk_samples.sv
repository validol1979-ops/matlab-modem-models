// Two full frame buffers and one short buffer, four banks, synchronous reads. Cubic II=1, latency 7:
// the request is registered first so RAM addresses do not depend on the requester's logic.
module bpsk_samples #(
 parameter bit RESET_ACTIVE=1,
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",
 parameter int SHORT_SAMPLES=2048
)(
 input logic clk,rst,
 input logic wr_en,
 input logic [1:0] wr_frame,
 input logic [14:0] wr_index,
 input logic signed [17:0] wr_re,wr_im,
 input logic ce,s_valid,
 input logic [1:0] s_frame,
 input logic signed [23:0] s_position,
 input logic [14:0] s_length,
 input logic [31:0] s_tag,
 output logic m_valid,
 output logic signed [17:0] m_re,m_im,
 output logic [31:0] m_tag
);
 `include "bpsk_types.svh"
 wire reset_now=rst==RESET_ACTIVE;
 logic [5:0] valid_pipe;
 logic [31:0] tag_pipe[0:5];
 logic [1:0] start_bank;
 logic [3:0] present;
 wire signed [17:0] coef[0:3];
 wire signed [17:0] read_re[0:3],read_im[0:3];
 logic signed [17:0] ordered_re[0:3],ordered_im[0:3],coef_pipe[0:3];
 logic signed [35:0] prod_re[0:3],prod_im[0:3];
 // Adders stay in fabric: DSP cascades (PCOUT->PCIN) left no hold margin on Artix-7.
 (* use_dsp="no" *) logic signed [36:0] pair_re[0:1],pair_im[0:1];
 (* use_dsp="no" *) logic signed [37:0] sum_re,sum_im;
 wire signed [17:0] quant_re,quant_im;
 wire unused_re,unused_im;
 fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(31),.OUT_WIDTH(18),.OUT_FRAC(15)) qr(sum_re,quant_re,unused_re);
 fxp_round_sat #(.IN_WIDTH(38),.IN_FRAC(31),.OUT_WIDTH(18),.OUT_FRAC(15)) qi(sum_im,quant_im,unused_im);
 localparam int SHORT_ROW_WIDTH=$clog2(SHORT_SAMPLES)-2;
 initial begin
  if(SHORT_SAMPLES<8||SHORT_SAMPLES>16384||(SHORT_SAMPLES&(SHORT_SAMPLES-1))!=0)
   $fatal(1,"SHORT_SAMPLES must be a power of two in 8..16384");
 end
 logic p_valid;
 logic [1:0] p_frame;
 logic signed [23:0] p_position;
 logic [14:0] p_length;
 logic [31:0] p_tag;
 wire signed [31:0] base=(b_s32_t'(p_position)>>>8)-1;
 genvar g,bank;
 generate
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
 for(bank=0;bank<4;bank=bank+1) begin:g_bank
  // Separate sync_ram instances: Quartus does not infer RAM from two arrays
  // written through if/else in one process and silently expands them to registers.
  logic [35:0] rd_main,rd_tail,rd_short;
  logic select_tail,select_short;
  wire [35:0] rd_data=select_short?rd_short:select_tail?rd_tail:rd_main;
  wire [1:0] delta=b_u2_t'(bank)-base[1:0];
  wire [12:0] row=b_s13_t'((base+b_s32_t'({30'd0,delta}))>>>2);
  wire write_bank=wr_en&&wr_index[1:0]==b_u2_t'(bank);
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(13)) main_memory(.clk(clk),.wr_en(write_bank&&wr_frame<2&&!wr_index[14]),.rd_en(ce),
   .wr_addr({wr_frame[0],wr_index[13:2]}),.rd_addr({p_frame[0],row[11:0]}),.wr_data({wr_im,wr_re}),.rd_data(rd_main));
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(7)) tail_memory(.clk(clk),.wr_en(write_bank&&wr_frame<2&&wr_index[14]),.rd_en(ce),
   .wr_addr({wr_frame[0],wr_index[7:2]}),.rd_addr({p_frame[0],row[5:0]}),.wr_data({wr_im,wr_re}),.rd_data(rd_tail));
  // Dedicated small RAMs: widening the full RAM frame address would allocate
  // four full frames. The range guard also prevents any short-address wrapping.
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(SHORT_ROW_WIDTH)) short_memory(.clk(clk),
   .wr_en(write_bank&&wr_frame==2&&{17'd0,wr_index}<SHORT_SAMPLES),.rd_en(ce),
   .wr_addr(wr_index[SHORT_ROW_WIDTH+1:2]),.rd_addr(row[SHORT_ROW_WIDTH-1:0]),
   .wr_data({wr_im,wr_re}),.rd_data(rd_short));
  always_ff @(posedge clk) if(ce) begin select_tail<=row[12];select_short<=p_frame==2;end
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
   start_bank<=base[1:0];
   for(integer j=0;j<4;j=j+1) begin
    present[j]<=base+j>=0&&base+j<$signed({17'd0,p_length});
    ordered_re[j]<=present[j]?read_re[b_u2_t'(start_bank+b_u2_t'(j))]:18'sd0;
    ordered_im[j]<=present[j]?read_im[b_u2_t'(start_bank+b_u2_t'(j))]:18'sd0;
    coef_pipe[j]<=coef[j];
    prod_re[j]<=ordered_re[j]*coef_pipe[j];
    prod_im[j]<=ordered_im[j]*coef_pipe[j];
   end
   for(integer j=0;j<2;j=j+1) begin pair_re[j]<=$signed(prod_re[2*j])+$signed(prod_re[2*j+1]);pair_im[j]<=$signed(prod_im[2*j])+$signed(prod_im[2*j+1]);end
   sum_re<=$signed(pair_re[0])+$signed(pair_re[1]);sum_im<=$signed(pair_im[0])+$signed(pair_im[1]);
   m_re<=quant_re;m_im<=quant_im;
  end
 end
endmodule
