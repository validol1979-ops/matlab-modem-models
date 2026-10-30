// Integer polyphase analysis bank (rtl/common/pfb_analysis.sv) against the integer model
// (tools/pfb_cases.py vectors). The bench drives the T taps (Q17) one per cfg transfer
// (cfg_last on the last tap, cfg_decimation D sampled with cfg_last) while cfg_ready,
// waits for configured (and error == 0), then streams one transaction per signal from
// in.txt (s_last on its last sample). The DUT answers with ceil(L/D) output times of M
// bins; every accepted bin is scored against out.txt (re, im and last bit-exact, m_last
// on the very last bin of the transaction). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready),
// +STALL_OUTPUT random m_ready (~2/3 high), +INJECT_MISMATCH corrupts the first expected
// output re (negative control, [NUMERIC]). Ends when the scoreboard is complete and
// requires error == 0. +MID_RESET drives half of the first transaction, resets the DUT in
// the middle of it and requires it to come back silent (no output valid, configured low,
// no error) before the configuration and the whole stream are driven again from the start
// (nothing is scored during that warm-up phase). +OUT_RESET is the same block, but the
// warm-up drives the WHOLE first transaction and the reset lands as soon as the DUT has
// delivered at least one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: the first half of the cfg transfers (never the
// one with cfg_last) is driven, the DUT resets at the next negedge, then everything - the
// configuration included - runs again from the start and only then is scored.
`timescale 1ns/1ps
module pfb_tb;
  parameter integer LOG2M=2;
  parameter integer LOG2LANES=2;
  parameter integer LOG2TMAX=6;
  parameter integer ACC_WIDTH=36+(LOG2TMAX>LOG2M?LOG2TMAX-LOG2M:0);
  parameter bit RESET_ACTIVE=1;
  parameter string TWIDDLE_FILE="rtl/common/mem/fft_twiddle_4.mem";
  localparam integer M=1<<LOG2M;
  localparam integer DECW=LOG2M+1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,cfd,ofd,rc,stall_in,stall_out,inject;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_tap=0;
  logic [DECW-1:0] cfg_decimation=0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,m_error;
  logic signed [23:0] m_re,m_im;
  pfb_analysis #(.LOG2M(LOG2M),.LOG2LANES(LOG2LANES),.LOG2TMAX(LOG2TMAX),
                 .RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.ACC_WIDTH(ACC_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_tap(cfg_tap),
    .cfg_decimation(cfg_decimation),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(m_error));
  axis_check #(.WIDTH(48),.RESET_ACTIVE(RESET_ACTIVE),.NAME("pfb m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(18+DECW),.RESET_ACTIVE(RESET_ACTIVE),.NAME("pfb cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_tap,cfg_decimation}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("pfb s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  stream_cover #(.FIELDS(2),.FW(24),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("pfb m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
  int tap_total,decimation;
  int taps[];
  int in_re[],in_im[],in_last[],in_total;
  int out_total,out_checked=0;
  bit scoring=1;
  `include "pfb_saturation_check.svh"
  `include "pfb_bounds_check.svh"
  `include "pfb_width_check.svh"
  `define FFT_DUT dut.fft
  generate if(1) begin : g_embedded_fft
    localparam int FFT_LOG2N=LOG2M;
    localparam int FFT_SIZE=M;
    localparam int FFT_WIDTH=24;
    localparam string FFT_EXPECTED_FILE="pfb_fft_expected.txt";
    localparam string FFT_LABEL="pfb";
    `include "fft_embedded_observer.svh"
  end endgenerate
  `undef FFT_DUT
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
  // Scoreboard: every accepted bin must equal pfb_fixed.analyze exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(inject&&out_checked==0) re=re+1;
      if(m_re!==24'(re)||m_im!==24'(im)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d last %0d/%0d",out_checked,m_re,m_im,re,im,m_last,last);
        $fatal(1,"[NUMERIC] pfb_analysis output");
      end
      out_checked=out_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered while nothing is scored yet.
  always @(posedge clk) if(!scoring&&m_valid&&m_ready) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_cfg(input int tap,input int last);
    @(negedge clk);
    cfg_valid=1;cfg_tap=18'(tap);cfg_last=1'(last);cfg_decimation=DECW'(decimation);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cfg_valid&&cfg_ready) return;
    end
    $fatal(1,"[THROUGHPUT] configuration tap never accepted (cycle %0d)",cycle);
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
    $fatal(1,"[THROUGHPUT] input sample never accepted (cycle %0d)",cycle);
  endtask
  // The whole configuration: the taps one per transfer, the decimation sampled with cfg_last.
  task automatic configure;
    for(int j=0;j<tap_total;j=j+1) drive_cfg(taps[j],j==tap_total-1);
    @(negedge clk);cfg_valid=0;cfg_last=0;
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
    rc=$fscanf(cfd,"%d",tap_total);
    taps=new[tap_total];
    for(int j=0;j<tap_total;j=j+1) rc=$fscanf(cfd,"%d",taps[j]);
    rc=$fscanf(cfd,"%d",decimation);
    $fclose(cfd);
    fd=$fopen({directory,"/in.txt"},"r");
    rc=$fscanf(fd,"%d",in_total);
    in_re=new[in_total];in_im=new[in_total];in_last=new[in_total];
    for(int j=0;j<in_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      in_re[j]=re;in_im[j]=im;in_last[j]=last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/out.txt"},"r");rc=$fscanf(ofd,"%d",out_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: the taps one per transfer, the decimation sampled with cfg_last.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C = tap_total cfg transfers; interrupt after the first C/2 (never the one with cfg_last)
        if(tap_total>=2) begin
          for(int j=0;j<tap_total/2;j=j+1) drive_cfg(taps[j],0);
          if(configured) $fatal(1,"[CFG_RESET] already configured");
        end else begin
          for(int j=0;j<tap_total;j=j+1) drive_cfg(taps[j],j==tap_total-1);
        end
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
      @(negedge clk);cfg_valid=0;cfg_last=0;s_valid=0;s_last=0;rst=RESET_ACTIVE;
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
    repeat(20) @(negedge clk);
    if(m_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_pfb_bounds();
    if($test$plusargs("CHECK_ACCUMULATOR"))check_pfb_accumulators();
    g_embedded_fft.check_embedded_fft_saturation();
    $display("PASS PFB: %0d bins, %0d cycles",out_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"PFB testbench did not drain"); end
endmodule
