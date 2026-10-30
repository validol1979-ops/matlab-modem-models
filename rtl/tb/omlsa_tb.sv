// Integer OM-LSA speech enhancement (rtl/common/omlsa.sv) against the integer model
// (tools/omlsa_cases.py vectors). The bench performs ONE configuration transfer while
// cfg_ready (cfg_nnoise in 1..16, cfg_alpha = round(alpha 2^16) from cfg.txt), waits for
// configured (and error == 0), then streams one transaction per signal from in.txt
// (s_last on its last sample). Every transaction is a signal of L >= N + 1 samples with at
// least cfg_nnoise frames and the DUT answers with exactly L outputs; every accepted output
// is scored against out.txt (re, im and last bit-exact, m_last on the very last output of
// the transaction). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready), +STALL_OUTPUT random m_ready
// (~2/3 high), +INJECT_MISMATCH corrupts the first expected output re (negative control,
// [NUMERIC]). Ends when the scoreboard is complete and requires error == 0. +MID_RESET drives half
// of the first transaction, resets the DUT in the middle of it and requires it to come back silent
// (no output valid, configured low, no error) before the configuration and the whole stream are
// driven again from the start (nothing is scored during that warm-up phase). +OUT_RESET is the
// same block, but the warm-up drives the WHOLE first transaction and the reset lands as soon as
// the DUT has delivered at least one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: OM-LSA has C == 1 cfg transfer, so the bench drives
// that single transfer and resets on the very next negedge while the DUT is still computing, then the
// configuration and the whole stream run again from the start and only then are scored.
// +CHECK_GAIN_WIDTHS adds the 128-bit operand-level reference of omlsa_gain_check.svh
// (+INJECT_GAIN_<TAG> corrupts one of its observations: a negative control).
`timescale 1ns/1ps
module omlsa_tb;
  parameter integer LOG2N=5;
  parameter integer LOG2HOP=3;
  parameter bit RESET_ACTIVE=1;
  parameter string MEM_DIR="rtl/common/mem/";
  parameter integer RECIP_WIDTH=18,GAMMA_WIDTH=72,XI_WIDTH=47,V_WIDTH=48,G1_WIDTH=37,T_WIDTH=48,A_WIDTH=37,OUT_WIDTH=41,GG_WIDTH=34,PREV_WIDTH=49;
  localparam integer N=1<<LOG2N;
  localparam integer HOP=1<<LOG2HOP;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,cfd,ofd,rc,stall_in,stall_out,inject;
  logic cfg_valid=0,cfg_ready,configured;
  logic [4:0] cfg_nnoise=0;
  logic [16:0] cfg_alpha=0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,m_error;
  logic signed [17:0] m_re,m_im;
  omlsa #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),.MEM_DIR(MEM_DIR),
    .RECIP_WIDTH(RECIP_WIDTH),.GAMMA_WIDTH(GAMMA_WIDTH),.XI_WIDTH(XI_WIDTH),.V_WIDTH(V_WIDTH),.G1_WIDTH(G1_WIDTH),.T_WIDTH(T_WIDTH),.A_WIDTH(A_WIDTH),.OUT_WIDTH(OUT_WIDTH),.GG_WIDTH(GG_WIDTH),.PREV_WIDTH(PREV_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_nnoise(cfg_nnoise),.cfg_alpha(cfg_alpha),
    .cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(m_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("omlsa m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(5+17),.RESET_ACTIVE(RESET_ACTIVE),.NAME("omlsa cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data({cfg_nnoise,cfg_alpha}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("omlsa s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("omlsa m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
  int nnoise_value,alpha_value,seen=0,checked_frames;
  int in_re[],in_im[],in_last[],in_total;
  int out_total,out_checked=0;
  bit scoring=1;
  `include "omlsa_saturation_check.svh"
  `include "omlsa_gain_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
  // The DUT must never complain: the vectors are always legal.
  always @(posedge clk) if(rst!=RESET_ACTIVE && m_error===1'b1)
    $fatal(1,"[NUMERIC] error asserted (cycle %0d)",cycle);
  // Scoreboard: every accepted output must equal omlsa_fixed.enhance exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(inject&&out_checked==0) re=re^1;
      if(m_re!==18'(re)||m_im!==18'(im)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d last %0d/%0d",out_checked,m_re,m_im,re,im,m_last,last);
        $fatal(1,"[NUMERIC] omlsa output");
      end
      out_checked=out_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered while nothing is scored yet.
  always @(posedge clk) if(!scoring&&m_valid&&m_ready) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_cfg();
    @(negedge clk);
    cfg_valid=1;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cfg_valid&&cfg_ready) return;
    end
    $fatal(1,"[THROUGHPUT] configuration never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);s_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    s_valid=1;s_re=18'(re);s_im=18'(im);s_last=1'(last);
    for(int guard=0;guard<1048576;guard++) begin
      @(posedge clk);
      if(s_valid&&s_ready) return;
    end
    $fatal(1,"[THROUGHPUT] input sample never accepted (cycle %0d)",cycle);
  endtask
  // The whole configuration: one transfer, then wait until the DUT is configured.
  task automatic configure;
    drive_cfg();
    @(negedge clk);cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(configured) break;
    end
    if(configured!==1'b1) $fatal(1,"[TIMEOUT] DUT never configured");
    if(m_error!==1'b0) $fatal(1,"[NUMERIC] error asserted after configuration");
  endtask
  initial begin
    int re,im,last,n0;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    cfd=$fopen({directory,"/cfg.txt"},"r");
    if(cfd==0) $fatal(1,"[TESTBENCH] cannot open cfg.txt");
    rc=$fscanf(cfd,"%d %d",nnoise_value,alpha_value);
    if(rc!=2||nnoise_value<1||nnoise_value>16||alpha_value<1||alpha_value>(1<<17)-1)
      $fatal(1,"[TESTBENCH] bad cfg.txt");
    cfg_nnoise=5'(nnoise_value);cfg_alpha=17'(alpha_value);
    $fclose(cfd);
    fd=$fopen({directory,"/in.txt"},"r");
    if(fd==0) $fatal(1,"[TESTBENCH] cannot open in.txt");
    rc=$fscanf(fd,"%d",in_total);
    if(rc!=1||in_total<1) $fatal(1,"[TESTBENCH] bad in.txt");
    in_re=new[in_total];in_im=new[in_total];in_last=new[in_total];
    for(int j=0;j<in_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      in_re[j]=re;in_im[j]=im;in_last[j]=last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/out.txt"},"r");
    if(ofd==0) $fatal(1,"[TESTBENCH] cannot open out.txt");
    rc=$fscanf(ofd,"%d",out_total);
    if(rc!=1||out_total!=in_total) $fatal(1,"[TESTBENCH] out.txt must hold one output per input");
    // Every transaction must be a legal OM-LSA signal: L >= N+1 and at least nnoise frames.
    for(int j=0;j<in_total;j=j+1) begin
      seen=seen+1;
      if(in_last[j]) begin
        checked_frames=1+(seen+N)/HOP;
        if(seen<N+1) $fatal(1,"[TESTBENCH] transaction of %0d samples is shorter than N+1",seen);
        if(checked_frames<nnoise_value)
          $fatal(1,"[TESTBENCH] transaction of %0d samples gives %0d frames < nnoise %0d",seen,checked_frames,nnoise_value);
        seen=0;
      end
    end
    if(seen!=0) $fatal(1,"[TESTBENCH] in.txt does not end with s_last");
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: one transfer, then wait until the DUT is configured.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C == 1: the only cfg transfer is driven in full, the shared reset below lands on the very
        // next negedge, while the DUT is still computing (no configured check for C == 1)
        drive_cfg();
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
      if(m_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions.
    for(int j=0;j<in_total;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
    @(negedge clk);s_valid=0;s_last=0;
    wait(out_checked==out_total);
    // The discarded reflection tail still exercises gain/ISTFT clamps and RAM accesses.
    wait(dut.len_count==0 && dut.index==0);
    repeat(20) @(negedge clk);
    if(m_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_omlsa_bounds();
    check_omlsa_gain_widths();
    $display("PASS OMLSA: %0d outputs, %0d cycles",out_checked,cycle);
    $finish;
  end
  initial begin #50000000;$fatal(1,"OM-LSA testbench did not drain"); end
endmodule
