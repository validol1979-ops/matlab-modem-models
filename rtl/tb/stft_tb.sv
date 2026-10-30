// STFT analysis / synthesis front end (rtl/common/stft_analysis.sv, stft_synthesis.sv)
// against the integer model (tools/stft_cases.py vectors). Both DUTs run in one bench on
// independent streams: stft_analysis scores every accepted spectrum bin against
// an_out.txt, stft_synthesis every accepted sample against sy_out.txt; re, im and last
// must be bit-exact (an_in.txt / sy_in.txt drive, *_out.txt score). One analysis
// transaction is one signal (s_last on its last sample) producing F frames of N bins;
// the synthesis transaction is those F frames (s_last on the very last bin) producing
// (F-1)*HOP+N samples. +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers,
// +STALL_OUTPUT random m_ready (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts the
// first expected analysis output re (negative control, [NUMERIC]). Ends when both
// scoreboards are complete and requires error == 0 on both DUTs. +MID_RESET drives half
// of the first transaction of both streams, resets both DUTs in the middle of them and
// requires them to come back silent (no output valid, no error) before everything is
// driven again from the start (nothing is scored during that warm-up phase). +OUT_RESET
// is the same block, but the warm-up drives the WHOLE first transaction of both streams
// and the reset lands as soon as the DUTs have delivered at least one accepted output
// (otherwise [TIMEOUT] no output before OUT_RESET).
`timescale 1ns/1ps
module stft_tb;
  parameter integer LOG2N=6;
  parameter integer LOG2HOP=4;
  parameter bit RESET_ACTIVE=1;
  parameter string TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem";
  parameter string WINDOW_FILE="rtl/common/mem/stft_window_64.mem";
  parameter string RECIP_FILE="rtl/common/mem/stft_recip_64_16.mem";
  parameter string SYNTH_WINDOW_FILE="";
  parameter integer ACC_WIDTH=41+LOG2N-LOG2HOP;
  parameter integer PRODUCT_WIDTH=41;
  localparam integer N=1<<LOG2N;
  localparam integer HOP=1<<LOG2HOP;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer fd,afd,sfd,rc,stall_in,stall_out,inject;
  logic ai_valid=0,ai_last=0,ai_ready;
  logic signed [17:0] ai_re=0,ai_im=0;
  logic ao_valid,ao_last,ao_ready=1,ao_error;
  logic signed [23:0] ao_re,ao_im;
  logic si_valid=0,si_last=0,si_ready;
  logic signed [23:0] si_re=0,si_im=0;
  logic so_valid,so_last,so_ready=1,so_error;
  logic signed [17:0] so_re,so_im;
  stft_analysis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),
                 .TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE)) dut_analysis
   (.clk(clk),.rst(rst),.s_valid(ai_valid),.s_last(ai_last),.s_re(ai_re),.s_im(ai_im),.s_ready(ai_ready),
    .m_valid(ao_valid),.m_last(ao_last),.m_re(ao_re),.m_im(ao_im),.m_ready(ao_ready),.error(ao_error));
  stft_synthesis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),
                   .TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(SYNTH_WINDOW_FILE==""?WINDOW_FILE:SYNTH_WINDOW_FILE),.RECIP_FILE(RECIP_FILE),
                   .ACC_WIDTH(ACC_WIDTH),.PRODUCT_WIDTH(PRODUCT_WIDTH)) dut_synthesis
   (.clk(clk),.rst(rst),.s_valid(si_valid),.s_last(si_last),.s_re(si_re),.s_im(si_im),.s_ready(si_ready),
    .m_valid(so_valid),.m_last(so_last),.m_re(so_re),.m_im(so_im),.m_ready(so_ready),.error(so_error));
  axis_check #(.WIDTH(48),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_analysis m")) check_ao
   (.clk(clk),.rst(rst),.valid(ao_valid),.ready(ao_ready),.last(ao_last),.data({ao_re,ao_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_synthesis m")) check_so
   (.clk(clk),.rst(rst),.valid(so_valid),.ready(so_ready),.last(so_last),.data({so_re,so_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_analysis s")) check_ai
   (.clk(clk),.rst(rst),.valid(ai_valid),.ready(ai_ready),.last(ai_last),.data({ai_re,ai_im}));
  axis_check #(.WIDTH(48),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_synthesis s")) check_si
   (.clk(clk),.rst(rst),.valid(si_valid),.ready(si_ready),.last(si_last),.data({si_re,si_im}));
  stream_cover #(.FIELDS(2),.FW(24),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_analysis m")) cover_ao
   (.clk(clk),.rst(rst),.valid(ao_valid),.ready(ao_ready),.last(ao_last),.data({ao_re,ao_im}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("stft_synthesis m")) cover_so
   (.clk(clk),.rst(rst),.valid(so_valid),.ready(so_ready),.last(so_last),.data({so_re,so_im}),.mode(0));
  int aii_re[],aii_im[],aii_last[],aii_total;
  int ao_total,ao_checked=0;
  int sii_re[],sii_im[],sii_last[],sii_total;
  int so_total,so_checked=0;
  bit scoring=1;
  `include "stft_saturation_check.svh"
  `include "istft_width_check.svh"
  int mid_reset,out_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin ao_ready<=(($urandom%3)!=0);so_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal stft_fixed.analyze / synthesize exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&ao_valid&&ao_ready) begin
      rc=$fscanf(afd,"%d %d %d",re,im,last);
      if(inject&&ao_checked==0) re=re+1;
      if(ao_re!==24'(re)||ao_im!==24'(im)||ao_last!==1'(last)) begin
        $display("MISMATCH analysis output %0d: %0d,%0d/%0d,%0d last %0d/%0d",ao_checked,ao_re,ao_im,re,im,ao_last,last);
        $fatal(1,"[NUMERIC] stft_analysis output");
      end
      ao_checked=ao_checked+1;
    end
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&so_valid&&so_ready) begin
      rc=$fscanf(sfd,"%d %d %d",re,im,last);
      if(so_re!==18'(re)||so_im!==18'(im)||so_last!==1'(last)) begin
        $display("MISMATCH synthesis output %0d: %0d,%0d/%0d,%0d last %0d/%0d",so_checked,so_re,so_im,re,im,so_last,last);
        $fatal(1,"[NUMERIC] stft_synthesis output");
      end
      so_checked=so_checked+1;
    end
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((ao_valid&&ao_ready)||(so_valid&&so_ready))) warm_out=warm_out+1;
  // Drivers: optional gap idle clocks, then hold the value until s_ready on a posedge.
  // Inputs change only on a negedge (no race with the DUT's posedge sampling).
  task automatic drive_an(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ai_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ai_valid=1;ai_re=18'(re);ai_im=18'(im);ai_last=1'(last);
    for(int guard=0;guard<64*N+8*HOP+4096;guard++) begin
      @(posedge clk);
      if(ai_valid&&ai_ready) return;
    end
    $fatal(1,"[THROUGHPUT] analysis input sample never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_sy(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);si_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    si_valid=1;si_re=24'(re);si_im=24'(im);si_last=1'(last);
    for(int guard=0;guard<64*N+8*HOP+4096;guard++) begin
      @(posedge clk);
      if(si_valid&&si_ready) return;
    end
    $fatal(1,"[THROUGHPUT] synthesis input bin never accepted (cycle %0d)",cycle);
  endtask
  initial begin
    int re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    fd=$fopen({directory,"/an_in.txt"},"r");
    rc=$fscanf(fd,"%d",aii_total);
    aii_re=new[aii_total];aii_im=new[aii_total];aii_last=new[aii_total];
    for(int j=0;j<aii_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      aii_re[j]=re;aii_im[j]=im;aii_last[j]=last;
    end
    $fclose(fd);
    fd=$fopen({directory,"/sy_in.txt"},"r");
    rc=$fscanf(fd,"%d",sii_total);
    sii_re=new[sii_total];sii_im=new[sii_total];sii_last=new[sii_total];
    for(int j=0;j<sii_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",re,im,last);
      sii_re[j]=re;sii_im[j]=im;sii_last[j]=last;
    end
    $fclose(fd);
    afd=$fopen({directory,"/an_out.txt"},"r");rc=$fscanf(afd,"%d",ao_total);
    sfd=$fopen({directory,"/sy_out.txt"},"r");rc=$fscanf(sfd,"%d",so_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    if(mid_reset||out_reset) begin
      scoring=0;
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=aii_total;
      for(int j=0;j<aii_total;j=j+1) if(aii_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=sii_total;
      for(int j=0;j<sii_total;j=j+1) if(sii_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_an(aii_re[j],aii_im[j],aii_last[j]);
        @(negedge clk);ai_valid=0;ai_last=0;
        for(int j=0;j<n1;j=j+1) drive_sy(sii_re[j],sii_im[j],sii_last[j]);
        @(negedge clk);si_valid=0;si_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_an(aii_re[j],aii_im[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_sy(sii_re[j],sii_im[j],0);
      end
      @(negedge clk);ai_valid=0;ai_last=0;si_valid=0;si_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(ao_valid!==1'b0||so_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(ao_error!==1'b0||so_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
    end
    fork
      begin
        for(int j=0;j<aii_total;j=j+1) drive_an(aii_re[j],aii_im[j],aii_last[j]);
        @(negedge clk);ai_valid=0;ai_last=0;
      end
      begin
        for(int j=0;j<sii_total;j=j+1) drive_sy(sii_re[j],sii_im[j],sii_last[j]);
        @(negedge clk);si_valid=0;si_last=0;
      end
    join
    wait(ao_checked==ao_total&&so_checked==so_total);
    repeat(20) @(negedge clk);
    if(ao_error!==1'b0||so_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete (analysis %0d, synthesis %0d)",ao_error,so_error);
    check_stft_bounds();
    if($test$plusargs("CHECK_ACCUMULATOR"))check_istft_widths();
    $display("PASS STFT: %0d spectra, %0d samples, %0d cycles",ao_checked,so_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"STFT testbench did not drain"); end
endmodule
