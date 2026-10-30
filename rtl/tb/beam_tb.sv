// Integer beamformer (rtl/common/beamform.sv) and Alamouti decoder (rtl/common/alamouti_rx.sv)
// against the integer model (tools/beam_cases.py vectors). Both DUTs run in one bench on
// independent streams. Each DUT is configured with a stream of Q15 complex values (accepted while
// cfg_ready, cfg_last on the last one): the beamformer takes the M weights a_m (one per transfer,
// M <= 2^LOG2M), the Alamouti decoder h0 then h1; the bench waits for `configured` on both (a
// reciprocal of the weight energy is computed), then streams transactions from *_in.txt (s_last on
// the last sample of a transaction). A beamformer transaction is whole snapshots of M samples and
// answers one output per snapshot (m_last on the last); an Alamouti transaction is sample pairs and
// answers two outputs per pair (m_last on the very last). Every accepted output is scored against
// *_out.txt (re, im and last bit-exact). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers,
// +STALL_OUTPUT random m_ready (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts the first
// expected beamformer output re (negative control, [NUMERIC]). Ends when both scoreboards are
// complete and requires both errors to stay 0. +MID_RESET drives half of the first transaction of
// both streams, resets both DUTs in the middle of them and requires them to come back silent (no
// output valid, configured low, no error) before both configurations and both streams are driven
// again from the start (nothing is scored during that warm-up phase). +OUT_RESET is the same
// block, but the warm-up drives the WHOLE first transaction of both streams and the reset
// lands as soon as the DUTs have delivered at least one accepted output (otherwise [TIMEOUT]
// no output before OUT_RESET).
// +CFG_RESET interrupts the configurations themselves: for every DUT the first C/2 cfg transfers
// (never the one with cfg_last; for C == 1 the single transfer in full) are driven, then one reset
// lands on the next negedge, then both configurations and both streams run again from the start and
// only then are scored.
`timescale 1ns/1ps
module beam_tb;
  parameter int LOG2M=3;
  parameter bit RESET_ACTIVE=1;
  parameter int ENERGY_WIDTH=36+LOG2M;
  parameter int AL_SUM_WIDTH=38,AL_ENERGY_WIDTH=37,AL_SCALE_WIDTH=61;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  int bcf,bif,bof,acf,aif,aof,rc,stall_in,stall_out,inject;
  // Beamformer configuration and stream.
  logic b_cfg_valid=0,b_cfg_last=0,b_cfg_ready,b_configured;
  logic signed [17:0] b_cfg_re=0,b_cfg_im=0;
  logic bs_valid=0,bs_last=0,bs_ready;
  logic signed [17:0] bs_re=0,bs_im=0;
  logic bm_valid,bm_last,bm_ready=1,bm_error;
  logic signed [17:0] bm_re,bm_im;
  // Alamouti configuration and stream.
  logic a_cfg_valid=0,a_cfg_last=0,a_cfg_ready,a_configured;
  logic signed [17:0] a_cfg_re=0,a_cfg_im=0;
  logic as_valid=0,as_last=0,as_ready;
  logic signed [17:0] as_re=0,as_im=0;
  logic am_valid,am_last,am_ready=1,am_error;
  logic signed [17:0] am_re,am_im;
  beamform #(.LOG2M(LOG2M),.RESET_ACTIVE(RESET_ACTIVE),.ENERGY_WIDTH(ENERGY_WIDTH)) dut_beamform
   (.clk(clk),.rst(rst),
    .cfg_valid(b_cfg_valid),.cfg_last(b_cfg_last),.cfg_re(b_cfg_re),.cfg_im(b_cfg_im),
    .cfg_ready(b_cfg_ready),.configured(b_configured),
    .s_valid(bs_valid),.s_last(bs_last),.s_re(bs_re),.s_im(bs_im),.s_ready(bs_ready),
    .m_valid(bm_valid),.m_last(bm_last),.m_re(bm_re),.m_im(bm_im),.m_ready(bm_ready),.error(bm_error));
  alamouti_rx #(.RESET_ACTIVE(RESET_ACTIVE),.SUM_WIDTH(AL_SUM_WIDTH),.ENERGY_WIDTH(AL_ENERGY_WIDTH),.SCALE_WIDTH(AL_SCALE_WIDTH)) dut_alamouti
   (.clk(clk),.rst(rst),
    .cfg_valid(a_cfg_valid),.cfg_last(a_cfg_last),.cfg_re(a_cfg_re),.cfg_im(a_cfg_im),
    .cfg_ready(a_cfg_ready),.configured(a_configured),
    .s_valid(as_valid),.s_last(as_last),.s_re(as_re),.s_im(as_im),.s_ready(as_ready),
    .m_valid(am_valid),.m_last(am_last),.m_re(am_re),.m_im(am_im),.m_ready(am_ready),.error(am_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("beamform m")) check_bm
   (.clk(clk),.rst(rst),.valid(bm_valid),.ready(bm_ready),.last(bm_last),.data({bm_re,bm_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("alamouti m")) check_am
   (.clk(clk),.rst(rst),.valid(am_valid),.ready(am_ready),.last(am_last),.data({am_re,am_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("beamform cfg")) check_bcfg
   (.clk(clk),.rst(rst),.valid(b_cfg_valid),.ready(b_cfg_ready),.last(b_cfg_last),.data({b_cfg_re,b_cfg_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("alamouti cfg")) check_acfg
   (.clk(clk),.rst(rst),.valid(a_cfg_valid),.ready(a_cfg_ready),.last(a_cfg_last),.data({a_cfg_re,a_cfg_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("beamform s")) check_bs
   (.clk(clk),.rst(rst),.valid(bs_valid),.ready(bs_ready),.last(bs_last),.data({bs_re,bs_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("alamouti s")) check_as
   (.clk(clk),.rst(rst),.valid(as_valid),.ready(as_ready),.last(as_last),.data({as_re,as_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("beamform m")) cover_bm
   (.clk(clk),.rst(rst),.valid(bm_valid),.ready(bm_ready),.last(bm_last),.data({bm_re,bm_im}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("alamouti m")) cover_am
   (.clk(clk),.rst(rst),.valid(am_valid),.ready(am_ready),.last(am_last),.data({am_re,am_im}),.mode(0));
  int bcfg_re[],bcfg_im[],bcfg_total;
  int acfg_re[],acfg_im[],acfg_total;
  int bi_re[],bi_im[],bi_last[],bi_total;
  int ai_re[],ai_im[],ai_last[],ai_total;
  int bo_total,bo_checked=0;
  int ao_total,ao_checked=0;
  bit scoring=1;
  longint cycle=0;
  `include "beam_bounds_check.svh"
  `include "beam_energy_check.svh"
  `include "alamouti_width_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  // Saturation monitors: the pre-clamp rounded value at the DUT's own clamp edge. beamform applies
  // sat18 to q_re/q_im (AW+25 = 62+LOG2M bits) when q_valid is high,
  // alamouti_rx to q0r/q0i/q1r/q1i (AL_SCALE_WIDTH bits). The rounding expression mirrors sat18 with
  // sized signed operations (no longint cast); SAT_RAW covers both DUTs, also for LOG2M>4.
  localparam int SAT_BEAM=(62+LOG2M)>66 ? 62+LOG2M : 66;
  localparam int SAT_RAW=SAT_BEAM>AL_SCALE_WIDTH ? SAT_BEAM : AL_SCALE_WIDTH;
  logic signed [SAT_RAW-1:0] b_sat_rounded[0:1],a_sat_rounded[0:3];
  wire b_sat_done=(bo_checked==bo_total);
  wire a_sat_done=(ao_checked==ao_total);
  function automatic logic signed [SAT_RAW-1:0] sat_round(input logic signed [SAT_RAW-1:0] value,
                                                          input logic [6:0] shift);
    logic signed [SAT_RAW-1:0] rounded;
    rounded=(value+(SAT_RAW'(1) << (shift-7'd1))) >>> shift;
    return rounded;
  endfunction
  always_comb begin
    b_sat_rounded[0]=sat_round(SAT_RAW'(dut_beamform.q_re),dut_beamform.shift);
    b_sat_rounded[1]=sat_round(SAT_RAW'(dut_beamform.q_im),dut_beamform.shift);
    a_sat_rounded[0]=sat_round(SAT_RAW'(dut_alamouti.q0r),dut_alamouti.shift);
    a_sat_rounded[1]=sat_round(SAT_RAW'(dut_alamouti.q0i),dut_alamouti.shift);
    a_sat_rounded[2]=sat_round(SAT_RAW'(dut_alamouti.q1r),dut_alamouti.shift);
    a_sat_rounded[3]=sat_round(SAT_RAW'(dut_alamouti.q1i),dut_alamouti.shift);
  end
  sat_event_check #(.FIELDS(2),.RAW_WIDTH(SAT_RAW),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
                    .NAME("beam"),.EXPECTED_FILE("beam_expected.txt")) sat_beam
   (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(dut_beamform.q_valid),.done(b_sat_done),
    .rounded(b_sat_rounded));
  sat_event_check #(.FIELDS(4),.RAW_WIDTH(SAT_RAW),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
                    .NAME("alamouti"),.EXPECTED_FILE("alamouti_expected.txt")) sat_al
   (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(dut_alamouti.q_valid),.done(a_sat_done),
    .rounded(a_sat_rounded));
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin bm_ready<=(($urandom%3)!=0);am_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal beam_fixed exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&bm_valid&&bm_ready) begin
      rc=$fscanf(bof,"%d %d %d",re,im,last);
      if(inject&&bo_checked==0) re=re+1;
      if(bm_re!==18'(re)||bm_im!==18'(im)||bm_last!==1'(last)) begin
        $display("MISMATCH beamform output %0d: %0d,%0d/%0d,%0d last %0d/%0d",bo_checked,bm_re,bm_im,re,im,bm_last,last);
        $fatal(1,"[NUMERIC] beamform output");
      end
      bo_checked=bo_checked+1;
    end
    if(bm_error!==1'b0) $fatal(1,"[NUMERIC] beamform error asserted");
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&am_valid&&am_ready) begin
      rc=$fscanf(aof,"%d %d %d",re,im,last);
      if(am_re!==18'(re)||am_im!==18'(im)||am_last!==1'(last)) begin
        $display("MISMATCH alamouti output %0d: %0d,%0d/%0d,%0d last %0d/%0d",ao_checked,am_re,am_im,re,im,am_last,last);
        $fatal(1,"[NUMERIC] alamouti_rx output");
      end
      ao_checked=ao_checked+1;
    end
    if(am_error!==1'b0) $fatal(1,"[NUMERIC] alamouti_rx error asserted");
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((bm_valid&&bm_ready)||(am_valid&&am_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_bf_cfg;
    for(int j=0;j<bcfg_total;j=j+1) begin
      @(negedge clk);
      b_cfg_valid=1;b_cfg_re=18'(bcfg_re[j]);b_cfg_im=18'(bcfg_im[j]);b_cfg_last=1'(j==bcfg_total-1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(b_cfg_valid&&b_cfg_ready) break;
      end
    end
    @(negedge clk);b_cfg_valid=0;b_cfg_last=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(b_configured) return;
    end
    $fatal(1,"[TIMEOUT] beamform never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_al_cfg;
    for(int j=0;j<acfg_total;j=j+1) begin
      @(negedge clk);
      a_cfg_valid=1;a_cfg_re=18'(acfg_re[j]);a_cfg_im=18'(acfg_im[j]);a_cfg_last=1'(j==acfg_total-1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(a_cfg_valid&&a_cfg_ready) break;
      end
    end
    @(negedge clk);a_cfg_valid=0;a_cfg_last=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(a_configured) return;
    end
    $fatal(1,"[TIMEOUT] alamouti never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_bf_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);bs_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    bs_valid=1;bs_re=18'(re);bs_im=18'(im);bs_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(bs_valid&&bs_ready) return;
    end
    $fatal(1,"[THROUGHPUT] beamform input sample never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_al_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);as_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    as_valid=1;as_re=18'(re);as_im=18'(im);as_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(as_valid&&as_ready) return;
    end
    $fatal(1,"[THROUGHPUT] alamouti input sample never accepted (cycle %0d)",cycle);
  endtask
  // +CFG_RESET warm-up of one DUT: the first C/2 cfg transfers, never the one with cfg_last; when
  // the configuration has a single transfer (C == 1) it is driven in full and not checked.
  task automatic drive_partial_cfg_bf;
    int c=(bcfg_total>=2)?bcfg_total/2:bcfg_total;
    for(int j=0;j<c;j=j+1) begin
      @(negedge clk);
      b_cfg_valid=1;b_cfg_re=18'(bcfg_re[j]);b_cfg_im=18'(bcfg_im[j]);b_cfg_last=1'(bcfg_total==1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(b_cfg_valid&&b_cfg_ready) break;
      end
    end
    @(negedge clk);b_cfg_valid=0;b_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(bcfg_total>=2&&b_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  task automatic drive_partial_cfg_al;
    int c=(acfg_total>=2)?acfg_total/2:acfg_total;
    for(int j=0;j<c;j=j+1) begin
      @(negedge clk);
      a_cfg_valid=1;a_cfg_re=18'(acfg_re[j]);a_cfg_im=18'(acfg_im[j]);a_cfg_last=1'(acfg_total==1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(a_cfg_valid&&a_cfg_ready) break;
      end
    end
    @(negedge clk);a_cfg_valid=0;a_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(acfg_total>=2&&a_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  // The whole configuration of both DUTs: a stream of weights each, then wait for `configured`.
  task automatic configure;
    fork
      drive_bf_cfg;
      drive_al_cfg;
    join
    if(bm_error!==1'b0) $fatal(1,"[NUMERIC] beamform error asserted after configuration");
    if(am_error!==1'b0) $fatal(1,"[NUMERIC] alamouti error asserted after configuration");
  endtask
  initial begin
    int re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    bcf=$fopen({directory,"/bf_cfg.txt"},"r");
    rc=$fscanf(bcf,"%d",bcfg_total);
    bcfg_re=new[bcfg_total];bcfg_im=new[bcfg_total];
    for(int j=0;j<bcfg_total;j=j+1) begin
      rc=$fscanf(bcf,"%d %d",re,im);
      bcfg_re[j]=re;bcfg_im[j]=im;
    end
    $fclose(bcf);
    acf=$fopen({directory,"/al_cfg.txt"},"r");
    rc=$fscanf(acf,"%d",acfg_total);
    acfg_re=new[acfg_total];acfg_im=new[acfg_total];
    for(int j=0;j<acfg_total;j=j+1) begin
      rc=$fscanf(acf,"%d %d",re,im);
      acfg_re[j]=re;acfg_im[j]=im;
    end
    $fclose(acf);
    bif=$fopen({directory,"/bf_in.txt"},"r");
    rc=$fscanf(bif,"%d",bi_total);
    bi_re=new[bi_total];bi_im=new[bi_total];bi_last=new[bi_total];
    for(int j=0;j<bi_total;j=j+1) begin
      rc=$fscanf(bif,"%d %d %d",re,im,last);
      bi_re[j]=re;bi_im[j]=im;bi_last[j]=last;
    end
    $fclose(bif);
    aif=$fopen({directory,"/al_in.txt"},"r");
    rc=$fscanf(aif,"%d",ai_total);
    ai_re=new[ai_total];ai_im=new[ai_total];ai_last=new[ai_total];
    for(int j=0;j<ai_total;j=j+1) begin
      rc=$fscanf(aif,"%d %d %d",re,im,last);
      ai_re[j]=re;ai_im[j]=im;ai_last[j]=last;
    end
    $fclose(aif);
    bof=$fopen({directory,"/bf_out.txt"},"r");rc=$fscanf(bof,"%d",bo_total);
    aof=$fopen({directory,"/al_out.txt"},"r");rc=$fscanf(aof,"%d",ao_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: a stream of weights each, then wait for `configured`.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // the partial configuration of both DUTs, then the single shared reset below
        fork
          drive_partial_cfg_bf;
          drive_partial_cfg_al;
        join
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=bi_total;
      for(int j=0;j<bi_total;j=j+1) if(bi_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=ai_total;
      for(int j=0;j<ai_total;j=j+1) if(ai_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_bf_in(bi_re[j],bi_im[j],bi_last[j]);
        @(negedge clk);bs_valid=0;bs_last=0;
        for(int j=0;j<n1;j=j+1) drive_al_in(ai_re[j],ai_im[j],ai_last[j]);
        @(negedge clk);as_valid=0;as_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_bf_in(bi_re[j],bi_im[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_al_in(ai_re[j],ai_im[j],0);
      end
      end
      @(negedge clk);b_cfg_valid=0;b_cfg_last=0;a_cfg_valid=0;a_cfg_last=0;
      bs_valid=0;bs_last=0;as_valid=0;as_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(bm_valid!==1'b0||am_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(b_configured!==1'b0||a_configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(bm_error!==1'b0||am_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions on both independent streams.
    fork
      begin
        for(int j=0;j<bi_total;j=j+1) drive_bf_in(bi_re[j],bi_im[j],bi_last[j]);
        @(negedge clk);bs_valid=0;bs_last=0;
      end
      begin
        for(int j=0;j<ai_total;j=j+1) drive_al_in(ai_re[j],ai_im[j],ai_last[j]);
        @(negedge clk);as_valid=0;as_last=0;
      end
    join
    wait(bo_checked==bo_total&&ao_checked==ao_total);
    repeat(20) @(negedge clk);
    if(bm_error!==1'b0)
      $fatal(1,"[NUMERIC] beamform error asserted although every transaction was complete");
    if(am_error!==1'b0)
      $fatal(1,"[NUMERIC] alamouti error asserted although every transaction was complete");
    check_beam_bounds();
    if($test$plusargs("CHECK_ENERGY"))check_beam_energy();
    if($test$plusargs("CHECK_ALAMOUTI_WIDTHS"))check_alamouti_widths();
    $display("PASS BEAM: %0d beams, %0d symbols, %0d cycles",bo_checked,ao_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"BEAM testbench did not drain"); end
endmodule
