// Adaptive RLS filter (rtl/common/rls_filter.sv) against the integer model
// (tools/rls_cases.py vectors). The bench drives the single configuration transfer (tap count
// N, P0, LAM, INVL) while cfg_ready, waits for configured (and error == 0), then streams one
// transaction per signal from in.txt (x and the desired d of the same sample, s_last on its last
// sample). The DUT answers with one (pred, e) per sample scored against out.txt (m_last on the
// last sample of the transaction) and, after each transaction, the N final weights scored
// against w.txt (w_last on the last weight). Every transaction restarts P = P0*I, w = 0 and the
// history at zero, which the vectors model independently. +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready),
// +STALL_OUTPUT random m_ready/w_ready (~2/3 high), +INJECT_MISMATCH corrupts the first expected
// prediction re (negative control, [NUMERIC]). Ends when both scoreboards are complete and
// requires error == 0. +MID_RESET drives half of the first transaction, resets the DUT in the
// middle of it and requires it to come back silent (no output valid, no weight valid, configured
// low, no error) before the configuration and the whole stream are driven again from the start
// (nothing is scored during that warm-up phase). +OUT_RESET is the same block, but the warm-up
// drives the WHOLE first transaction and the reset lands as soon as the DUT has delivered at least
// one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: RLS has C == 1 cfg transfer, so the bench drives
// that single transfer and resets on the very next negedge while the DUT is still configuring itself
// (no configured check for C == 1), then the configuration and the whole stream run again from the
// start and only then are scored.
`timescale 1ns/1ps
module rls_tb;
  parameter integer LOG2N=2;
  typedef logic [LOG2N:0] tap_count_t;
  parameter bit RESET_ACTIVE=1;
  parameter int PRED_WIDTH=53+LOG2N,DOT_WIDTH=63+LOG2N,Q_WIDTH=67+LOG2N;
  parameter int GAIN_WIDTH=71,UPDATE_WIDTH=59,WEIGHT_WIDTH=44,PT_WIDTH=89,COV_WIDTH=79;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,cfd,ofd,wfd,rc,stall_in,stall_out,inject;
  logic cfg_valid=0,cfg_ready,configured;
  tap_count_t cfg_taps='0;
  logic [43:0] cfg_p0='0;
  logic [29:0] cfg_lambda='0;
  logic [31:0] cfg_invl='0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0,s_dre=0,s_dim=0;
  logic m_valid,m_last,m_ready=1,dut_error;
  logic signed [17:0] m_pre,m_pim,m_ere,m_eim;
  logic w_valid,w_last,w_ready=1;
  logic signed [17:0] w_re,w_im;
  rls_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.PRED_WIDTH(PRED_WIDTH),.DOT_WIDTH(DOT_WIDTH),.Q_WIDTH(Q_WIDTH),
      .GAIN_WIDTH(GAIN_WIDTH),.UPDATE_WIDTH(UPDATE_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH),.PT_WIDTH(PT_WIDTH),.COV_WIDTH(COV_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_taps(cfg_taps),.cfg_p0(cfg_p0),.cfg_lambda(cfg_lambda),
    .cfg_invl(cfg_invl),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_dre(s_dre),.s_dim(s_dim),
    .s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_pre(m_pre),.m_pim(m_pim),.m_ere(m_ere),.m_eim(m_eim),
    .m_ready(m_ready),
    .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(w_ready),
    .error(dut_error));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_pre,m_pim,m_ere,m_eim}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls w")) check_w
   (.clk(clk),.rst(rst),.valid(w_valid),.ready(w_ready),.last(w_last),.data({w_re,w_im}));
  axis_check #(.WIDTH((LOG2N+1)+44+30+32),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data({cfg_taps,cfg_p0,cfg_lambda,cfg_invl}));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im,s_dre,s_dim}));
  stream_cover #(.FIELDS(4),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_pre,m_pim,m_ere,m_eim}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rls w")) cover_w
   (.clk(clk),.rst(rst),.valid(w_valid),.ready(w_ready),.last(w_last),.data({w_re,w_im}),.mode(0));
  int cfg_taps_v;
  longint cfg_p0_v,cfg_lambda_v,cfg_invl_v;
  int in_total;
  int in_xre[],in_xim[],in_dre[],in_dim[],in_last[];
  int out_total,out_checked=0,w_total,w_checked=0;
  bit scoring=1;
  `include "rls_bounds_check.svh"
  // Direct observation of the DUT's own clamp inputs against <group>_group_expected.txt.
  `include "rls_saturation_check.svh"
  `include "rls_dot_check.svh"
  `include "rls_update_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin
    m_ready<=(($urandom%3)!=0);
    w_ready<=(($urandom%3)!=0);
  end
  // Scoreboard m_*: every accepted prediction/error must equal rls_fixed.adapt exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int pre,pim,ere,eim,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d %d %d",pre,pim,ere,eim,last);
      if(inject&&out_checked==0) pre=pre+1;
      if(m_pre!==18'(pre)||m_pim!==18'(pim)||m_ere!==18'(ere)||m_eim!==18'(eim)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d err %0d,%0d/%0d,%0d last %0d/%0d",
          out_checked,m_pre,m_pim,pre,pim,m_ere,m_eim,ere,eim,m_last,last);
        $fatal(1,"[NUMERIC] rls_filter output");
      end
      out_checked=out_checked+1;
    end
  end
  // Scoreboard w_*: every accepted weight must equal rls_fixed.adapt exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&w_valid&&w_ready) begin
      rc=$fscanf(wfd,"%d %d %d",re,im,last);
      if(w_re!==18'(re)||w_im!==18'(im)||w_last!==1'(last)) begin
        $display("MISMATCH weight %0d: %0d,%0d/%0d,%0d last %0d/%0d",w_checked,w_re,w_im,re,im,w_last,last);
        $fatal(1,"[NUMERIC] rls_filter weight");
      end
      w_checked=w_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered on any output stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((m_valid&&m_ready)||(w_valid&&w_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_cfg(input int taps,input longint p0,input longint lambda,input longint invl);
    @(negedge clk);
    cfg_valid=1;cfg_taps=tap_count_t'(taps);cfg_p0=44'(p0);cfg_lambda=30'(lambda);cfg_invl=32'(invl);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cfg_valid&&cfg_ready) return;
    end
    $fatal(1,"[THROUGHPUT] configuration never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_in(input int xre,input int xim,input int dre,input int dim,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);s_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    s_valid=1;s_re=18'(xre);s_im=18'(xim);s_dre=18'(dre);s_dim=18'(dim);s_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(s_valid&&s_ready) return;
    end
    $fatal(1,"[THROUGHPUT] input sample never accepted (cycle %0d)",cycle);
  endtask
  // The whole configuration: the single transfer while cfg_ready.
  task automatic configure;
    drive_cfg(cfg_taps_v,cfg_p0_v,cfg_lambda_v,cfg_invl_v);
    @(negedge clk);cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(configured) break;
    end
    if(configured!==1'b1) $fatal(1,"[TIMEOUT] DUT never configured");
    if(dut_error!==1'b0) $fatal(1,"[NUMERIC] error asserted after configuration");
  endtask
  initial begin
    int xre,xim,dre,dim,last,n0;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    cfd=$fopen({directory,"/cfg.txt"},"r");
    rc=$fscanf(cfd,"%d %d %d %d",cfg_taps_v,cfg_p0_v,cfg_lambda_v,cfg_invl_v);
    $fclose(cfd);
    fd=$fopen({directory,"/in.txt"},"r");
    rc=$fscanf(fd,"%d",in_total);
    in_xre=new[in_total];in_xim=new[in_total];in_dre=new[in_total];in_dim=new[in_total];
    in_last=new[in_total];
    for(int j=0;j<in_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d %d %d",xre,xim,dre,dim,last);
      in_xre[j]=xre;in_xim[j]=xim;in_dre[j]=dre;in_dim[j]=dim;in_last[j]=last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/out.txt"},"r");rc=$fscanf(ofd,"%d",out_total);
    wfd=$fopen({directory,"/w.txt"},"r");rc=$fscanf(wfd,"%d",w_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: the single transfer while cfg_ready.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C == 1: the single cfg transfer in full, the shared reset lands on the very next negedge
        drive_cfg(cfg_taps_v,cfg_p0_v,cfg_lambda_v,cfg_invl_v);
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=in_total;
      for(int j=0;j<in_total;j=j+1) if(in_last[j]) begin n0=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transaction (with its real last flag), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_in(in_xre[j],in_xim[j],in_dre[j],in_dim[j],in_last[j]);
        @(negedge clk);s_valid=0;s_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1)
          drive_in(in_xre[j],in_xim[j],in_dre[j],in_dim[j],0);
      end
      end
      @(negedge clk);cfg_valid=0;s_valid=0;s_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(m_valid!==1'b0||w_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(dut_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions.
    for(int j=0;j<in_total;j=j+1) drive_in(in_xre[j],in_xim[j],in_dre[j],in_dim[j],in_last[j]);
    @(negedge clk);s_valid=0;s_last=0;
    wait(out_checked==out_total&&w_checked==w_total);
    repeat(20) @(negedge clk);
    if(dut_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_rls_bounds();
    if($test$plusargs("CHECK_DOT"))check_rls_dot();
    if($test$plusargs("CHECK_UPDATES"))check_rls_updates();
    $display("PASS RLS: %0d outputs, %0d weights, %0d cycles",out_checked,w_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"RLS testbench did not drain"); end
endmodule
