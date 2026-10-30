// LDPC decoder (rtl/common/ldpc_decoder.sv) and systematic GF(2) encoder (rtl/common/gf2_encoder.sv)
// against the integer model (tools/ldpc_cases.py vectors). Both DUTs run in one bench on independent
// streams. Each DUT is configured with a stream of single matrix bits accepted while cfg_ready with
// cfg_last on the last bit, the matrix rows in row-major order (decoder: H, m x n; encoder: A, m x k);
// the header fields (cfg_m, cfg_n / cfg_k, iterations, mode, alpha, beta) are held stable during the
// whole configuration and the bench waits for `configured` on both. dec_cfg.txt is the header line
// `m n iterations mode alpha beta` (alpha = round(alpha*256), beta = round(beta*256)) then the m*n
// bits, enc_cfg.txt is `m k` then the m*k bits. A decoder transaction is n Q8 LLRs (s_last on the
// n-th) and answers n outputs (bit, posterior; m_last on the n-th); an encoder transaction is k
// message bits (s_last on the k-th) and answers m parity bits then the k message bits (m_last on the
// last). Every accepted output is scored against *_out.txt (bit, posterior where present, and last
// bit-exact). +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready) to both drivers, +STALL_OUTPUT random m_ready
// (~2/3 high) to both DUTs, +INJECT_MISMATCH corrupts the first expected decoder posterior (negative
// control, [NUMERIC]). Ends when both scoreboards are complete and requires both errors to stay 0.
// +MID_RESET drives half of the first transaction of both streams, resets both DUTs in the middle
// of them and requires them to come back silent (no output valid, configured low, no error) before
// both configurations and both streams are driven again from the start (nothing is scored during
// that warm-up phase). +OUT_RESET is the same block, but the warm-up drives the WHOLE first
// transaction of both streams and the reset lands as soon as the DUTs have delivered at least one
// accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configurations themselves: for every DUT the first C/2 matrix bit
// transfers (never the one with cfg_last) are driven, then one reset lands on the next negedge, then
// both configurations and both streams run again from the start and only then are scored.
`timescale 1ns/1ps
module ldpc_tb;
  parameter int LOG2NMAX=7;
  parameter int LOG2MMAX=6;
  parameter int LOG2EMAX=9;
  parameter int LOG2KMAX=6;
  parameter bit RESET_ACTIVE=1;
  parameter string PHI_FILE="rtl/common/mem/ldpc_phi.mem";
  parameter string INV_FILE="rtl/common/mem/ldpc_inv.mem";
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory;
  int dcf,di,dof,ecf,ei,eof,rc,stall_in,stall_out,inject;
  // Decoder configuration and stream.
  logic d_cfg_valid=0,d_cfg_last=0,d_cfg_ready,d_configured,d_cfg_bit=0;
  logic [LOG2MMAX:0] d_cfg_m='0;
  logic [LOG2NMAX:0] d_cfg_n='0;
  logic [7:0] d_cfg_iterations='0;
  logic [1:0] d_cfg_mode='0;
  logic [8:0] d_cfg_alpha='0;
  logic [15:0] d_cfg_beta='0;
  logic ds_valid=0,ds_last=0,ds_ready;
  logic signed [15:0] ds_llr='0;
  logic dm_valid,dm_last,dm_ready=1,dm_error,dm_bit;
  logic signed [15:0] dm_posterior;
  // Encoder configuration and stream.
  logic e_cfg_valid=0,e_cfg_last=0,e_cfg_ready,e_configured,e_cfg_bit=0;
  logic [LOG2MMAX:0] e_cfg_m='0;
  logic [LOG2KMAX:0] e_cfg_k='0;
  logic es_valid=0,es_last=0,es_ready;
  logic es_bit=0;
  logic em_valid,em_last,em_ready=1,em_error,em_bit;
  ldpc_decoder #(.LOG2NMAX(LOG2NMAX),.LOG2MMAX(LOG2MMAX),.LOG2EMAX(LOG2EMAX),
                 .RESET_ACTIVE(RESET_ACTIVE),.PHI_FILE(PHI_FILE),.INV_FILE(INV_FILE)) dut_ldpc_decoder
   (.clk(clk),.rst(rst),
    .cfg_valid(d_cfg_valid),.cfg_last(d_cfg_last),.cfg_bit(d_cfg_bit),
    .cfg_m(d_cfg_m),.cfg_n(d_cfg_n),.cfg_iterations(d_cfg_iterations),.cfg_mode(d_cfg_mode),
    .cfg_alpha(d_cfg_alpha),.cfg_beta(d_cfg_beta),.cfg_ready(d_cfg_ready),.configured(d_configured),
    .s_valid(ds_valid),.s_last(ds_last),.s_llr(ds_llr),.s_ready(ds_ready),
    .m_valid(dm_valid),.m_last(dm_last),.m_bit(dm_bit),.m_posterior(dm_posterior),
    .m_ready(dm_ready),.error(dm_error));
  gf2_encoder #(.LOG2KMAX(LOG2KMAX),.LOG2MMAX(LOG2MMAX),.RESET_ACTIVE(RESET_ACTIVE)) dut_gf2_encoder
   (.clk(clk),.rst(rst),
    .cfg_valid(e_cfg_valid),.cfg_last(e_cfg_last),.cfg_bit(e_cfg_bit),
    .cfg_m(e_cfg_m),.cfg_k(e_cfg_k),.cfg_ready(e_cfg_ready),.configured(e_configured),
    .s_valid(es_valid),.s_last(es_last),.s_bit(es_bit),.s_ready(es_ready),
    .m_valid(em_valid),.m_last(em_last),.m_bit(em_bit),.m_ready(em_ready),.error(em_error));
  int dcfg_mode;
  axis_check #(.WIDTH(17),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ldpc_decoder m")) check_dm
   (.clk(clk),.rst(rst),.valid(dm_valid),.ready(dm_ready),.last(dm_last),.data({dm_bit,dm_posterior}));
  stream_cover #(.FIELDS(1),.FW(16),.MODES(4),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ldpc_decoder m")) cover_dm
   (.clk(clk),.rst(rst),.valid(dm_valid),.ready(dm_ready),.last(dm_last),.data(dm_posterior),.mode(dcfg_mode));
  axis_check #(.WIDTH(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gf2_encoder m")) check_em
   (.clk(clk),.rst(rst),.valid(em_valid),.ready(em_ready),.last(em_last),.data(em_bit));
  axis_check #(.WIDTH(1+(LOG2MMAX+1)+(LOG2NMAX+1)+8+2+9+16),.RESET_ACTIVE(RESET_ACTIVE),
               .NAME("ldpc_decoder cfg")) check_dcfg
   (.clk(clk),.rst(rst),.valid(d_cfg_valid),.ready(d_cfg_ready),.last(d_cfg_last),
    .data({d_cfg_bit,d_cfg_m,d_cfg_n,d_cfg_iterations,d_cfg_mode,d_cfg_alpha,d_cfg_beta}));
  axis_check #(.WIDTH(1+(LOG2MMAX+1)+(LOG2KMAX+1)),.RESET_ACTIVE(RESET_ACTIVE),
               .NAME("gf2_encoder cfg")) check_ecfg
   (.clk(clk),.rst(rst),.valid(e_cfg_valid),.ready(e_cfg_ready),.last(e_cfg_last),
    .data({e_cfg_bit,e_cfg_m,e_cfg_k}));
  axis_check #(.WIDTH(16),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ldpc_decoder s")) check_ds
   (.clk(clk),.rst(rst),.valid(ds_valid),.ready(ds_ready),.last(ds_last),.data(ds_llr));
  axis_check #(.WIDTH(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gf2_encoder s")) check_es
   (.clk(clk),.rst(rst),.valid(es_valid),.ready(es_ready),.last(es_last),.data(es_bit));
  stream_cover #(.FIELDS(1),.FW(1),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("gf2_encoder m")) cover_em
   (.clk(clk),.rst(rst),.valid(em_valid),.ready(em_ready),.last(em_last),.data(em_bit),.mode(0));
  int dcfg_m,dcfg_n,dcfg_iterations,dcfg_alpha,dcfg_beta,dcfg_bits[],dcfg_total;
  int ecfg_m,ecfg_k,ecfg_bits[],ecfg_total;
  bit [31:0] dhead_m,dhead_n,dhead_iterations,dhead_mode,dhead_alpha,dhead_beta;
  bit [31:0] ehead_m,ehead_k;
  int di_llr[],di_last[],di_total;
  int ei_bit[],ei_last[],ei_total;
  int do_total,do_checked=0;
  int eo_total,eo_checked=0;
  bit scoring=1;
  `include "ldpc_saturation_check.svh"
  `include "ldpc_bounds_check.svh"
  int mid_reset,out_reset,cfg_reset,warm_out=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) begin dm_ready<=(($urandom%3)!=0);em_ready<=(($urandom%3)!=0); end
  // Scoreboards: every accepted output must equal ldpc_fixed exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int bit_expect,post,last;
    if(scoring&&dm_valid&&dm_ready) begin
      rc=$fscanf(dof,"%d %d %d",bit_expect,post,last);
      if(inject&&do_checked==0) post=post+1;
      if(dm_bit!==1'(bit_expect)||dm_posterior!==16'(post)||dm_last!==1'(last)) begin
        $display("MISMATCH decoder output %0d: %0d,%0d/%0d,%0d last %0d/%0d",
                 do_checked,dm_bit,dm_posterior,bit_expect,post,dm_last,last);
        $fatal(1,"[NUMERIC] ldpc_decoder output");
      end
      do_checked=do_checked+1;
    end
    if(dm_error!==1'b0) $fatal(1,"[NUMERIC] ldpc_decoder error asserted");
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int bit_expect,last;
    if(scoring&&em_valid&&em_ready) begin
      rc=$fscanf(eof,"%d %d",bit_expect,last);
      if(em_bit!==1'(bit_expect)||em_last!==1'(last)) begin
        $display("MISMATCH encoder output %0d: %0d/%0d last %0d/%0d",eo_checked,em_bit,bit_expect,em_last,last);
        $fatal(1,"[NUMERIC] gf2_encoder output");
      end
      eo_checked=eo_checked+1;
    end
    if(em_error!==1'b0) $fatal(1,"[NUMERIC] gf2_encoder error asserted");
  end
  // +OUT_RESET: count the accepted outputs delivered on either stream while nothing is scored yet.
  always @(posedge clk) if(!scoring&&((dm_valid&&dm_ready)||(em_valid&&em_ready))) warm_out=warm_out+1;
  // Drivers: values change only on a negedge (no race with the DUT's posedge sampling),
  // then hold until the handshake on a posedge. The header fields stay stable throughout.
  task automatic drive_decoder_cfg;
    dhead_m=32'(dcfg_m);dhead_n=32'(dcfg_n);dhead_iterations=32'(dcfg_iterations);
    dhead_mode=32'(dcfg_mode);dhead_alpha=32'(dcfg_alpha);dhead_beta=32'(dcfg_beta);
    d_cfg_m=dhead_m[LOG2MMAX:0];d_cfg_n=dhead_n[LOG2NMAX:0];
    d_cfg_iterations=dhead_iterations[7:0];d_cfg_mode=dhead_mode[1:0];
    d_cfg_alpha=dhead_alpha[8:0];d_cfg_beta=dhead_beta[15:0];
    for(int j=0;j<dcfg_total;j=j+1) begin
      @(negedge clk);
      d_cfg_valid=1;d_cfg_bit=1'(dcfg_bits[j]);d_cfg_last=1'(j==dcfg_total-1);
      for(int guard=0;guard<1048576;guard++) begin
        @(posedge clk);
        if(d_cfg_valid&&d_cfg_ready) break;
      end
    end
    @(negedge clk);d_cfg_valid=0;d_cfg_last=0;d_cfg_bit=0;
    for(int guard=0;guard<1048576;guard++) begin
      @(posedge clk);
      if(d_configured) return;
    end
    $fatal(1,"[TIMEOUT] ldpc_decoder never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_encoder_cfg;
    ehead_m=32'(ecfg_m);ehead_k=32'(ecfg_k);
    e_cfg_m=ehead_m[LOG2MMAX:0];e_cfg_k=ehead_k[LOG2KMAX:0];
    for(int j=0;j<ecfg_total;j=j+1) begin
      @(negedge clk);
      e_cfg_valid=1;e_cfg_bit=1'(ecfg_bits[j]);e_cfg_last=1'(j==ecfg_total-1);
      for(int guard=0;guard<1048576;guard++) begin
        @(posedge clk);
        if(e_cfg_valid&&e_cfg_ready) break;
      end
    end
    @(negedge clk);e_cfg_valid=0;e_cfg_last=0;e_cfg_bit=0;
    for(int guard=0;guard<1048576;guard++) begin
      @(posedge clk);
      if(e_configured) return;
    end
    $fatal(1,"[TIMEOUT] gf2_encoder never configured (cycle %0d)",cycle);
  endtask
  task automatic drive_decoder_in(input int llr,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);ds_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    ds_valid=1;ds_llr=16'(llr);ds_last=1'(last);
    for(int guard=0;guard<1048576;guard++) begin
      @(posedge clk);
      if(ds_valid&&ds_ready) return;
    end
    $fatal(1,"[THROUGHPUT] ldpc_decoder input LLR never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_encoder_in(input int bit_in,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);es_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    es_valid=1;es_bit=1'(bit_in);es_last=1'(last);
    for(int guard=0;guard<1048576;guard++) begin
      @(posedge clk);
      if(es_valid&&es_ready) return;
    end
    $fatal(1,"[THROUGHPUT] gf2_encoder input bit never accepted (cycle %0d)",cycle);
  endtask
  // +CFG_RESET warm-up of one DUT: the first C/2 matrix bit transfers, never the one with cfg_last
  // (a configuration of a single bit is driven in full and not checked).
  task automatic drive_partial_decoder_cfg;
    int c=(dcfg_total>=2)?dcfg_total/2:dcfg_total;
    dhead_m=32'(dcfg_m);dhead_n=32'(dcfg_n);dhead_iterations=32'(dcfg_iterations);
    dhead_mode=32'(dcfg_mode);dhead_alpha=32'(dcfg_alpha);dhead_beta=32'(dcfg_beta);
    d_cfg_m=dhead_m[LOG2MMAX:0];d_cfg_n=dhead_n[LOG2NMAX:0];
    d_cfg_iterations=dhead_iterations[7:0];d_cfg_mode=dhead_mode[1:0];
    d_cfg_alpha=dhead_alpha[8:0];d_cfg_beta=dhead_beta[15:0];
    for(int j=0;j<c;j=j+1) begin
      @(negedge clk);
      d_cfg_valid=1;d_cfg_bit=1'(dcfg_bits[j]);d_cfg_last=1'(dcfg_total==1);
      for(int guard=0;guard<1048576;guard++) begin
        @(posedge clk);
        if(d_cfg_valid&&d_cfg_ready) break;
      end
    end
    @(negedge clk);d_cfg_valid=0;d_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(dcfg_total>=2&&d_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  task automatic drive_partial_encoder_cfg;
    int c=(ecfg_total>=2)?ecfg_total/2:ecfg_total;
    ehead_m=32'(ecfg_m);ehead_k=32'(ecfg_k);
    e_cfg_m=ehead_m[LOG2MMAX:0];e_cfg_k=ehead_k[LOG2KMAX:0];
    for(int j=0;j<c;j=j+1) begin
      @(negedge clk);
      e_cfg_valid=1;e_cfg_bit=1'(ecfg_bits[j]);e_cfg_last=1'(ecfg_total==1);
      for(int guard=0;guard<1048576;guard++) begin
        @(posedge clk);
        if(e_cfg_valid&&e_cfg_ready) break;
      end
    end
    @(negedge clk);e_cfg_valid=0;e_cfg_last=0;   // stop feeding this DUT while the other one continues
    if(ecfg_total>=2&&e_configured) $fatal(1,"[CFG_RESET] already configured");
  endtask
  // The whole configuration of both DUTs: a stream of matrix bits each, then wait for `configured`.
  task automatic configure;
    fork
      drive_decoder_cfg;
      drive_encoder_cfg;
    join
    if(dm_error!==1'b0) $fatal(1,"[NUMERIC] ldpc_decoder error asserted after configuration");
    if(em_error!==1'b0) $fatal(1,"[NUMERIC] gf2_encoder error asserted after configuration");
  endtask
  initial begin
    int value,last_read,n0,n1;
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    dcf=$fopen({directory,"/dec_cfg.txt"},"r");
    rc=$fscanf(dcf,"%d %d %d %d %d %d",dcfg_m,dcfg_n,dcfg_iterations,dcfg_mode,dcfg_alpha,dcfg_beta);
    dcfg_total=dcfg_m*dcfg_n;
    dcfg_bits=new[dcfg_total];
    for(int j=0;j<dcfg_total;j=j+1) begin
      rc=$fscanf(dcf,"%d",value);
      dcfg_bits[j]=value;
    end
    $fclose(dcf);
    ecf=$fopen({directory,"/enc_cfg.txt"},"r");
    rc=$fscanf(ecf,"%d %d",ecfg_m,ecfg_k);
    ecfg_total=ecfg_m*ecfg_k;
    ecfg_bits=new[ecfg_total];
    for(int j=0;j<ecfg_total;j=j+1) begin
      rc=$fscanf(ecf,"%d",value);
      ecfg_bits[j]=value;
    end
    $fclose(ecf);
    di=$fopen({directory,"/dec_in.txt"},"r");
    rc=$fscanf(di,"%d",di_total);
    di_llr=new[di_total];di_last=new[di_total];
    for(int j=0;j<di_total;j=j+1) begin
      rc=$fscanf(di,"%d %d",value,last_read);
      di_llr[j]=value;di_last[j]=last_read;
    end
    $fclose(di);
    ei=$fopen({directory,"/enc_in.txt"},"r");
    rc=$fscanf(ei,"%d",ei_total);
    ei_bit=new[ei_total];ei_last=new[ei_total];
    for(int j=0;j<ei_total;j=j+1) begin
      rc=$fscanf(ei,"%d %d",value,last_read);
      ei_bit[j]=value;ei_last[j]=last_read;
    end
    $fclose(ei);
    dof=$fopen({directory,"/dec_out.txt"},"r");rc=$fscanf(dof,"%d",do_total);
    eof=$fopen({directory,"/enc_out.txt"},"r");rc=$fscanf(eof,"%d",eo_total);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    // Configuration: a stream of matrix bits each, then wait for `configured`.
    if(!cfg_reset) configure;
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        // the partial configuration of both DUTs, then the single shared reset below
        fork
          drive_partial_decoder_cfg;
          drive_partial_encoder_cfg;
        join
      end else begin
      // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
      n0=di_total;
      for(int j=0;j<di_total;j=j+1) if(di_last[j]) begin n0=j+1;break; end
      // the same half transaction on the second, independent stream (n1 = its length)
      n1=ei_total;
      for(int j=0;j<ei_total;j=j+1) if(ei_last[j]) begin n1=j+1;break; end
      if(out_reset) begin
        // the WHOLE first transactions (with their real last flags), then wait for the first accepted output
        for(int j=0;j<n0;j=j+1) drive_decoder_in(di_llr[j],di_last[j]);
        @(negedge clk);ds_valid=0;ds_last=0;
        for(int j=0;j<n1;j=j+1) drive_encoder_in(ei_bit[j],ei_last[j]);
        @(negedge clk);es_valid=0;es_last=0;
        for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
        if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
      end else begin
        for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_decoder_in(di_llr[j],0);
        for(int j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) drive_encoder_in(ei_bit[j],0);
      end
      end
      @(negedge clk);d_cfg_valid=0;d_cfg_last=0;e_cfg_valid=0;e_cfg_last=0;
      ds_valid=0;ds_last=0;es_valid=0;es_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(dm_valid!==1'b0||em_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
      if(d_configured!==1'b0||e_configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(dm_error!==1'b0||em_error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
      repeat(2) @(negedge clk);
      scoring=1;
      // the full configuration from the start, then the transactions as usual
      configure;
    end
    // Stream the transactions on both independent streams.
    fork
      begin
        for(int j=0;j<di_total;j=j+1) drive_decoder_in(di_llr[j],di_last[j]);
        @(negedge clk);ds_valid=0;ds_last=0;
      end
      begin
        for(int j=0;j<ei_total;j=j+1) drive_encoder_in(ei_bit[j],ei_last[j]);
        @(negedge clk);es_valid=0;es_last=0;
      end
    join
    wait(do_checked==do_total&&eo_checked==eo_total);
    repeat(20) @(negedge clk);
    if(dm_error!==1'b0)
      $fatal(1,"[NUMERIC] ldpc_decoder error asserted although every transaction was complete");
    if(em_error!==1'b0)
      $fatal(1,"[NUMERIC] gf2_encoder error asserted although every transaction was complete");
    check_ldpc_bounds();
    check_ldpc_saturation();
    $display("PASS LDPC: %0d llrs, %0d bits, %0d cycles",do_checked,eo_checked,cycle);
    $finish;
  end
  initial begin #200000000;$fatal(1,"LDPC testbench did not drain"); end
endmodule
