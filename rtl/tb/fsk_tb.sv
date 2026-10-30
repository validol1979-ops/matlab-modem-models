// M-FSK transmitter (rtl/common/fsk_tx.sv) and receiver (rtl/common/fsk_rx.sv) against the
// integer model (tools/fsk_cases.py vectors). Both DUTs run in one bench on independent streams.
// Each DUT is configured with M step transfers, one per transfer (m = 0..M-1, cfg_last on the
// last one, cfg_n sampled with cfg_last, accepted while cfg_ready); the bench waits for
// `configured` on both, then streams the transactions from *_in.txt. A TX transaction is labels
// (s_last on the last one) and answers with n samples per label (m_last on the very last); an RX
// transaction is whole symbols of n samples (s_last on the last sample) and answers with one
// label per symbol (m_last on the last label). Every accepted output is scored against *_out.txt
// (values and last bit-exact). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers,
// +STALL_OUTPUT random m_ready (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts the first
// expected TX output re (negative control, [NUMERIC]). Requires both error flags to stay 0.
// +MID_RESET drives half of the first transaction of both streams, resets both DUTs in the
// middle of them and requires them to come back silent (no output valid, configured low, no
// error) before both configurations and both streams are driven again from the start (nothing
// is scored during that warm-up phase). +OUT_RESET is the same block, but the warm-up drives
// the WHOLE first transaction of both streams and the reset lands as soon as the DUTs have
// delivered at least one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configurations themselves: for every DUT the first C/2 cfg transfers
// (never the one with cfg_last; for C == 1 the single transfer in full) are driven, then one reset
// lands on the next negedge, then both configurations and both streams run again from the start and
// only then are scored.
// Simulation-only logical bounds monitor (rtl/tb/fsk_bounds_check.svh) watches the accepted
// config writes, the step table reads, the symbol index t < n and the RX pending/FIFO
// reservations; +INJECT_BOUND_MISMATCH routes a corrupted index through the same validator as
// a real access. PASS BOUNDS fsk prints before the final PASS.
`timescale 1ns/1ps
module fsk_tb;
  parameter bit RESET_ACTIVE=1;
  parameter integer LOG2M=2,LOG2NMAX=5;
  parameter string TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  localparam integer LABEL_W=LOG2M==0 ? 1 : LOG2M;   // a zero bit alphabet is driven on 1 bit
  localparam integer NBITS=LOG2NMAX+1;               // cfg_n holds n up to 2^LOG2NMAX
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  integer tcf,tif,tof,rif,rof,rc,stall_in,stall_out,inject;
  // Transmitter configuration and streams.
  logic t_cfg_valid=0,t_cfg_last=0,t_cfg_ready,t_configured,t_error;
  logic [31:0] t_cfg_step=0;
  logic [NBITS-1:0] t_cfg_n=0;
  logic ts_valid=0,ts_last=0,ts_ready;
  logic [LABEL_W-1:0] ts_label=0;
  logic tm_valid,tm_last,tm_ready=1;
  logic signed [17:0] tm_re,tm_im;
  // Receiver configuration and streams.
  logic r_cfg_valid=0,r_cfg_last=0,r_cfg_ready,r_configured,r_error;
  logic [31:0] r_cfg_step=0;
  logic [NBITS-1:0] r_cfg_n=0;
  logic rs_valid=0,rs_last=0,rs_ready;
  logic signed [17:0] rs_re=0,rs_im=0;
  logic rm_valid,rm_last,rm_ready=1;
  logic [LABEL_W-1:0] rm_label;
  fsk_tx #(.LOG2M(LOG2M),.LOG2NMAX(LOG2NMAX),.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut_tx
   (.clk(clk),.rst(rst),
    .cfg_valid(t_cfg_valid),.cfg_last(t_cfg_last),.cfg_step(t_cfg_step),.cfg_n(t_cfg_n),
    .cfg_ready(t_cfg_ready),.configured(t_configured),
    .s_valid(ts_valid),.s_last(ts_last),.s_label(ts_label),.s_ready(ts_ready),
    .m_valid(tm_valid),.m_last(tm_last),.m_re(tm_re),.m_im(tm_im),.m_ready(tm_ready),.error(t_error));
  fsk_rx #(.LOG2M(LOG2M),.LOG2NMAX(LOG2NMAX),.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut_rx
   (.clk(clk),.rst(rst),
    .cfg_valid(r_cfg_valid),.cfg_last(r_cfg_last),.cfg_step(r_cfg_step),.cfg_n(r_cfg_n),
    .cfg_ready(r_cfg_ready),.configured(r_configured),
    .s_valid(rs_valid),.s_last(rs_last),.s_re(rs_re),.s_im(rs_im),.s_ready(rs_ready),
    .m_valid(rm_valid),.m_last(rm_last),.m_label(rm_label),.m_ready(rm_ready),.error(r_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_tx m")) check_tm
   (.clk(clk),.rst(rst),.valid(tm_valid),.ready(tm_ready),.last(tm_last),.data({tm_re,tm_im}));
  axis_check #(.WIDTH(LABEL_W),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_rx m")) check_rm
   (.clk(clk),.rst(rst),.valid(rm_valid),.ready(rm_ready),.last(rm_last),.data(rm_label));
  axis_check #(.WIDTH(32+NBITS),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_tx cfg")) check_tcfg
   (.clk(clk),.rst(rst),.valid(t_cfg_valid),.ready(t_cfg_ready),.last(t_cfg_last),.data({t_cfg_step,t_cfg_n}));
  axis_check #(.WIDTH(32+NBITS),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_rx cfg")) check_rcfg
   (.clk(clk),.rst(rst),.valid(r_cfg_valid),.ready(r_cfg_ready),.last(r_cfg_last),.data({r_cfg_step,r_cfg_n}));
  axis_check #(.WIDTH(LABEL_W),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_tx s")) check_ts
   (.clk(clk),.rst(rst),.valid(ts_valid),.ready(ts_ready),.last(ts_last),.data(ts_label));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_rx s")) check_rs
   (.clk(clk),.rst(rst),.valid(rs_valid),.ready(rs_ready),.last(rs_last),.data({rs_re,rs_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_tx m")) cover_tm
   (.clk(clk),.rst(rst),.valid(tm_valid),.ready(tm_ready),.last(tm_last),.data({tm_re,tm_im}),.mode(0));
  stream_cover #(.FIELDS(1),.FW(LABEL_W),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fsk_rx m")) cover_rm
   (.clk(clk),.rst(rst),.valid(rm_valid),.ready(rm_ready),.last(rm_last),.data(rm_label),.mode(0));
  int cfg_step[];
  int cfg_count,cfg_n;
  int ti_label[],ti_last[],ti_total;
  int ri_re[],ri_im[],ri_last[],ri_total;
  int to_total,to_checked=0,ro_total,ro_checked=0;
  bit scoring=1;
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin tm_ready<=(($urandom%3)!=0);rm_ready<=(($urandom%3)!=0); end
  `include "fsk_bounds_check.svh"
  // Scoreboards: every accepted output must equal fsk_fixed.transmit / fsk_fixed.receive exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&tm_valid&&tm_ready) begin
      rc=$fscanf(tof,"%d %d %d",re,im,last);
      if(inject&&to_checked==0) re=re+1;
      if(tm_re!==18'(re)||tm_im!==18'(im)||tm_last!==1'(last)) begin
        $display("MISMATCH tx output %0d: %0d,%0d/%0d,%0d last %0d/%0d",to_checked,tm_re,tm_im,re,im,tm_last,last);
        $fatal(1,"[NUMERIC] fsk_tx output");
      end
      to_checked=to_checked+1;
    end
    if(t_error!==1'b0) $fatal(1,"[NUMERIC] fsk_tx error asserted");
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int label,last;
    if(scoring&&rm_valid&&rm_ready) begin
      rc=$fscanf(rof,"%d %d",label,last);
      if(rm_label!==LABEL_W'(label)||rm_last!==1'(last)) begin
        $display("MISMATCH rx label %0d: %0d/%0d last %0d/%0d",ro_checked,rm_label,label,rm_last,last);
        $fatal(1,"[NUMERIC] fsk_rx label");
      end
      ro_checked=ro_checked+1;
    end
    if(r_error!==1'b0) $fatal(1,"[NUMERIC] fsk_rx error asserted");
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((tm_valid&&tm_ready)||(rm_valid&&rm_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge.
  task automatic drive_tx_cfg;
    for(int m=0;m<cfg_count;m=m+1) begin
      @(negedge clk);
      t_cfg_valid=1;t_cfg_step=32'(cfg_step[m]);t_cfg_n=NBITS'(cfg_n);t_cfg_last=m==cfg_count-1;
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(t_cfg_valid&&t_cfg_ready) break;
      end
    end
    @(negedge clk);t_cfg_valid=0;t_cfg_last=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(t_configured) return;
    end
    $fatal(1,"[TIMEOUT] fsk_tx never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_rx_cfg;
    for(int m=0;m<cfg_count;m=m+1) begin
      @(negedge clk);
      r_cfg_valid=1;r_cfg_step=32'(cfg_step[m]);r_cfg_n=NBITS'(cfg_n);r_cfg_last=m==cfg_count-1;
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(r_cfg_valid&&r_cfg_ready) break;
      end
    end
    @(negedge clk);r_cfg_valid=0;r_cfg_last=0;
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(r_configured) return;
    end
    $fatal(1,"[TIMEOUT] fsk_rx never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_tx_in(input int label,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ts_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ts_valid=1;ts_label=LABEL_W'(label);ts_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(ts_valid&&ts_ready) return;
    end
    $fatal(1,"[THROUGHPUT] fsk_tx input label never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_rx_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);rs_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    rs_valid=1;rs_re=18'(re);rs_im=18'(im);rs_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(rs_valid&&rs_ready) return;
    end
    $fatal(1,"[THROUGHPUT] fsk_rx input sample never accepted (cycle %0d)",cycle);
  endtask
  // +CFG_RESET warm-up of one DUT: the first C/2 cfg transfers, never the one with cfg_last; when
  // the configuration has a single transfer (C == 1) it is driven in full and not checked.
  task automatic drive_partial_tx_cfg;
    int c=(cfg_count>=2)?cfg_count/2:cfg_count;
    for(int m=0;m<c;m=m+1) begin
      @(negedge clk);
      t_cfg_valid=1;t_cfg_step=32'(cfg_step[m]);t_cfg_n=NBITS'(cfg_n);t_cfg_last=1'(cfg_count==1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(t_cfg_valid&&t_cfg_ready) break;
      end
    end
    @(negedge clk);t_cfg_valid=0;t_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(cfg_count>=2&&t_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  task automatic drive_partial_rx_cfg;
    int c=(cfg_count>=2)?cfg_count/2:cfg_count;
    for(int m=0;m<c;m=m+1) begin
      @(negedge clk);
      r_cfg_valid=1;r_cfg_step=32'(cfg_step[m]);r_cfg_n=NBITS'(cfg_n);r_cfg_last=1'(cfg_count==1);
      for(int guard=0;guard<65536;guard++) begin
        @(posedge clk);
        if(r_cfg_valid&&r_cfg_ready) break;
      end
    end
    @(negedge clk);r_cfg_valid=0;r_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(cfg_count>=2&&r_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  // The whole configuration of both DUTs: M step transfers each, then wait for `configured`.
  task automatic configure;
    fork
      drive_tx_cfg;
      drive_rx_cfg;
    join
    if(t_error!==1'b0||r_error!==1'b0) $fatal(1,"[NUMERIC] error asserted after configuration");
  endtask
  initial begin
    int step,value,re,im,last,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    // One configuration for both DUTs: M steps, then n.
    tcf=$fopen({directory,"/cfg.txt"},"r");
    rc=$fscanf(tcf,"%d",cfg_count);
    cfg_step=new[cfg_count];
    for(int j=0;j<cfg_count;j=j+1) begin
      rc=$fscanf(tcf,"%d",step);
      cfg_step[j]=step;
    end
    rc=$fscanf(tcf,"%d",cfg_n);
    $fclose(tcf);
    tif=$fopen({directory,"/tx_in.txt"},"r");
    rc=$fscanf(tif,"%d",ti_total);
    ti_label=new[ti_total];ti_last=new[ti_total];
    for(int j=0;j<ti_total;j=j+1) begin
      rc=$fscanf(tif,"%d %d",value,last);
      ti_label[j]=value;ti_last[j]=last;
    end
    $fclose(tif);
    rif=$fopen({directory,"/rx_in.txt"},"r");
    rc=$fscanf(rif,"%d",ri_total);
    ri_re=new[ri_total];ri_im=new[ri_total];ri_last=new[ri_total];
    for(int j=0;j<ri_total;j=j+1) begin
      rc=$fscanf(rif,"%d %d %d",re,im,last);
      ri_re[j]=re;ri_im[j]=im;ri_last[j]=last;
    end
    $fclose(rif);
    tof=$fopen({directory,"/tx_out.txt"},"r");rc=$fscanf(tof,"%d",to_total);
    rof=$fopen({directory,"/rx_out.txt"},"r");rc=$fscanf(rof,"%d",ro_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: M step transfers each, then wait for `configured`.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // the partial configuration of both DUTs, then the single shared reset below
        fork
          drive_partial_tx_cfg;
          drive_partial_rx_cfg;
        join
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=ti_total;
      for(int j=0;j<ti_total;j=j+1) if(ti_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=ri_total;
      for(int j=0;j<ri_total;j=j+1) if(ri_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_tx_in(ti_label[j],ti_last[j]);
        @(negedge clk);ts_valid=0;ts_last=0;
        for(int j=0;j<n1;j=j+1) drive_rx_in(ri_re[j],ri_im[j],ri_last[j]);
        @(negedge clk);rs_valid=0;rs_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_tx_in(ti_label[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_rx_in(ri_re[j],ri_im[j],0);
      end
      end
      @(negedge clk);t_cfg_valid=0;t_cfg_last=0;r_cfg_valid=0;r_cfg_last=0;
      ts_valid=0;ts_last=0;rs_valid=0;rs_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(tm_valid!==1'b0||rm_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(t_configured!==1'b0||r_configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(t_error!==1'b0||r_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions on both independent streams.
    fork
      begin
        for(int j=0;j<ti_total;j=j+1) drive_tx_in(ti_label[j],ti_last[j]);
        @(negedge clk);ts_valid=0;ts_last=0;
      end
      begin
        for(int j=0;j<ri_total;j=j+1) drive_rx_in(ri_re[j],ri_im[j],ri_last[j]);
        @(negedge clk);rs_valid=0;rs_last=0;
      end
    join
    wait(to_checked==to_total&&ro_checked==ro_total);
    repeat(20) @(negedge clk);
    if(t_error!==1'b0||r_error!==1'b0)
      $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    check_fsk_bounds();
    $display("PASS FSK: %0d samples, %0d labels, %0d cycles",to_checked,ro_checked,cycle);
    $finish;
  end
  initial begin #500000000;$fatal(1,"FSK testbench did not drain"); end
endmodule
