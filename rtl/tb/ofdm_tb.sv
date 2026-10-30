// OFDM frame front end (rtl/modems/ofdm_awgn/ofdm_tx.sv, ofdm_rx.sv) against the integer
// model (tools/ofdm_cases.py vectors). Both DUTs run in one bench on independent streams:
// ofdm_tx scores every accepted sample against tx_out.txt, ofdm_rx against rx_out.txt;
// re, im and last must be bit-exact (tx_in.txt / rx_in.txt drive, *_out.txt score).
// +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers, +STALL_OUTPUT random m_ready
// (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts the first expected tx output re
// (negative control, [NUMERIC]). Ends when both scoreboards are complete and requires
// error == 0 on both DUTs. +MID_RESET drives half of the first frame of both streams,
// resets both DUTs in the middle of those frames and requires them to come back silent
// (no output valid, no error) before everything is driven again from the start (nothing
// is scored during that warm-up phase). +OUT_RESET is the same block, but the warm-up
// drives the WHOLE first transaction of both streams and the reset lands as soon as the
// DUTs have delivered at least one accepted output (otherwise [TIMEOUT] no output before
// OUT_RESET).
`timescale 1ns/1ps
module ofdm_tb;
  parameter integer LOG2N=5;
  parameter integer CP=8;
  parameter bit RESET_ACTIVE=1;
  parameter string TWIDDLE_FILE="rtl/common/mem/fft_twiddle_32.mem";
  localparam integer N=1<<LOG2N;
  localparam integer FRAME=N+CP;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,ofd,rc,stall_in,stall_out,inject;
  logic ti_valid=0,ti_last=0,ti_ready;
  logic signed [17:0] ti_re=0,ti_im=0;
  logic to_valid,to_last,to_ready=1,to_error;
  logic signed [17:0] to_re,to_im;
  logic ri_valid=0,ri_last=0,ri_ready;
  logic signed [17:0] ri_re=0,ri_im=0;
  logic ro_valid,ro_last,ro_ready=1,ro_error;
  logic signed [17:0] ro_re,ro_im;
  ofdm_tx #(.LOG2N(LOG2N),.CP(CP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut_tx
   (.clk(clk),.rst(rst),.s_valid(ti_valid),.s_last(ti_last),.s_re(ti_re),.s_im(ti_im),.s_ready(ti_ready),
    .m_valid(to_valid),.m_last(to_last),.m_re(to_re),.m_im(to_im),.m_ready(to_ready),.error(to_error));
  ofdm_rx #(.LOG2N(LOG2N),.CP(CP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut_rx
   (.clk(clk),.rst(rst),.s_valid(ri_valid),.s_last(ri_last),.s_re(ri_re),.s_im(ri_im),.s_ready(ri_ready),
    .m_valid(ro_valid),.m_last(ro_last),.m_re(ro_re),.m_im(ro_im),.m_ready(ro_ready),.error(ro_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_tx m")) check_to
   (.clk(clk),.rst(rst),.valid(to_valid),.ready(to_ready),.last(to_last),.data({to_re,to_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_rx m")) check_ro
   (.clk(clk),.rst(rst),.valid(ro_valid),.ready(ro_ready),.last(ro_last),.data({ro_re,ro_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_tx s")) check_ti
   (.clk(clk),.rst(rst),.valid(ti_valid),.ready(ti_ready),.last(ti_last),.data({ti_re,ti_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_rx s")) check_ri
   (.clk(clk),.rst(rst),.valid(ri_valid),.ready(ri_ready),.last(ri_last),.data({ri_re,ri_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_tx m")) cover_to
   (.clk(clk),.rst(rst),.valid(to_valid),.ready(to_ready),.last(to_last),.data({to_re,to_im}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ofdm_rx m")) cover_ro
   (.clk(clk),.rst(rst),.valid(ro_valid),.ready(ro_ready),.last(ro_last),.data({ro_re,ro_im}),.mode(0));
  int txi_re[],txi_im[],txi_last[],txi_total;
  int txo_total,tx_checked=0;
  int rxi_re[],rxi_im[],rxi_last[],rxi_total;
  int rxo_total,rx_checked=0;
  bit scoring=1;
  `include "ofdm_saturation_check.svh"
  `include "ofdm_bounds_check.svh"
  `define FFT_DUT dut_tx.fft
  generate if(1) begin : g_tx_fft
    localparam int FFT_LOG2N=LOG2N;
    localparam int FFT_SIZE=N;
    localparam int FFT_WIDTH=20;
    localparam string FFT_EXPECTED_FILE="ofdm_tx_fft_expected.txt";
    localparam string FFT_LABEL="ofdm_tx";
    `include "fft_embedded_observer.svh"
  end endgenerate
  `undef FFT_DUT
  `define FFT_DUT dut_rx.fft
  generate if(1) begin : g_rx_fft
    localparam int FFT_LOG2N=LOG2N;
    localparam int FFT_SIZE=N;
    localparam int FFT_WIDTH=20;
    localparam string FFT_EXPECTED_FILE="ofdm_rx_fft_expected.txt";
    localparam string FFT_LABEL="ofdm_rx";
    `include "fft_embedded_observer.svh"
  end endgenerate
  `undef FFT_DUT
  int mid_reset,out_reset,warm_out=0;
  integer tfi,rfo;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin to_ready<=(($urandom%3)!=0);ro_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal ofdm_fixed.transmit / receive exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&to_valid&&to_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(inject&&tx_checked==0) re=re+1;
      if(to_re!==18'(re)||to_im!==18'(im)||to_last!==1'(last)) begin
        $display("MISMATCH tx output %0d: %0d,%0d/%0d,%0d last %0d/%0d",tx_checked,to_re,to_im,re,im,to_last,last);
        $fatal(1,"[NUMERIC] ofdm_tx output");
      end
      tx_checked=tx_checked+1;
    end
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&ro_valid&&ro_ready) begin
      rc=$fscanf(rfo,"%d %d %d",re,im,last);
      if(ro_re!==18'(re)||ro_im!==18'(im)||ro_last!==1'(last)) begin
        $display("MISMATCH rx output %0d: %0d,%0d/%0d,%0d last %0d/%0d",rx_checked,ro_re,ro_im,re,im,ro_last,last);
        $fatal(1,"[NUMERIC] ofdm_rx output");
      end
      rx_checked=rx_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((to_valid&&to_ready)||(ro_valid&&ro_ready))) warm_out=warm_out+1;
  // Drivers: optional gap idle clocks, then hold the sample until s_ready on a posedge.
  // Inputs change only on a negedge (no race with the DUT's posedge sampling).
  task automatic drive_tx(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ti_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ti_valid=1;ti_re=18'(re);ti_im=18'(im);ti_last=1'(last);
    for(int guard=0;guard<8*N+4*FRAME+400;guard++) begin
      @(posedge clk);
      if(ti_valid&&ti_ready) return;
    end
    $fatal(1,"[THROUGHPUT] tx input sample never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_rx(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ri_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ri_valid=1;ri_re=18'(re);ri_im=18'(im);ri_last=1'(last);
    for(int guard=0;guard<8*N+4*FRAME+400;guard++) begin
      @(posedge clk);
      if(ri_valid&&ri_ready) return;
    end
    $fatal(1,"[THROUGHPUT] rx input sample never accepted (cycle %0d)",cycle);
  endtask
  initial begin
    int re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    fd=$fopen({directory,"/tx_in.txt"},"r");
    rc=$fscanf(fd,"%d",txi_total);
    txi_re=new[txi_total];txi_im=new[txi_total];txi_last=new[txi_total];
    for(int j=0;j<txi_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      txi_re[j]=re;txi_im[j]=im;txi_last[j]=last;
    end
    $fclose(fd);
    fd=$fopen({directory,"/rx_in.txt"},"r");
    rc=$fscanf(fd,"%d",rxi_total);
    rxi_re=new[rxi_total];rxi_im=new[rxi_total];rxi_last=new[rxi_total];
    for(int j=0;j<rxi_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      rxi_re[j]=re;rxi_im[j]=im;rxi_last[j]=last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/tx_out.txt"},"r");rc=$fscanf(ofd,"%d",txo_total);
    rfo=$fopen({directory,"/rx_out.txt"},"r");rc=$fscanf(rfo,"%d",rxo_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    if(mid_reset||out_reset) begin
      scoring=0;
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=txi_total;
      for(int j=0;j<txi_total;j=j+1) if(txi_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=rxi_total;
      for(int j=0;j<rxi_total;j=j+1) if(rxi_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_tx(txi_re[j],txi_im[j],txi_last[j]);
        @(negedge clk);ti_valid=0;ti_last=0;
        for(int j=0;j<n1;j=j+1) drive_rx(rxi_re[j],rxi_im[j],rxi_last[j]);
        @(negedge clk);ri_valid=0;ri_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_tx(txi_re[j],txi_im[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_rx(rxi_re[j],rxi_im[j],0);
      end
      @(negedge clk);ti_valid=0;ti_last=0;ri_valid=0;ri_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(to_valid!==1'b0||ro_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(to_error!==1'b0||ro_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
    end
    fork
      begin
        for(int j=0;j<txi_total;j=j+1) drive_tx(txi_re[j],txi_im[j],txi_last[j]);
        @(negedge clk);ti_valid=0;ti_last=0;
      end
      begin
        for(int j=0;j<rxi_total;j=j+1) drive_rx(rxi_re[j],rxi_im[j],rxi_last[j]);
        @(negedge clk);ri_valid=0;ri_last=0;
      end
    join
    wait(tx_checked==txo_total&&rx_checked==rxo_total);
    repeat(20) @(negedge clk);
    if(to_error!==1'b0||ro_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every frame was complete (tx %0d, rx %0d)",to_error,ro_error);
    check_ofdm_bounds();
    g_tx_fft.check_embedded_fft_saturation();
    g_rx_fft.check_embedded_fft_saturation();
    $display("PASS OFDM: %0d tx samples, %0d rx symbols, %0d cycles",tx_checked,rx_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"OFDM testbench did not drain"); end
endmodule
