// Integer 2x2 MMSE / zero-forcing solver (rtl/common/mmse2.sv) against the integer model
// (tools/mmse_cases.py vectors). The bench drives the four Q15 entries of H in row-major order
// (one cfg transfer each, cfg_last and cfg_lambda on h11), waits for configured (and error == 0),
// then streams the observation pairs of in.txt (s_last on the last o1 of a transaction). The DUT
// answers with y0, y1 per pair scored against out.txt exactly (m_last on the last output) and the
// run must end with error == 0. +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready), +STALL_OUTPUT random m_ready
// (~2/3 high), +INJECT_MISMATCH corrupts the first expected output re (negative control,
// [NUMERIC]). +SINGULAR configures H = [[1,1],[1,1]] with lambda 0 instead and only requires the
// error flag to rise. +COEFFICIENT_OVERFLOW configures nonsingular raw
// H=[[131071,131070],[1,1]], lambda=0, and requires error, configured low and no
// accepted input or output after its inverse exceeds signed 48-bit Q24 storage.
// +MID_RESET drives half of the first transaction, resets the DUT in the middle
// of it and requires it to come back silent (no output valid, configured low, no error) before the
// configuration and the whole stream are driven again from the start (nothing is scored during that
// warm-up phase). +OUT_RESET is the same block, but the warm-up drives the WHOLE first transaction
// and the reset lands as soon as the DUT has delivered at least one accepted output (otherwise
// [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: the first C/2 = 2 entries of H (never the one with
// cfg_last, where the DUT starts computing the weights) are driven, the DUT resets at the next
// negedge, then the configuration and the whole observation stream run again from the start and only
// then are scored.
// GRAM/DET/M/SCALE/SUM_WIDTH select the mmse2 expression widths; +CHECK_MMSE2_WIDTHS enables the
// independent full-width intermediate monitor (mmse2_width_check.svh, +INJECT_MMSE2=<TAG>).
`timescale 1ns/1ps
module mmse_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int GRAM_WIDTH=38,DET_WIDTH=74,M_WIDTH=55,SCALE_WIDTH=78,SUM_WIDTH=68;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,cfd,ofd,rc,stall_in,stall_out,inject,singular,coefficient_overflow;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic [33:0] cfg_lambda='0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,dut_error;
  logic signed [17:0] m_re,m_im;
  mmse2 #(.RESET_ACTIVE(RESET_ACTIVE),.GRAM_WIDTH(GRAM_WIDTH),.DET_WIDTH(DET_WIDTH),.M_WIDTH(M_WIDTH),
          .SCALE_WIDTH(SCALE_WIDTH),.SUM_WIDTH(SUM_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_re(cfg_re),.cfg_im(cfg_im),
    .cfg_lambda(cfg_lambda),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),
    .error(dut_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(36+34),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_re,cfg_im,cfg_lambda}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
  int cfg_re_v[4],cfg_im_v[4];
  longint cfg_lambda_v;
  int rd_re,rd_im,rd_last;
  int in_total,in_re[],in_im[],in_last[];
  int out_total,out_checked=0;
  bit scoring=1;
  `include "mmse_bounds_check.svh"
  `include "mmse2_width_check.svh"
  wire signed [67:0] mmse_rounded [0:3];
  // |y| <= 2^66 + 2^23 for every SUM_WIDTH >= 68, so the 68-bit view is exact.
  assign mmse_rounded[0]=(68'(dut.y0r)+68'sd8388608)>>>24;
  assign mmse_rounded[1]=(68'(dut.y0i)+68'sd8388608)>>>24;
  assign mmse_rounded[2]=(68'(dut.y1r)+68'sd8388608)>>>24;
  assign mmse_rounded[3]=(68'(dut.y1i)+68'sd8388608)>>>24;
  sat_event_check #(.FIELDS(4),.RAW_WIDTH(68),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
                     .NAME("mmse"),.EXPECTED_FILE("mmse_expected.txt")) saturation_check
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(dut.p_valid),
     .done(!singular&&!coefficient_overflow&&out_total>0&&out_checked==out_total),.rounded(mmse_rounded));
  int mid_reset,out_reset,cfg_reset,warm_out=0,n0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
  // Scoreboard: every accepted output must equal mmse_fixed.solve exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(inject&&out_checked==0) re=re+1;
      if(m_re!==18'(re)||m_im!==18'(im)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d last %0d/%0d",out_checked,m_re,m_im,re,im,m_last,last);
        $fatal(1,"[NUMERIC] mmse2 output");
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
  // The whole configuration: the four entries of H, cfg_last and cfg_lambda on h11.
  task automatic configure;
    for(int j=0;j<4;j=j+1) drive_cfg(cfg_re_v[j],cfg_im_v[j],j==3,cfg_lambda_v);
    @(negedge clk);cfg_valid=0;
    wait_config;
    if(dut_error!==1'b0) $fatal(1,"[NUMERIC] error asserted on a non-singular H");
    if(configured!==1'b1) $fatal(1,"[TIMEOUT] DUT never configured");
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
    coefficient_overflow=$test$plusargs("COEFFICIENT_OVERFLOW");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    cfd=$fopen({directory,"/cfg.txt"},"r");
    for(int j=0;j<4;j=j+1) rc=$fscanf(cfd,"%d %d",cfg_re_v[j],cfg_im_v[j]);
    rc=$fscanf(cfd,"%d",cfg_lambda_v);
    $fclose(cfd);
    if(!singular&&!coefficient_overflow) load_vectors;
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    if(coefficient_overflow) begin
      drive_cfg(131071,0,0,0);drive_cfg(131070,0,0,0);
      drive_cfg(1,0,0,0);drive_cfg(1,0,1,0);
      @(negedge clk);cfg_valid=0;
      wait_config;
      if(dut.det!==76'sd1) $fatal(1,"[COEFFICIENT_OVERFLOW] expected positive determinant one");
      if(dut_error!==1'b1||configured!==1'b0)
        $fatal(1,"[COEFFICIENT_OVERFLOW] unrepresentable inverse was accepted");
      // Offer stable observations to verify that the rejected configuration blocks the input.
      @(negedge clk);s_valid=1;s_re=1;s_im=0;s_last=0;
      repeat(32) begin
        @(negedge clk);
        if(configured!==1'b0||dut_error!==1'b1||s_ready!==1'b0||m_valid!==1'b0)
          $fatal(1,"[COEFFICIENT_OVERFLOW] rejected configuration activated the datapath");
      end
      s_valid=0;
      check_mmse2_widths();
      $display("PASS MMSE COEFFICIENT_OVERFLOW");
      $finish;
    end
    if(singular) begin
      // H = [[1,1],[1,1]] (Q15 32768) and lambda 0: the normal matrix is singular.
      for(int j=0;j<4;j=j+1) drive_cfg(32768,0,j==3,0);
      @(negedge clk);cfg_valid=0;
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(dut_error) break;
      end
      if(dut_error!==1'b1) $fatal(1,"[TIMEOUT] singular H did not raise error (cycle %0d)",cycle);
      repeat(20) @(posedge clk);
      check_mmse2_widths();
      $display("PASS MMSE SINGULAR");
      $finish;
    end
    // Configuration: the four entries of H, cfg_last and cfg_lambda on h11.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C = 4 cfg transfers (the entries of H): drive the first C/2 of them, cfg_last stays low
        for(int j=0;j<2;j=j+1) drive_cfg(cfg_re_v[j],cfg_im_v[j],0,0);
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
    // Stream the observation pairs.
    for(int j=0;j<in_total;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
    @(negedge clk);s_valid=0;s_last=0;
    wait(out_checked==out_total);
    repeat(20) @(negedge clk);
    if(dut_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_mmse_bounds();
    check_mmse2_widths();
    $display("PASS MMSE: %0d outputs, %0d cycles",out_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"MMSE testbench did not drain"); end
endmodule
