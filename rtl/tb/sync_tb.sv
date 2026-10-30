// Integer Costas loop (rtl/common/costas_loop.sv) and Gardner timing loop
// (rtl/common/gardner_timing.sv) against the integer model (tools/sync_cases.py vectors). Both DUTs
// run in one bench on independent streams. Each DUT is configured with ONE transfer (the values are
// driven, the bench waits for cfg_ready and then for `configured`): the Costas loop takes the gains
// k1 and k2, the timing loop sps, count, the initial position (Q32) and the gains k3 and k4. A Costas
// transaction is one signal (s_last on its last sample) and answers one output per sample (value and
// the phase used for it); a timing transaction is one signal (s_last on its last sample) and answers
// exactly `count` outputs (mid value and position in Q16). Every accepted output is scored against
// *_out.txt (re, im, phase/position and last bit-exact, phases and positions as 32 bit signed).
// +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers, +STALL_OUTPUT random m_ready (~2/3 high) to
// both DUTs, +INJECT_MISMATCH corrupts the first expected Costas output re (negative control,
// [NUMERIC]). Ends when both scoreboards are complete and requires the timing error to stay 0.
// +MID_RESET drives half of the first transaction of both streams, resets both DUTs in the middle
// of them and requires them to come back silent (no output valid, configured low, no error) before
// both configurations and both streams are driven again from the start (nothing is scored during
// that warm-up phase). +OUT_RESET is the same block, but the warm-up drives the WHOLE first
// transaction of both streams and the reset lands as soon as the DUTs have delivered at least one
// accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configurations themselves: both DUTs have C == 1 cfg transfer, so the
// bench drives that single transfer of each DUT and resets on the very next negedge (no configured
// check for C == 1), then both configurations and both streams run again from the start and only
// then are scored.
`timescale 1ns/1ps
module sync_tb;
  parameter bit RESET_ACTIVE=1;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory,costas_observed;
  int observed_file=0,inject_slip_phase=0;
  int ccf,cif,cof,gcf,gif,gof,rc,stall_in,stall_out,inject;
  // Costas configuration and stream.
  logic c_cfg_valid=0,c_cfg_ready,c_configured;
  logic [31:0] c_cfg_k1=0,c_cfg_k2=0;
  logic cs_valid=0,cs_last=0,cs_ready;
  logic signed [17:0] cs_re=0,cs_im=0;
  logic cm_valid,cm_last,cm_ready=1;
  logic signed [17:0] cm_re,cm_im;
  logic signed [31:0] cm_phase;
  // Timing configuration and stream.
  logic g_cfg_valid=0,g_cfg_ready,g_configured;
  logic [7:0] g_cfg_sps=0;
  logic [15:0] g_cfg_count=0;
  logic [47:0] g_cfg_position=0;
  logic [31:0] g_cfg_k3=0,g_cfg_k4=0;
  logic gs_valid=0,gs_last=0,gs_ready;
  logic signed [17:0] gs_re=0,gs_im=0;
  logic gm_valid,gm_last,gm_ready=1,gm_error;
  logic signed [17:0] gm_re,gm_im;
  logic signed [31:0] gm_position;
  costas_loop #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut_costas
   (.clk(clk),.rst(rst),
    .cfg_valid(c_cfg_valid),.cfg_k1(c_cfg_k1),.cfg_k2(c_cfg_k2),
    .cfg_ready(c_cfg_ready),.configured(c_configured),
    .s_valid(cs_valid),.s_last(cs_last),.s_re(cs_re),.s_im(cs_im),.s_ready(cs_ready),
    .m_valid(cm_valid),.m_last(cm_last),.m_re(cm_re),.m_im(cm_im),.m_phase(cm_phase),.m_ready(cm_ready));
  gardner_timing #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut_timing
   (.clk(clk),.rst(rst),
    .cfg_valid(g_cfg_valid),.cfg_sps(g_cfg_sps),.cfg_count(g_cfg_count),.cfg_position(g_cfg_position),
    .cfg_k3(g_cfg_k3),.cfg_k4(g_cfg_k4),.cfg_ready(g_cfg_ready),.configured(g_configured),
    .s_valid(gs_valid),.s_last(gs_last),.s_re(gs_re),.s_im(gs_im),.s_ready(gs_ready),
    .m_valid(gm_valid),.m_last(gm_last),.m_re(gm_re),.m_im(gm_im),.m_position(gm_position),
    .m_ready(gm_ready),.error(gm_error));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas m")) check_cm
   (.clk(clk),.rst(rst),.valid(cm_valid),.ready(cm_ready),.last(cm_last),.data({cm_re,cm_im,cm_phase}));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gardner m")) check_gm
   (.clk(clk),.rst(rst),.valid(gm_valid),.ready(gm_ready),.last(gm_last),.data({gm_re,gm_im,gm_position}));
  axis_check #(.WIDTH(64),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas cfg")) check_ccfg
   (.clk(clk),.rst(rst),.valid(c_cfg_valid),.ready(c_cfg_ready),.last(1'b0),.data({c_cfg_k1,c_cfg_k2}));
  axis_check #(.WIDTH(136),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gardner cfg")) check_gcfg
   (.clk(clk),.rst(rst),.valid(g_cfg_valid),.ready(g_cfg_ready),.last(1'b0),
    .data({g_cfg_sps,g_cfg_count,g_cfg_position,g_cfg_k3,g_cfg_k4}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas s")) check_cs
   (.clk(clk),.rst(rst),.valid(cs_valid),.ready(cs_ready),.last(cs_last),.data({cs_re,cs_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gardner s")) check_gs
   (.clk(clk),.rst(rst),.valid(gs_valid),.ready(gs_ready),.last(gs_last),.data({gs_re,gs_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas m")) cover_cm
   (.clk(clk),.rst(rst),.valid(cm_valid),.ready(cm_ready),.last(cm_last),.data({cm_re,cm_im}),.mode(0));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gardner m")) cover_gm
   (.clk(clk),.rst(rst),.valid(gm_valid),.ready(gm_ready),.last(gm_last),.data({gm_re,gm_im}),.mode(0));
  longint c_k1,c_k2,g_k3,g_k4,g_position;
  int g_sps,g_count;
  int ci_re[],ci_im[],ci_last[],ci_total;
  int gi_re[],gi_im[],gi_last[],gi_total;
  int co_total,co_checked=0;
  int go_total,go_checked=0;
  bit scoring=1;
  `include "sync_gradient_check.svh"
  `include "sync_bounds_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin cm_ready<=(($urandom%3)!=0);gm_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal sync_fixed exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,phase,last;
    if(scoring&&cm_valid&&cm_ready) begin
      rc=$fscanf(cof,"%d %d %d %d",re,im,phase,last);
      if(inject&&co_checked==0) re=re+1;
      if(cm_re!==18'(re)||cm_im!==18'(im)||cm_phase!==phase||cm_last!==1'(last)) begin
        $display("MISMATCH costas output %0d: %0d,%0d/%0d,%0d phase %0d/%0d last %0d/%0d",
                 co_checked,cm_re,cm_im,re,im,cm_phase,phase,cm_last,last);
        $fatal(1,"[NUMERIC] costas_loop output");
      end
      // Capture the accepted DUT trajectory; reset warm-up and stalled cycles are excluded.
      if(observed_file) begin
        if(inject_slip_phase)
          $fwrite(observed_file,"%0d %0d %0d %0d\n",cm_re,cm_im,32'(cm_phase+32'sh40000000),cm_last);
        else
          $fwrite(observed_file,"%0d %0d %0d %0d\n",cm_re,cm_im,cm_phase,cm_last);
      end
      co_checked=co_checked+1;
    end
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,position,last;
    if(scoring&&gm_valid&&gm_ready) begin
      rc=$fscanf(gof,"%d %d %d %d",re,im,position,last);
      if(gm_re!==18'(re)||gm_im!==18'(im)||gm_position!==position||gm_last!==1'(last)) begin
        $display("MISMATCH timing output %0d: %0d,%0d/%0d,%0d position %0d/%0d last %0d/%0d",
                 go_checked,gm_re,gm_im,re,im,gm_position,position,gm_last,last);
        $fatal(1,"[NUMERIC] gardner_timing output");
      end
      go_checked=go_checked+1;
    end
    if(gm_error!==1'b0) $fatal(1,"[NUMERIC] gardner_timing error asserted");
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((cm_valid&&cm_ready)||(gm_valid&&gm_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_cl_cfg;
    @(negedge clk);
    c_cfg_valid=1;c_cfg_k1=32'(c_k1);c_cfg_k2=32'(c_k2);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(c_cfg_valid&&c_cfg_ready) break;
    end
    @(negedge clk);c_cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(c_configured) return;
    end
    $fatal(1,"[TIMEOUT] costas_loop never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_gt_cfg;
    @(negedge clk);
    g_cfg_valid=1;g_cfg_sps=8'(g_sps);g_cfg_count=16'(g_count);g_cfg_position=48'(g_position);
    g_cfg_k3=32'(g_k3);g_cfg_k4=32'(g_k4);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(g_cfg_valid&&g_cfg_ready) break;
    end
    @(negedge clk);g_cfg_valid=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(g_configured) return;
    end
    $fatal(1,"[TIMEOUT] gardner_timing never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_cl_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);cs_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    cs_valid=1;cs_re=18'(re);cs_im=18'(im);cs_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cs_valid&&cs_ready) return;
    end
    $fatal(1,"[THROUGHPUT] costas_loop input sample never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_gt_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);gs_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    gs_valid=1;gs_re=18'(re);gs_im=18'(im);gs_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(gs_valid&&gs_ready) return;
    end
    $fatal(1,"[THROUGHPUT] gardner_timing input sample never accepted (cycle %0d)",cycle);
  endtask
  // The whole configuration of both DUTs: one transfer each, then wait for `configured`.
  task automatic configure;
    fork
      drive_cl_cfg;
      drive_gt_cfg;
    join
    if(gm_error!==1'b0) $fatal(1,"[NUMERIC] gardner_timing error asserted after configuration");
  endtask
  initial begin
    int re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    inject_slip_phase=$test$plusargs("INJECT_SLIP_PHASE");
    if($value$plusargs("COSTAS_OBSERVED=%s",costas_observed)) begin
      observed_file=$fopen(costas_observed,"w");
      if(!observed_file) $fatal(1,"[SLIP] cannot open observed Costas trajectory");
    end
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    ccf=$fopen({directory,"/cl_cfg.txt"},"r");
    rc=$fscanf(ccf,"%d %d",c_k1,c_k2);
    $fclose(ccf);
    gcf=$fopen({directory,"/gt_cfg.txt"},"r");
    rc=$fscanf(gcf,"%d %d %d %d %d",g_sps,g_count,g_position,g_k3,g_k4);
    $fclose(gcf);
    cif=$fopen({directory,"/cl_in.txt"},"r");
    rc=$fscanf(cif,"%d",ci_total);
    ci_re=new[ci_total];ci_im=new[ci_total];ci_last=new[ci_total];
    for(int j=0;j<ci_total;j=j+1) begin
      rc=$fscanf(cif,"%d %d %d",re,im,last);
      ci_re[j]=re;ci_im[j]=im;ci_last[j]=last;
    end
    $fclose(cif);
    gif=$fopen({directory,"/gt_in.txt"},"r");
    rc=$fscanf(gif,"%d",gi_total);
    gi_re=new[gi_total];gi_im=new[gi_total];gi_last=new[gi_total];
    for(int j=0;j<gi_total;j=j+1) begin
      rc=$fscanf(gif,"%d %d %d",re,im,last);
      gi_re[j]=re;gi_im[j]=im;gi_last[j]=last;
    end
    $fclose(gif);
    cof=$fopen({directory,"/cl_out.txt"},"r");rc=$fscanf(cof,"%d",co_total);
    gof=$fopen({directory,"/gt_out.txt"},"r");rc=$fscanf(gof,"%d",go_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: one transfer each, then wait for `configured`.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // C == 1 on both DUTs: the single cfg transfer of each one is driven in full and the reset
        // below lands on the very next negedge, before any sample reaches the DUTs
        fork
          begin
            @(negedge clk);c_cfg_valid=1;c_cfg_k1=32'(c_k1);c_cfg_k2=32'(c_k2);
            for(int guard=0;guard<65536;guard++) begin
              @(posedge clk);
              if(c_cfg_valid&&c_cfg_ready) break;
            end
            @(negedge clk);c_cfg_valid=0;   // stop feeding this DUT while the other one continues
          end
          begin
            @(negedge clk);g_cfg_valid=1;g_cfg_sps=8'(g_sps);g_cfg_count=16'(g_count);
            g_cfg_position=48'(g_position);g_cfg_k3=32'(g_k3);g_cfg_k4=32'(g_k4);
            for(int guard=0;guard<65536;guard++) begin
              @(posedge clk);
              if(g_cfg_valid&&g_cfg_ready) break;
            end
            @(negedge clk);g_cfg_valid=0;   // stop feeding this DUT while the other one continues
          end
        join
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=ci_total;
      for(int j=0;j<ci_total;j=j+1) if(ci_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=gi_total;
      for(int j=0;j<gi_total;j=j+1) if(gi_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_cl_in(ci_re[j],ci_im[j],ci_last[j]);
        @(negedge clk);cs_valid=0;cs_last=0;
        for(int j=0;j<n1;j=j+1) drive_gt_in(gi_re[j],gi_im[j],gi_last[j]);
        @(negedge clk);gs_valid=0;gs_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_cl_in(ci_re[j],ci_im[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_gt_in(gi_re[j],gi_im[j],0);
      end
      end
      @(negedge clk);c_cfg_valid=0;g_cfg_valid=0;cs_valid=0;cs_last=0;gs_valid=0;gs_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(cm_valid!==1'b0||gm_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(c_configured!==1'b0||g_configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(gm_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions on both independent streams.
    fork
      begin
        for(int j=0;j<ci_total;j=j+1) drive_cl_in(ci_re[j],ci_im[j],ci_last[j]);
        @(negedge clk);cs_valid=0;cs_last=0;
      end
      begin
        for(int j=0;j<gi_total;j=j+1) drive_gt_in(gi_re[j],gi_im[j],gi_last[j]);
        @(negedge clk);gs_valid=0;gs_last=0;
      end
    join
    wait(co_checked==co_total&&go_checked==go_total);
    repeat(20) @(negedge clk);
    if(gm_error!==1'b0)
      $fatal(1,"[NUMERIC] gardner_timing error asserted although every transaction was complete");
    check_sync_gradient();
    check_sync_bounds();
    if(observed_file) $fclose(observed_file);
    $display("PASS SYNC: %0d costas, %0d timing, %0d cycles",co_checked,go_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"SYNC testbench did not drain"); end
endmodule
