// Integer 3x3 MMSE / zero-forcing solver (rtl/common/mmse2.sv) against the integer model
// (tools/mmse_cases.py vectors). The bench drives the nine Q15 entries of H in row-major order
// (one cfg transfer each, cfg_last and cfg_lambda on h22), waits for configured (and error == 0),
// then streams the observation triples of in.txt (s_last on the last o1 of a transaction). The DUT
// answers with y0, y1, y2 per triple scored against out.txt exactly (m_last on the last output) and the
// run must end with error == 0. +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready), +STALL_OUTPUT random m_ready
// (~2/3 high), +INJECT_MISMATCH corrupts the first expected output re (negative control,
// [NUMERIC]). +SINGULAR configures H = [[1,1],[1,1]] with lambda 0 instead and only requires the
// error flag to rise. +MID_RESET drives half of the first transaction, resets the DUT in the middle
// of it and requires it to come back silent (no output valid, configured low, no error) before the
// configuration and the whole stream are driven again from the start (nothing is scored during that
// warm-up phase). +OUT_RESET is the same block, but the warm-up drives the WHOLE first transaction
// and the reset lands as soon as the DUT has delivered at least one accepted output (otherwise
// [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: the first four entries of H (never the one with
// cfg_last, where the DUT starts computing the weights) are driven, the DUT resets at the next
// negedge, then the configuration and the whole observation stream run again from the start and only
// then are scored.
`timescale 1ns/1ps
module mmse3_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int GRAM_WIDTH=38, SUM_WIDTH=84;
  parameter int ADJ_WIDTH=81, DET_WIDTH=126, M_WIDTH=104;
  parameter int SCALE_WIDTH=145;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,cfd,ofd,rc,stall_in,stall_out,inject,singular;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic [33:0] cfg_lambda='0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,dut_error;
  logic signed [17:0] m_re,m_im;
  mmse3 #(.RESET_ACTIVE(RESET_ACTIVE),.GRAM_WIDTH(GRAM_WIDTH),.SUM_WIDTH(SUM_WIDTH),
          .ADJ_WIDTH(ADJ_WIDTH),.DET_WIDTH(DET_WIDTH),.M_WIDTH(M_WIDTH),.SCALE_WIDTH(SCALE_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_re(cfg_re),.cfg_im(cfg_im),
    .cfg_lambda(cfg_lambda),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),
    .error(dut_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse3 m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(36+34),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse3 cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_re,cfg_im,cfg_lambda}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse3 s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse3 m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
  int cfg_re_v[9],cfg_im_v[9];
  longint cfg_lambda_v;
  int rd_re,rd_im,rd_last;
  int in_total,in_re[],in_im[],in_last[];
  int out_total,out_checked=0;
  bit scoring=1;
  `include "mmse3_bounds_check.svh"
  wire signed [SUM_WIDTH:0] mmse_rounded [0:5];
  for(genvar row=0;row<3;row++) begin : g_observer
    assign mmse_rounded[2*row]=((SUM_WIDTH+1)'(dut.yr[row])+(SUM_WIDTH+1)'(8388608))>>>24;
    assign mmse_rounded[2*row+1]=((SUM_WIDTH+1)'(dut.yi[row])+(SUM_WIDTH+1)'(8388608))>>>24;
  end
  sat_event_check #(.FIELDS(6),.RAW_WIDTH(SUM_WIDTH+1),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
                     .NAME("mmse3"),.EXPECTED_FILE("mmse3_expected.txt")) saturation_check
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(dut.p_valid),
     .done(!singular&&out_total>0&&out_checked==out_total),.rounded(mmse_rounded));
  longint weight_re_v[9],weight_im_v[9];
  int mid_reset,out_reset,cfg_reset,warm_out=0,n0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
  always @(posedge clk) if(rst!=RESET_ACTIVE&&scoring&&!stall_in&&!stall_out&&configured&&s_valid)
    if(!s_ready) $fatal(1,"[THROUGHPUT] MMSE3 did not sustain consecutive input samples/frames");
  // Scoreboard: every accepted output must equal mmse_fixed.solve exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(rc!=3) $fatal(1,"[VECTOR] incomplete expected MMSE3 output");
      if(inject&&out_checked==0) re=re+1;
      if(m_re!==18'(re)||m_im!==18'(im)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d last %0d/%0d",out_checked,m_re,m_im,re,im,m_last,last);
        $fatal(1,"[NUMERIC] mmse3 output");
      end
      out_checked=out_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered while nothing is scored yet.
  always @(posedge clk) if(!scoring&&m_valid&&m_ready) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_cfg(input int re,input int im,input int last,input longint lam);
    @(negedge clk);
    cfg_valid=1;cfg_last=1'(last);cfg_re=18'(re);cfg_im=18'(im);cfg_lambda=34'(lam);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cfg_valid&&cfg_ready) return;
    end
    $fatal(1,"[THROUGHPUT] configuration entry never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);s_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    s_valid=1;s_re=18'(re);s_im=18'(im);s_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(s_valid&&s_ready) return;
    end
    $fatal(1,"[THROUGHPUT] observation never accepted (cycle %0d)",cycle);
  endtask
  // Waits for configured (weights computed) or error (singular normal matrix).
  task automatic wait_config;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(configured||dut_error) break;
    end
  endtask
  // The whole configuration: the nine entries of H, cfg_last and cfg_lambda on h22.
  task automatic configure;
    for(int j=0;j<9;j=j+1) drive_cfg(cfg_re_v[j],cfg_im_v[j],j==8,cfg_lambda_v);
    @(negedge clk);cfg_valid=0;
    wait_config;
    if(dut_error!==1'b0) $fatal(1,"[NUMERIC] error asserted on a non-singular H");
    if(configured!==1'b1) $fatal(1,"[TIMEOUT] DUT never configured");
    for(int j=0;j<9;j++) begin
      longint expected_re;
      expected_re=weight_re_v[j];
      if(j==0&&$test$plusargs("INJECT_WEIGHT_MISMATCH")) expected_re+=1;
      if(dut.wr[j]!==expected_re || dut.wi[j]!==weight_im_v[j])
        $fatal(1,"[WEIGHTS] MMSE3 coefficient %0d differs from integer model",j);
    end
  endtask
  function automatic void load_vectors;
    fd=$fopen({directory,"/in.txt"},"r");
    while($fscanf(fd,"%d %d %d",rd_re,rd_im,rd_last)==3) in_total=in_total+1;
    rc=$fseek(fd,0,0);
    in_re=new[in_total];in_im=new[in_total];in_last=new[in_total];
    for(int j=0;j<in_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",rd_re,rd_im,rd_last);
      in_re[j]=rd_re;in_im[j]=rd_im;in_last[j]=rd_last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/out.txt"},"r");
    while($fscanf(ofd,"%d %d %d",rd_re,rd_im,rd_last)==3) out_total=out_total+1;
    rc=$fseek(ofd,0,0);
  endfunction
  initial begin
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");singular=$test$plusargs("SINGULAR");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    cfd=$fopen({directory,"/cfg.txt"},"r");
    for(int j=0;j<9;j=j+1) rc=$fscanf(cfd,"%d %d",cfg_re_v[j],cfg_im_v[j]);
    rc=$fscanf(cfd,"%d",cfg_lambda_v);
    $fclose(cfd);
    if(!singular) begin
      load_vectors;
      cfd=$fopen({directory,"/weights.txt"},"r");
      if(!cfd) $fatal(1,"[VECTOR] missing weights");
      for(int j=0;j<9;j++) begin
        rc=$fscanf(cfd,"%d %d",weight_re_v[j],weight_im_v[j]);
        if(rc!=2) $fatal(1,"[VECTOR] incomplete weights");
      end
      $fclose(cfd);
    end
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    if($test$plusargs("BAD_CFG_LAST")||$test$plusargs("BAD_CFG_COUNT")||$test$plusargs("COEFFICIENT_OVERFLOW")) begin
      int bad_channel[9]='{131071,1,0,0,131071,1,1,0,0};
      if($test$plusargs("BAD_CFG_LAST")) drive_cfg(32768,0,1,0);
      else if($test$plusargs("BAD_CFG_COUNT"))
        for(int j=0;j<10;j++) drive_cfg(32768,0,j==9,0);
      else for(int j=0;j<9;j++) drive_cfg(bad_channel[j],0,j==8,0);
      @(negedge clk);cfg_valid=0;
      wait_config;
      if(dut_error!==1'b1||configured!==1'b0||m_valid!==1'b0||s_ready!==1'b0)
        $fatal(1,"[REJECTION] invalid MMSE3 configuration accepted");
      $display("PASS MMSE3 CONFIG REJECT");$finish;
    end
    if(singular) begin
      // H = [[1,1],[1,1]] (Q15 32768) and lambda 0: the normal matrix is singular.
      for(int j=0;j<9;j=j+1) drive_cfg(32768,0,j==8,0);
      @(negedge clk);cfg_valid=0;
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(dut_error) break;
      end
      if(dut_error!==1'b1) $fatal(1,"[TIMEOUT] singular H did not raise error (cycle %0d)",cycle);
      repeat(20) @(posedge clk);
      if(configured!==1'b0||m_valid!==1'b0||s_ready!==1'b0)
        $fatal(1,"[REJECTION] singular MMSE3 configured or emitted data");
      $display("PASS MMSE3 SINGULAR");
      $finish;
    end
    // Configuration: the nine entries of H, cfg_last and cfg_lambda on h22.
    if(!cfg_reset) configure;
    if($test$plusargs("BAD_DATA_LAST")||$test$plusargs("BAD_DATA_LAST_SECOND")) begin
      if($test$plusargs("BAD_DATA_LAST_SECOND")) drive_in(1,0,0);
      drive_in(1,0,1);
      @(negedge clk);s_valid=0;s_last=0;
      repeat(10) @(negedge clk);
      if(dut_error!==1'b1||configured!==1'b0||m_valid!==1'b0||s_ready!==1'b0
         ||dut.pending!=='0||dut.index!=='0)
        $fatal(1,"[REJECTION] incomplete MMSE3 observation accepted or reservation leaked");
      $display("PASS MMSE3 DATA REJECT");$finish;
    end
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C = 9 cfg transfers (the entries of H): drive the first four of them, cfg_last stays low
        for(int j=0;j<4;j=j+1) drive_cfg(cfg_re_v[j],cfg_im_v[j],0,0);
        if(configured) $fatal(1,"[CFG_RESET] already configured");
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=in_total;
      for(int j=0;j<in_total;j=j+1) if(in_last[j]) begin n0=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transaction (with its real last flag), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
        @(negedge clk);s_valid=0;s_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_in(in_re[j],in_im[j],0);
      end
      end
      @(negedge clk);cfg_valid=0;s_valid=0;s_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(m_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(dut_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the observation triples.
    for(int j=0;j<in_total;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
    @(negedge clk);s_valid=0;s_last=0;
    wait(out_checked==out_total);
    repeat(20) @(negedge clk);
    if(dut_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_mmse3_bounds();
    check_mmse3_widths();
    check_mmse3_config();
    check_scale_updates();
    $display("PASS MMSE3: %0d outputs, %0d cycles",out_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"MMSE testbench did not drain"); end
  `include "mmse3_width_check.svh"
  `include "mmse3_config_check.svh"
  `include "mmse3_scale_check.svh"
endmodule
