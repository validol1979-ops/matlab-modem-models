// Finite offered-load integration: production WIDTH72 FIFO and LMS/NLMS.
`timescale 1ns/1ps
module axis_fifo_lms_load_tb;
  parameter int DEPTH=16, LOG2N=2;
  parameter bit RESET_ACTIVE=1;
  parameter RECIP_FILE="rtl/common/mem/lms_reciprocal.mem";
  localparam int CW=$clog2(DEPTH+1);
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic s_valid=0,s_last=0,s_ready,f_valid,f_last,f_ready,m_valid,m_last,m_ready=0,w_valid,w_last,w_ready=0;
  logic [71:0] s_data=0,f_data;
  logic [CW-1:0] level;
  logic cfg_valid=0,cfg_ready,configured,error,cfg_nlms;
  logic [LOG2N:0] cfg_taps;
  logic [17:0] cfg_mu;
  logic [33:0] cfg_eps;
  logic signed [17:0] m_pre,m_pim,m_ere,m_eim,w_re,w_im;
  axis_fifo #(.WIDTH(72),.DEPTH(DEPTH),.RESET_ACTIVE(RESET_ACTIVE)) fifo(
    .clk(clk),.rst(rst),.s_valid(s_valid),.s_last(s_last),.s_data(s_data),.s_ready(s_ready),
    .m_valid(f_valid),.m_last(f_last),.m_data(f_data),.m_ready(f_ready),.level(level));
  lms_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.RECIP_FILE(RECIP_FILE)) core(
    .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_nlms(cfg_nlms),.cfg_taps(cfg_taps),.cfg_mu(cfg_mu),.cfg_eps(cfg_eps),.configured(configured),.error(error),
    .s_valid(f_valid),.s_last(f_last),.s_re($signed(f_data[71:54])),.s_im($signed(f_data[53:36])),.s_dre($signed(f_data[35:18])),.s_dim($signed(f_data[17:0])),.s_ready(f_ready),
    .m_valid(m_valid),.m_last(m_last),.m_pre(m_pre),.m_pim(m_pim),.m_ere(m_ere),.m_eim(m_eim),.m_ready(m_ready),
    .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(w_ready));
  bit inject_hold_data=0,inject_hold_weights=0,corrupt_data_hold=0,corrupt_weight_hold=0;
  wire [71:0] checked_data={m_pre,m_pim,m_ere,m_eim}^{71'd0,corrupt_data_hold};
  wire [35:0] checked_weights={w_re,w_im}^{35'd0,corrupt_weight_hold};
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("LMS load source")) source_check(
    .clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data(s_data));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("LMS load FIFO output")) fifo_check(
    .clk(clk),.rst(rst),.valid(f_valid),.ready(f_ready),.last(f_last),.data(f_data));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("LMS load data output")) data_check(
    .clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data(checked_data));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("LMS load weight output")) weight_check(
    .clk(clk),.rst(rst),.valid(w_valid),.ready(w_ready),.last(w_last),.data(checked_weights));
  string vectors,trace_file;
  int fd,trace_fd,rc,total,horizon,expected_total,weight_total;
  int arrivals[],m_ready_mask[],w_ready_mask[],in_re[],in_im[],in_dre[],in_dim[],in_last[];
  int ex_pre[],ex_pim[],ex_ere[],ex_eim[],ex_last[],ex_wre[],ex_wim[],ex_wlast[];
  int cycle=-1,sent=0,consumed=0,seen=0,weights_seen=0,waits=0,peak=0,held_data=0,held_weights=0,held_fifo=0;
  bit scoring=0,inject_data,inject_weights,require_unblocked;
  always @(posedge clk) if(scoring&&rst!=RESET_ACTIVE) begin
    cycle++;
    if(cycle>=horizon) $fatal(1,"[TIMEOUT] LMS load schedule exhausted");
    if(error||!configured) $fatal(1,"[CONFIG] unexpected LMS load error/unconfigured");
    if(int'(level)!=sent-consumed) $fatal(1,"[CONSERVATION] LMS FIFO level mismatch");
    if(int'(level)>peak) peak=int'(level);
    $fdisplay(trace_fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
      cycle,s_valid,s_ready,s_valid?s_last:0,s_valid?$signed(s_data[71:54]):0,s_valid?$signed(s_data[53:36]):0,s_valid?$signed(s_data[35:18]):0,s_valid?$signed(s_data[17:0]):0,
      f_valid,f_ready,f_valid?f_last:0,f_valid?$signed(f_data[71:54]):0,f_valid?$signed(f_data[53:36]):0,f_valid?$signed(f_data[35:18]):0,f_valid?$signed(f_data[17:0]):0,
      m_valid,m_ready,m_valid?m_last:0,m_valid?m_pre:0,m_valid?m_pim:0,m_valid?m_ere:0,m_valid?m_eim:0,
      w_valid,w_ready,w_valid?w_last:0,w_valid?w_re:0,w_valid?w_im:0,level,configured,error);
    if(s_valid&&s_ready) sent++;
    if(s_valid&&!s_ready) begin
      waits++;
      if(require_unblocked) begin
        $display("LMS LOAD CAPACITY TARGET cycle=%0d depth=%0d level=%0d",cycle,DEPTH,level);
        $fatal(1,"[CAPACITY] LMS due word blocked at short depth");
      end
    end
    if(f_valid&&!f_ready) held_fifo++;
    if(f_valid&&f_ready) begin
      if(consumed>=total||f_data!=={18'(in_re[consumed]),18'(in_im[consumed]),18'(in_dre[consumed]),18'(in_dim[consumed])}||f_last!==1'(in_last[consumed]))
        $fatal(1,"[FIFO_DATA] LMS FIFO transfer changed word/order/TLAST");
      consumed++;
    end
    if(m_valid&&!m_ready) begin
      held_data++;
      if(inject_hold_data&&!corrupt_data_hold) $display("LMS LOAD HOLD DATA TARGET cycle=%0d valid=1 ready=0",cycle);
    end
    if(w_valid&&!w_ready) begin
      held_weights++;
      if(inject_hold_weights&&!corrupt_weight_hold) $display("LMS LOAD HOLD WEIGHTS TARGET cycle=%0d valid=1 ready=0",cycle);
    end
    if(m_valid&&m_ready) begin
      if(seen>=total) $fatal(1,"[NUMERIC] extra LMS load output");
      if(inject_data&&seen==0) $display("LMS LOAD DATA TARGET cycle=%0d index=%0d",cycle,seen);
      if(m_pre!==18'(ex_pre[seen]+(inject_data?1:0))||m_pim!==18'(ex_pim[seen])||m_ere!==18'(ex_ere[seen])||m_eim!==18'(ex_eim[seen])||m_last!==1'(ex_last[seen]))
        $fatal(1,"[NUMERIC] LMS load prediction/error/TLAST mismatch");
      seen++;
    end
    if(w_valid&&w_ready) begin
      if(weights_seen>=weight_total) $fatal(1,"[WEIGHTS] extra LMS load weight");
      if(inject_weights&&weights_seen==0) $display("LMS LOAD WEIGHTS TARGET cycle=%0d index=%0d",cycle,weights_seen);
      if(w_re!==18'(ex_wre[weights_seen]+(inject_weights?1:0))||w_im!==18'(ex_wim[weights_seen])||w_last!==1'(ex_wlast[weights_seen]))
        $fatal(1,"[WEIGHTS] LMS load final weight/TLAST mismatch");
      weights_seen++;
    end
  end
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("TRACE=%s",trace_file)) $fatal(1,"missing LMS load paths");
    inject_data=$test$plusargs("INJECT_DATA");inject_weights=$test$plusargs("INJECT_WEIGHTS");
    inject_hold_data=$test$plusargs("INJECT_HOLD_DATA");inject_hold_weights=$test$plusargs("INJECT_HOLD_WEIGHTS");require_unblocked=$test$plusargs("REQUIRE_UNBLOCKED");
    fd=$fopen({vectors,"/load.txt"},"r");if(!fd) $fatal(1,"missing LMS load schedule");
    rc=$fscanf(fd,"%d %d",total,horizon);if(rc!=2||total<1||horizon<1) $fatal(1,"invalid LMS load header");
    arrivals=new[total];m_ready_mask=new[horizon];w_ready_mask=new[horizon];
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d",arrivals[j]);if(rc!=1) $fatal(1,"truncated LMS arrivals");end
    for(int j=0;j<horizon;j++) begin rc=$fscanf(fd,"%d %d",m_ready_mask[j],w_ready_mask[j]);if(rc!=2) $fatal(1,"truncated LMS readiness");end
    $fclose(fd);
    in_re=new[total];in_im=new[total];in_dre=new[total];in_dim=new[total];in_last=new[total];
    ex_pre=new[total];ex_pim=new[total];ex_ere=new[total];ex_eim=new[total];ex_last=new[total];
    fd=$fopen({vectors,"/input.txt"},"r");rc=$fscanf(fd,"%d",expected_total);if(rc!=1||expected_total!=total) $fatal(1,"LMS input count");
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d %d %d %d %d",in_re[j],in_im[j],in_dre[j],in_dim[j],in_last[j]);if(rc!=5) $fatal(1,"truncated LMS input");end
    $fclose(fd);
    fd=$fopen({vectors,"/expected.txt"},"r");rc=$fscanf(fd,"%d",expected_total);if(rc!=1||expected_total!=total) $fatal(1,"LMS expected count");
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d %d %d %d %d",ex_pre[j],ex_pim[j],ex_ere[j],ex_eim[j],ex_last[j]);if(rc!=5) $fatal(1,"truncated LMS expected");end
    $fclose(fd);
    fd=$fopen({vectors,"/weights.txt"},"r");rc=$fscanf(fd,"%d",weight_total);if(rc!=1||weight_total<1) $fatal(1,"LMS weight count");
    ex_wre=new[weight_total];ex_wim=new[weight_total];ex_wlast=new[weight_total];
    for(int j=0;j<weight_total;j++) begin rc=$fscanf(fd,"%d %d %d",ex_wre[j],ex_wim[j],ex_wlast[j]);if(rc!=3) $fatal(1,"truncated LMS weights");end
    $fclose(fd);
    fd=$fopen({vectors,"/config.txt"},"r");rc=$fscanf(fd,"%d %d %d %d",cfg_nlms,cfg_taps,cfg_mu,cfg_eps);if(rc!=4) $fatal(1,"LMS configuration count");$fclose(fd);
    trace_fd=$fopen(trace_file,"w");if(!trace_fd) $fatal(1,"missing LMS trace output");
    $fdisplay(trace_fd,"cycle,s_valid,s_ready,s_last,s_re,s_im,s_dre,s_dim,f_valid,f_ready,f_last,f_re,f_im,f_dre,f_dim,m_valid,m_ready,m_last,m_pre,m_pim,m_ere,m_eim,w_valid,w_ready,w_last,w_re,w_im,level,configured,error");
    repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
    @(negedge clk);cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    if(!configured||error) $fatal(1,"[CONFIG] LMS load configuration not accepted");
    @(negedge clk);scoring=1;m_ready=1'(m_ready_mask[0]);w_ready=1'(w_ready_mask[0]);
    fork
      begin
        for(int j=0;j<total;j++) begin
          while(cycle+1<arrivals[j]) begin s_valid=0;@(negedge clk);end
          s_valid=1;s_last=1'(in_last[j]);s_data={18'(in_re[j]),18'(in_im[j]),18'(in_dre[j]),18'(in_dim[j])};
          do begin @(posedge clk);if(s_ready) break;@(negedge clk);end while(1);
          @(negedge clk);
        end
        s_valid=0;s_last=0;
      end
      begin
        int quiet=0;
        while(quiet<5) begin
          @(negedge clk);
          if(seen==total&&weights_seen==weight_total) quiet++;
          if(cycle+1<horizon) begin m_ready=1'(m_ready_mask[cycle+1]);w_ready=1'(w_ready_mask[cycle+1]);end
          if(inject_hold_data&&held_data>0&&!corrupt_data_hold) corrupt_data_hold=1;
          if(inject_hold_weights&&held_weights>0&&!corrupt_weight_hold) corrupt_weight_hold=1;
        end
      end
    join
    if(sent!=total||consumed!=total||seen!=total||weights_seen!=weight_total||level!=0||m_valid||w_valid) $fatal(1,"[COVERAGE] incomplete LMS load drain");
    $fclose(trace_fd);
    $display("PASS LMS FIFO LOAD depth=%0d words=%0d weights=%0d wait=%0d peak=%0d held_data=%0d held_weights=%0d held_fifo=%0d",DEPTH,total,weight_total,waits,peak,held_data,held_weights,held_fifo);
    $finish;
  end
  initial begin #5000000;$fatal(1,"[TIMEOUT] LMS load test did not finish");end
endmodule
