// Notch IIR (rtl/common/notch_iir.sv) and scalar Kalman (rtl/common/kalman_scalar.sv) against
// the integer model (tools/oset_cases.py vectors). Both DUTs run in one bench on independent
// streams. Each DUT is configured with ONE transfer (all coefficients at once, accepted while
// cfg_ready): the notch takes b1,a1,a2 (Q16), the Kalman q,r,p0 (Q24); the bench waits for
// `configured` on both, then streams one transaction per signal from *_in.txt (s_last on its
// last sample). Each transaction restarts the filter state (and the Kalman covariance from P0)
// and answers with the same number of outputs (m_last on the last). Every accepted output is
// scored against *_out.txt (re, im and last bit-exact). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to
// both drivers, +STALL_OUTPUT random m_ready (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts
// the first expected notch output re (negative control, [NUMERIC]). Ends when both scoreboards
// are complete and requires the Kalman error to stay 0. +MID_RESET drives half of the first
// transaction of both streams, resets both DUTs in the middle of them and requires them to come
// back silent (no output valid, configured low, no error) before both configurations and both
// streams are driven again from the start (nothing is scored during that warm-up phase).
// +OUT_RESET is the same block, but the warm-up drives the WHOLE first transaction of both
// streams and the reset lands as soon as the DUTs have delivered at least one accepted output
// (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: both DUTs have C == 1 cfg transfer, so the bench
// drives that single transfer of each DUT and resets on the very next negedge (no configured check
// for C == 1), then both configurations and both streams run again from the start and only then are
// scored.
`timescale 1ns/1ps
module oset_tb;
  parameter bit RESET_ACTIVE=1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer ncf,nif,nof,kcf,kif,kof,rc,stall_in,stall_out,inject;
  // Notch configuration and stream.
  logic n_cfg_valid=0,n_cfg_ready,n_configured;
  logic signed [17:0] n_cfg_b1=0,n_cfg_a1=0,n_cfg_a2=0;
  logic ns_valid=0,ns_last=0,ns_ready;
  logic signed [17:0] ns_re=0,ns_im=0;
  logic nm_valid,nm_last,nm_ready=1;
  logic signed [17:0] nm_re,nm_im;
  // Kalman configuration and stream.
  logic k_cfg_valid=0,k_cfg_ready,k_configured;
  logic [31:0] k_cfg_q=0,k_cfg_r=0,k_cfg_p0=0;
  logic ks_valid=0,ks_last=0,ks_ready;
  logic signed [17:0] ks_re=0,ks_im=0;
  logic km_valid,km_last,km_ready=1,km_error;
  logic signed [17:0] km_re,km_im;
  notch_iir #(.RESET_ACTIVE(RESET_ACTIVE)) dut_notch
   (.clk(clk),.rst(rst),
    .cfg_valid(n_cfg_valid),.cfg_b1(n_cfg_b1),.cfg_a1(n_cfg_a1),.cfg_a2(n_cfg_a2),
    .cfg_ready(n_cfg_ready),.configured(n_configured),
    .s_valid(ns_valid),.s_last(ns_last),.s_re(ns_re),.s_im(ns_im),.s_ready(ns_ready),
    .m_valid(nm_valid),.m_last(nm_last),.m_re(nm_re),.m_im(nm_im),.m_ready(nm_ready));
  kalman_scalar #(.RESET_ACTIVE(RESET_ACTIVE)) dut_kalman
   (.clk(clk),.rst(rst),
    .cfg_valid(k_cfg_valid),.cfg_q(k_cfg_q),.cfg_r(k_cfg_r),.cfg_p0(k_cfg_p0),
    .cfg_ready(k_cfg_ready),.configured(k_configured),
    .s_valid(ks_valid),.s_last(ks_last),.s_re(ks_re),.s_im(ks_im),.s_ready(ks_ready),
    .m_valid(km_valid),.m_last(km_last),.m_re(km_re),.m_im(km_im),.m_ready(km_ready),.error(km_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("notch m")) check_nm
   (.clk(clk),.rst(rst),.valid(nm_valid),.ready(nm_ready),.last(nm_last),.data({nm_re,nm_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("kalman m")) check_km
   (.clk(clk),.rst(rst),.valid(km_valid),.ready(km_ready),.last(km_last),.data({km_re,km_im}));
  axis_check #(.WIDTH(54),.RESET_ACTIVE(RESET_ACTIVE),.NAME("notch cfg")) check_ncfg
   (.clk(clk),.rst(rst),.valid(n_cfg_valid),.ready(n_cfg_ready),.last(1'b0),.data({n_cfg_b1,n_cfg_a1,n_cfg_a2}));
  axis_check #(.WIDTH(96),.RESET_ACTIVE(RESET_ACTIVE),.NAME("kalman cfg")) check_kcfg
   (.clk(clk),.rst(rst),.valid(k_cfg_valid),.ready(k_cfg_ready),.last(1'b0),.data({k_cfg_q,k_cfg_r,k_cfg_p0}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("notch s")) check_ns
   (.clk(clk),.rst(rst),.valid(ns_valid),.ready(ns_ready),.last(ns_last),.data({ns_re,ns_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("kalman s")) check_ks
   (.clk(clk),.rst(rst),.valid(ks_valid),.ready(ks_ready),.last(ks_last),.data({ks_re,ks_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("notch m")) cover_nm
   (.clk(clk),.rst(rst),.valid(nm_valid),.ready(nm_ready),.last(nm_last),.data({nm_re,nm_im}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("kalman m")) cover_km
   (.clk(clk),.rst(rst),.valid(km_valid),.ready(km_ready),.last(km_last),.data({km_re,km_im}),.mode(0));
  int ni_re[],ni_im[],ni_last[],ni_total;
  int ki_re[],ki_im[],ki_last[],ki_total;
  int no_total,no_checked=0;
  int ko_total,ko_checked=0;
  bit scoring=1;
  `include "oset_bounds_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  // ---- saturation instrumentation (model rounding at the DUT's actual clamp edges) ----
  // notch: at ce&&a_valid the loop closes on yn=sat25((a1*yp+c)>>>16) (raw width 46 -> fits
  // 48 here, no longint needed) and the output register takes sat18(yn), whose rounding is
  // (yn+16)>>>5 in 26 bits (25-bit yn + 16 cannot overflow 26 bits, matches oset_fixed.rnd).
  // kalman: at `update` the output takes sat18(vn) with rounding (vn+128)>>>8; |vn| stays
  // below 2^25 (inputs and V carry 8 guard bits), so the 28-bit monitor sum equals the
  // 27-bit RTL rounding for every legal transaction (the numeric scoreboard guards that).
  wire n_sample = dut_notch.ce && dut_notch.a_valid;
  wire k_sample = dut_kalman.update;
  wire sat_done = scoring && (no_checked==no_total) && (ko_checked==ko_total);
  logic signed [31:0] nstate_rounded [0:1];
  logic signed [31:0] nout_rounded [0:1];
  logic signed [31:0] kout_rounded [0:1];
  always_comb begin
    nstate_rounded[0] = 32'((48'(dut_notch.a1)*48'(dut_notch.yp_re) + 48'(dut_notch.c_re)) >>> 16);
    nstate_rounded[1] = 32'((48'(dut_notch.a1)*48'(dut_notch.yp_im) + 48'(dut_notch.c_im)) >>> 16);
    nout_rounded[0] = 32'((26'(dut_notch.yn_re) + 26'sd16) >>> 5);
    nout_rounded[1] = 32'((26'(dut_notch.yn_im) + 26'sd16) >>> 5);
    kout_rounded[0] = 32'((28'(dut_kalman.vn_re) + 28'sd128) >>> 8);
    kout_rounded[1] = 32'((28'(dut_kalman.vn_im) + 28'sd128) >>> 8);
  end
  sat_event_check #(.FIELDS(2),.RAW_WIDTH(32),.OUT_WIDTH(25),.RESET_ACTIVE(RESET_ACTIVE),
    .NAME("notch_state"),.EXPECTED_FILE("notch_state_expected.txt")) sat_notch_state
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(n_sample),.done(sat_done),
     .rounded(nstate_rounded));
  sat_event_check #(.FIELDS(2),.RAW_WIDTH(32),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
    .NAME("notch_output"),.EXPECTED_FILE("notch_output_expected.txt")) sat_notch_output
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(n_sample),.done(sat_done),
     .rounded(nout_rounded));
  sat_event_check #(.FIELDS(2),.RAW_WIDTH(32),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
    .NAME("kalman"),.EXPECTED_FILE("kalman_expected.txt")) sat_kalman
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(k_sample),.done(sat_done),
     .rounded(kout_rounded));
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin nm_ready<=(($urandom%3)!=0);km_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal oset_fixed.notch / kalman exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&nm_valid&&nm_ready) begin
      rc=$fscanf(nof,"%d %d %d",re,im,last);
      if(inject&&no_checked==0) re=re+1;
      if(nm_re!==18'(re)||nm_im!==18'(im)||nm_last!==1'(last)) begin
        $display("MISMATCH notch output %0d: %0d,%0d/%0d,%0d last %0d/%0d",no_checked,nm_re,nm_im,re,im,nm_last,last);
        $fatal(1,"[NUMERIC] notch_iir output");
      end
      no_checked=no_checked+1;
    end
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&km_valid&&km_ready) begin
      rc=$fscanf(kof,"%d %d %d",re,im,last);
      if(km_re!==18'(re)||km_im!==18'(im)||km_last!==1'(last)) begin
        $display("MISMATCH kalman output %0d: %0d,%0d/%0d,%0d last %0d/%0d",ko_checked,km_re,km_im,re,im,km_last,last);
        $fatal(1,"[NUMERIC] kalman_scalar output");
      end
      ko_checked=ko_checked+1;
    end
    if(km_error!==1'b0) $fatal(1,"[NUMERIC] kalman error asserted");
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((nm_valid&&nm_ready)||(km_valid&&km_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_notch_cfg(input int b1,input int a1,input int a2);
    @(negedge clk);
    n_cfg_valid=1;n_cfg_b1=18'(b1);n_cfg_a1=18'(a1);n_cfg_a2=18'(a2);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(n_cfg_valid&&n_cfg_ready) break;
    end
    @(negedge clk);n_cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(n_configured) return;
    end
    $fatal(1,"[TIMEOUT] notch never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_kalman_cfg(input int q,input int r,input int p0);
    @(negedge clk);
    k_cfg_valid=1;k_cfg_q=32'(q);k_cfg_r=32'(r);k_cfg_p0=32'(p0);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(k_cfg_valid&&k_cfg_ready) break;
    end
    @(negedge clk);k_cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(k_configured) return;
    end
    $fatal(1,"[TIMEOUT] kalman never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_notch_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ns_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ns_valid=1;ns_re=18'(re);ns_im=18'(im);ns_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(ns_valid&&ns_ready) return;
    end
    $fatal(1,"[THROUGHPUT] notch input sample never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_kalman_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ks_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ks_valid=1;ks_re=18'(re);ks_im=18'(im);ks_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(ks_valid&&ks_ready) return;
    end
    $fatal(1,"[THROUGHPUT] kalman input sample never accepted (cycle %0d)",cycle);
  endtask
  // The whole configuration of both DUTs: one transfer each, then wait for `configured`.
  task automatic configure(input int b1,input int a1,input int a2,
                           input int q,input int r,input int p0);
    fork
      drive_notch_cfg(b1,a1,a2);
      drive_kalman_cfg(q,r,p0);
    join
    if(km_error!==1'b0) $fatal(1,"[NUMERIC] kalman error asserted after configuration");
  endtask
  initial begin
    int nb1,na1,na2,kq,kr,kp0,re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    ncf=$fopen({directory,"/notch_cfg.txt"},"r");
    rc=$fscanf(ncf,"%d %d %d",nb1,na1,na2);
    $fclose(ncf);
    kcf=$fopen({directory,"/kalman_cfg.txt"},"r");
    rc=$fscanf(kcf,"%d %d %d",kq,kr,kp0);
    $fclose(kcf);
    nif=$fopen({directory,"/notch_in.txt"},"r");
    rc=$fscanf(nif,"%d",ni_total);
    ni_re=new[ni_total];ni_im=new[ni_total];ni_last=new[ni_total];
    for(int j=0;j<ni_total;j=j+1) begin
      rc=$fscanf(nif,"%d %d %d",re,im,last);
      ni_re[j]=re;ni_im[j]=im;ni_last[j]=last;
    end
    $fclose(nif);
    kif=$fopen({directory,"/kalman_in.txt"},"r");
    rc=$fscanf(kif,"%d",ki_total);
    ki_re=new[ki_total];ki_im=new[ki_total];ki_last=new[ki_total];
    for(int j=0;j<ki_total;j=j+1) begin
      rc=$fscanf(kif,"%d %d %d",re,im,last);
      ki_re[j]=re;ki_im[j]=im;ki_last[j]=last;
    end
    $fclose(kif);
    nof=$fopen({directory,"/notch_out.txt"},"r");rc=$fscanf(nof,"%d",no_total);
    kof=$fopen({directory,"/kalman_out.txt"},"r");rc=$fscanf(kof,"%d",ko_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: one transfer each, then wait for `configured`.
    if(!cfg_reset) configure(nb1,na1,na2,kq,kr,kp0);
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C == 1 on both DUTs: the single cfg transfer of each one is driven in full and the reset
        // below lands on the very next negedge, while the DUTs have not started their streams
        fork
          begin
            @(negedge clk);n_cfg_valid=1;n_cfg_b1=18'(nb1);n_cfg_a1=18'(na1);n_cfg_a2=18'(na2);
            for(int guard=0;guard<65536;guard++) begin
              @(posedge clk);
              if(n_cfg_valid&&n_cfg_ready) break;
            end
            @(negedge clk);n_cfg_valid=0;   // stop feeding this DUT while the other one continues
          end
          begin
            @(negedge clk);k_cfg_valid=1;k_cfg_q=32'(kq);k_cfg_r=32'(kr);k_cfg_p0=32'(kp0);
            for(int guard=0;guard<65536;guard++) begin
              @(posedge clk);
              if(k_cfg_valid&&k_cfg_ready) break;
            end
            @(negedge clk);k_cfg_valid=0;   // stop feeding this DUT while the other one continues
          end
        join
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=ni_total;
      for(int j=0;j<ni_total;j=j+1) if(ni_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=ki_total;
      for(int j=0;j<ki_total;j=j+1) if(ki_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_notch_in(ni_re[j],ni_im[j],ni_last[j]);
        @(negedge clk);ns_valid=0;ns_last=0;
        for(int j=0;j<n1;j=j+1) drive_kalman_in(ki_re[j],ki_im[j],ki_last[j]);
        @(negedge clk);ks_valid=0;ks_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_notch_in(ni_re[j],ni_im[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_kalman_in(ki_re[j],ki_im[j],0);
      end
      end
      @(negedge clk);n_cfg_valid=0;k_cfg_valid=0;ns_valid=0;ns_last=0;ks_valid=0;ks_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(nm_valid!==1'b0||km_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(n_configured!==1'b0||k_configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(km_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure(nb1,na1,na2,kq,kr,kp0);
    end
    // Stream the transactions on both independent streams.
    fork
      begin
        for(int j=0;j<ni_total;j=j+1) drive_notch_in(ni_re[j],ni_im[j],ni_last[j]);
        @(negedge clk);ns_valid=0;ns_last=0;
      end
      begin
        for(int j=0;j<ki_total;j=j+1) drive_kalman_in(ki_re[j],ki_im[j],ki_last[j]);
        @(negedge clk);ks_valid=0;ks_last=0;
      end
    join
    wait(no_checked==no_total&&ko_checked==ko_total);
    repeat(20) @(negedge clk);
    if(km_error!==1'b0)
      $fatal(1,"[NUMERIC] kalman error asserted although every transaction was complete");
    check_oset_bounds();
    $display("PASS OSET: %0d notch, %0d kalman, %0d cycles",no_checked,ko_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"OSET testbench did not drain"); end
endmodule
