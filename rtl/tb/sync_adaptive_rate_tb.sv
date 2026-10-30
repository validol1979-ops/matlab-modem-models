// Interface cycles only; no functional golden outputs and no latency model.
`timescale 1ns/1ps
module sync_adaptive_rate_tb;
  // KIND: 0 Costas,1 Gardner,2 LMS,3 NLMS,4 RLS.
  parameter int KIND=0,LOG2N=2,TAPS=3,OUTPUT_COUNT=128,FRAMES=32,GAP=0;
  parameter bit RESET_ACTIVE=1,BACKPRESSURE=0;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  parameter RECIP_FILE="rtl/common/mem/lms_reciprocal.mem";
  logic clk=0,rst=RESET_ACTIVE;always #5 clk=!clk;
  logic cfg_valid=0,cfg_ready,configured;
  longint unsigned cfg[0:4];
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0,s_dre=0,s_dim=0;
  logic m_valid,m_last,m_ready=1,w_valid,w_last,w_ready=1,error;
  logic [71:0] m_data;
  logic [35:0] w_data;
  logic [135:0] cfg_data;
  localparam int CFGW_LMS=LOG2N+54,CFGW_RLS=LOG2N+107;
  if(KIND==0)begin:g_costas
    logic signed [17:0] re,im;logic signed [31:0] phase;
    costas_loop #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_k1(32'(cfg[0])),.cfg_k2(32'(cfg[1])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_re(re),.m_im(im),.m_phase(phase),.m_ready(m_ready));
    assign cfg_data={72'd0,32'(cfg[0]),32'(cfg[1])};assign m_data={4'd0,re,im,phase};
    assign w_valid=0;assign w_last=0;assign w_data=0;assign error=0;
  end else if(KIND==1)begin:g_gardner
    logic signed [17:0] re,im;logic signed [31:0] position;
    gardner_timing #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_sps(8'(cfg[0])),.cfg_count(16'(cfg[1])),.cfg_position(48'(cfg[2])),
      .cfg_k3(32'(cfg[3])),.cfg_k4(32'(cfg[4])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_re(re),.m_im(im),.m_position(position),.m_ready(m_ready),.error(error));
    assign cfg_data={8'(cfg[0]),16'(cfg[1]),48'(cfg[2]),32'(cfg[3]),32'(cfg[4])};assign m_data={4'd0,re,im,position};
    assign w_valid=0;assign w_last=0;assign w_data=0;
  end else if(KIND==2||KIND==3)begin:g_lms
    logic signed [17:0] pre,pim,ere,eim,wr,wi;
    lms_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.RECIP_FILE(RECIP_FILE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_nlms(1'(cfg[0])),.cfg_taps((LOG2N+1)'(cfg[1])),.cfg_mu(18'(cfg[2])),.cfg_eps(34'(cfg[3])),
      .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_dre(s_dre),.s_dim(s_dim),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_pre(pre),.m_pim(pim),.m_ere(ere),.m_eim(eim),.m_ready(m_ready),
      .w_valid(w_valid),.w_last(w_last),.w_re(wr),.w_im(wi),.w_ready(w_ready),.error(error));
    assign cfg_data={{(136-CFGW_LMS){1'b0}},1'(cfg[0]),(LOG2N+1)'(cfg[1]),18'(cfg[2]),34'(cfg[3])};
    assign m_data={pre,pim,ere,eim};assign w_data={wr,wi};
  end else begin:g_rls
    logic signed [17:0] pre,pim,ere,eim,wr,wi;
    rls_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_taps((LOG2N+1)'(cfg[0])),.cfg_p0(44'(cfg[1])),.cfg_lambda(30'(cfg[2])),.cfg_invl(32'(cfg[3])),
      .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_dre(s_dre),.s_dim(s_dim),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_pre(pre),.m_pim(pim),.m_ere(ere),.m_eim(eim),.m_ready(m_ready),
      .w_valid(w_valid),.w_last(w_last),.w_re(wr),.w_im(wi),.w_ready(w_ready),.error(error));
    assign cfg_data={{(136-CFGW_RLS){1'b0}},(LOG2N+1)'(cfg[0]),44'(cfg[1]),30'(cfg[2]),32'(cfg[3])};
    assign m_data={pre,pim,ere,eim};assign w_data={wr,wi};
  end
  axis_check #(.WIDTH(136),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rate cfg")) check_cfg
    (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data(cfg_data));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rate input")) check_input
    (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im,s_dre,s_dim}));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rate m")) check_m
    (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data(m_data));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rate w")) check_w
    (.clk(clk),.rst(rst),.valid(w_valid),.ready(w_ready),.last(w_last),.data(w_data));
  int in_re[],in_im[],in_dre[],in_dim[],input_length;
  int fd,rc,cfd,trace_fd,accepted_in=0,accepted_out=0,accepted_weights=0,input_frames=0,output_frames=0,weight_frames=0;
  bit capture=0;
  longint cycle=0;
  string directory,trace;
  always @(posedge clk) begin
    cycle++;
    if(rst!=RESET_ACTIVE&&capture) begin
      if($isunknown({cfg_valid,cfg_ready,configured,s_valid,s_ready,m_valid,m_ready,w_valid,w_ready,error})) $fatal(1,"[RATE] unknown control");
      $fdisplay(trace_fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",cycle,cfg_valid,cfg_ready,configured,
                s_valid,s_ready,(s_valid?s_last:0),m_valid,m_ready,(m_valid?m_last:0),w_valid,w_ready,(w_valid?w_last:0),error);
      if(error) $fatal(1,"[RATE] DUT error");
      if(s_valid&&s_ready) begin accepted_in++;if(s_last) input_frames++;end
      if(m_valid&&m_ready) begin accepted_out++;if(m_last) output_frames++;end
      if(w_valid&&w_ready) begin accepted_weights++;if(w_last) weight_frames++;end
    end
  end
  // Exactly the same known duty policy applies to both independent outputs.
  always @(negedge clk) begin m_ready=!BACKPRESSURE||(cycle%8)<5;w_ready=!BACKPRESSURE||(cycle%8)<5;end
  initial begin
    int xr,xi,dr,di,last;
    if(!$value$plusargs("VECTORS=%s",directory)||!$value$plusargs("TRACE=%s",trace)) $fatal(1,"[RATE] input paths required");
    cfd=$fopen({directory,"/rate_cfg.txt"},"r");
    if(!cfd) $fatal(1,"[RATE] missing cfg");
    if(KIND==0)rc=$fscanf(cfd,"%d %d",cfg[0],cfg[1]);
    else if(KIND==1)rc=$fscanf(cfd,"%d %d %d %d %d",cfg[0],cfg[1],cfg[2],cfg[3],cfg[4]);
    else rc=$fscanf(cfd,"%d %d %d %d",cfg[0],cfg[1],cfg[2],cfg[3]);
    if(rc!=(KIND==0?2:KIND==1?5:4)) $fatal(1,"[RATE] cfg format");
    $fclose(cfd);fd=$fopen({directory,"/rate_in.txt"},"r");
    if(!fd||$fscanf(fd,"%d",input_length)!=1||input_length<4) $fatal(1,"[RATE] bad input header");
    in_re=new[input_length];in_im=new[input_length];in_dre=new[input_length];in_dim=new[input_length];
    for(int i=0;i<input_length;i++) begin
      if($fscanf(fd,"%d %d %d %d",xr,xi,dr,di)!=4) $fatal(1,"[RATE] bad input row");
      in_re[i]=xr;in_im[i]=xi;in_dre[i]=dr;in_dim[i]=di;
    end
    $fclose(fd);trace_fd=$fopen(trace,"w");if(!trace_fd) $fatal(1,"[RATE] trace unavailable");
    $fdisplay(trace_fd,"cycle,cfg_valid,cfg_ready,configured,s_valid,s_ready,s_last,m_valid,m_ready,m_last,w_valid,w_ready,w_last,error");
    repeat(5) @(negedge clk);rst=!RESET_ACTIVE;capture=1;
    @(negedge clk);cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    if(!configured||error) $fatal(1,"[RATE] configuration rejected");
    for(int frame=0;frame<FRAMES;frame++) begin
      if(frame>0&&GAP>0) begin @(negedge clk);s_valid=0;repeat(GAP-1) @(negedge clk);end
      for(int sample=0;sample<input_length;sample++) begin
        @(negedge clk);s_valid=1;s_last=sample==input_length-1;
        s_re=18'(in_re[sample]);s_im=18'(in_im[sample]);s_dre=18'(in_dre[sample]);s_dim=18'(in_dim[sample]);
        for(int guard=0;guard<200000;guard++) begin
          @(posedge clk);if(s_ready)break;
          if(guard==199999)$fatal(1,"[RATE] input never accepted");
        end
      end
    end
    @(negedge clk);s_valid=0;s_last=0;
    for(int guard=0;guard<500000&&(accepted_out<FRAMES*OUTPUT_COUNT||(KIND>=2&&accepted_weights<FRAMES*TAPS));guard++) @(negedge clk);
    repeat(20) @(negedge clk);
    if(accepted_in!=FRAMES*input_length||accepted_out!=FRAMES*OUTPUT_COUNT||input_frames!=FRAMES||output_frames!=FRAMES||
       (KIND>=2&&(accepted_weights!=FRAMES*TAPS||weight_frames!=FRAMES))) $fatal(1,"[RATE] incomplete channels");
    capture=0;$fclose(trace_fd);
    $display("PASS SYNC ADAPTIVE RATES: %0d inputs, %0d outputs, %0d weights, %0d frames",accepted_in,accepted_out,accepted_weights,FRAMES);$finish;
  end
  initial begin #100000000;$fatal(1,"[RATE] meter timeout");end
endmodule
