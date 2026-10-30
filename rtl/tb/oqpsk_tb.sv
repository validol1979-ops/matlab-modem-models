// OQPSK RTL against the integer model (tools/oqpsk_cases.py vectors): oqpsk_tx samples,
// frame ends and last flags (tx_out.txt), oqpsk_rx acquisitions (rx_acquire.txt) and
// receiver symbols (values, labels, last flags; rx_out.txt), all bit-exact.
// +STALL_INPUT randomly deasserts the receiver wave s_valid, +STALL_OUTPUT random
// m_ready. +INJECT_MISMATCH corrupts the first expected acquisition, +INJECT_SYMBOL the
// first expected receiver value (negative controls, must print [NUMERIC]). In stream scenarios the receiver input must not wait more
// than 40 clocks in a row (the 32-clock FIR flush plus margin). +MID_RESET drives half of the
// first transmitter frame and half of the first receiver frame, resets both DUTs in the middle of
// them and requires them to come back silent (no output valid, no acquisition, configured low, no
// error) before the configuration and both whole streams are driven again from the start (nothing
// is scored during that warm-up phase). +OUT_RESET is the same block: it drives the WHOLE first
// transmitter frame and then enough of the receiver wave (frames are fed on until something comes
// out; a transmitter output counts too) and resets as soon as the DUTs have delivered at least one
// acquisition or one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
// +CFG_RESET interrupts the configuration itself: the first half of the preamble cfg transfers
// (never the one with cfg_last) is driven, both DUTs reset at the next negedge, then everything -
// the configuration included - runs again from the start and only then is scored.
`timescale 1ns/1ps
module oqpsk_tb;
 parameter bit RESET_ACTIVE=1;
 parameter integer SYMBOLS=768;
 parameter integer LOOP_DELAY=8;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0,rst=RESET_ACTIVE;
 always #5 clk=!clk;
 string directory;
 integer fd,rc,stall_in,stall_out,inject,inject_symbol;
 // Transmitter.
 logic s_valid=0,s_last=0,s_ready,tm_ready=1;
 logic [1:0] s_bit=0;
 logic m_valid,m_last;
 logic signed [17:0] m_re,m_im;
 oqpsk_tx #(.RESET_ACTIVE(RESET_ACTIVE)) dut(clk,rst,s_valid,s_bit,s_last,s_ready,tm_ready,m_valid,m_last,m_re,m_im);
 // Receiver.
 logic cfg_valid=0,cfg_last=0,cfg_ready,configured,error;
 logic [1:0] cfg_label=0;
 logic [11:0] cfg_count=12'(SYMBOLS);
 logic v_valid=0,v_last=0,v_ready;
 logic signed [17:0] v_re=0,v_im=0;
 logic mr_valid,mr_last,mr_ready=1;
 logic [1:0] mr_label;
 logic signed [17:0] mr_re,mr_im;
 logic acq_valid;
 logic signed [31:0] acq_delay,acq_frequency,acq_phase;
 oqpsk_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.LOOP_DELAY(LOOP_DELAY)) receiver(clk,rst,
  cfg_valid,cfg_last,cfg_label,cfg_count,cfg_ready,configured,error,
  v_valid,v_last,v_re,v_im,v_ready,
  mr_valid,mr_last,mr_label,mr_ready,mr_re,mr_im,
  acq_valid,acq_delay,acq_frequency,acq_phase);
 axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_tx m")) check_m
  (.clk(clk),.rst(rst),.valid(m_valid),.ready(tm_ready),.last(m_last),.data({m_re,m_im}));
 axis_check #(.WIDTH(38),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_rx m")) check_mr
  (.clk(clk),.rst(rst),.valid(mr_valid),.ready(mr_ready),.last(mr_last),.data({mr_label,mr_re,mr_im}));
 axis_check #(.WIDTH(2),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_tx s")) check_s
  (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data(s_bit));
 axis_check #(.WIDTH(2+12),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_rx cfg")) check_cfg
  (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_label,cfg_count}));
 axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_rx v")) check_v
  (.clk(clk),.rst(rst),.valid(v_valid),.ready(v_ready),.last(v_last),.data({v_re,v_im}));
 stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_tx m")) cover_m
  (.clk(clk),.rst(rst),.valid(m_valid),.ready(tm_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
 stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("oqpsk_rx m")) cover_mr
  (.clk(clk),.rst(rst),.valid(mr_valid),.ready(mr_ready),.last(mr_last),.data({mr_re,mr_im}),.mode(0));
 integer total,acq_fd,acq_total,out_fd,out_total,checked=0,acquired=0,symbols=0;
 bit scoring=1,tx_run=0;
 `include "oqpsk_bounds_check.svh"
 bpsk_cordic_bounds_check #(.WIDTH(49),.TAG_WIDTH(4),.RESET_ACTIVE(RESET_ACTIVE),.NAME("ACQ")) acq_cordic_bounds
  (.clk(clk),.rst(rst),.scoring(scoring),.ce(receiver.cordic.ce),.s_valid(receiver.cordic.s_valid),
   .s_x(receiver.cordic.s_x),.s_y(receiver.cordic.s_y),.s_tag(receiver.cordic.s_tag),
   .m_valid(receiver.cordic.m_valid),.m_tag(receiver.cordic.m_tag),.m_phase(receiver.cordic.m_phase),
   .valid_pipe(receiver.cordic.valid_pipe),.zero_pipe(receiver.cordic.zero_pipe),
   .x(receiver.cordic.x),.y(receiver.cordic.y),.angle(receiver.cordic.angle),.tag_pipe(receiver.cordic.tag_pipe));
 bpsk_cordic_bounds_check #(.WIDTH(20),.TAG_WIDTH(5),.RESET_ACTIVE(RESET_ACTIVE),.NAME("LOOP")) loop_cordic_bounds
  (.clk(clk),.rst(rst),.scoring(scoring),.ce(receiver.costas.cordic.ce),.s_valid(receiver.costas.cordic.s_valid),
   .s_x(receiver.costas.cordic.s_x),.s_y(receiver.costas.cordic.s_y),.s_tag(receiver.costas.cordic.s_tag),
   .m_valid(receiver.costas.cordic.m_valid),.m_tag(receiver.costas.cordic.m_tag),.m_phase(receiver.costas.cordic.m_phase),
   .valid_pipe(receiver.costas.cordic.valid_pipe),.zero_pipe(receiver.costas.cordic.zero_pipe),
   .x(receiver.costas.cordic.x),.y(receiver.costas.cordic.y),.angle(receiver.costas.cordic.angle),.tag_pipe(receiver.costas.cordic.tag_pipe));
 bpsk_divide_bounds_check #(.RESET_ACTIVE(RESET_ACTIVE)) acquisition_divider_bounds
  (.clk(clk),.rst(rst),.scoring(scoring),.start(receiver.divider.start),.busy(receiver.divider.busy),.done(receiver.divider.done),
   .numerator(receiver.divider.numerator),.denominator(receiver.divider.denominator),.result(receiver.divider.result),
   .divisor(receiver.divider.divisor),.remainder(receiver.divider.remainder),.step(receiver.divider.step),
   .finish_round(receiver.divider.finish_round),.finish_sign(receiver.divider.finish_sign));
 int nonpositive_fraction_checks=0;
 bit fraction_bypass_pending=0;
 always @(posedge clk)begin
  if(rst==RESET_ACTIVE)begin nonpositive_fraction_checks=0;fraction_bypass_pending=0;end
  else begin
   if(fraction_bypass_pending)begin
    if(receiver.state!=receiver.PASS2_SEND||receiver.divider_start)
      $fatal(1,"[NESTED_BOUNDS] nonpositive fraction did not bypass divider");
    fraction_bypass_pending=0;
   end
   if(receiver.state==receiver.FRACTION_START&&!receiver.divider_busy&&!receiver.use_fraction
      &&receiver.fraction_denominator<=0)begin
    fraction_bypass_pending=1;if(scoring)nonpositive_fraction_checks++;
   end
  end
 end
 bpsk_fir_bounds_check #(.RESET_ACTIVE(RESET_ACTIVE),.NAME("OQTX")) tx_fir_bounds
  (.clk(clk),.rst(rst),.scoring(scoring),.ce(dut.filter.ce),
   .s_valid(dut.filter.s_valid),.s_first(dut.filter.s_first),.s_last(dut.filter.s_last),
   .s_re(dut.filter.s_re),.s_im(dut.filter.s_im),.history_count(dut.filter.history_count),
   .valid_pipe(dut.filter.valid_pipe),.last_pipe(dut.filter.last_pipe),
   .m_valid(dut.filter.m_valid),.m_last(dut.filter.m_last),
   .history_re(dut.filter.real_axis.history),.history_im(dut.filter.g_complex.imag_axis.history));
 bpsk_fir_bounds_check #(.RESET_ACTIVE(RESET_ACTIVE),.NAME("OQRX")) rx_fir_bounds
  (.clk(clk),.rst(rst),.scoring(scoring),.ce(receiver.filter.ce),
   .s_valid(receiver.filter.s_valid),.s_first(receiver.filter.s_first),.s_last(receiver.filter.s_last),
   .s_re(receiver.filter.s_re),.s_im(receiver.filter.s_im),.history_count(receiver.filter.history_count),
   .valid_pipe(receiver.filter.valid_pipe),.last_pipe(receiver.filter.last_pipe),
   .m_valid(receiver.filter.m_valid),.m_last(receiver.filter.m_last),
   .history_re(receiver.filter.real_axis.history),.history_im(receiver.filter.g_complex.imag_axis.history));
 int mid_reset,out_reset,cfg_reset,warm_out=0;
 int tx_lab[],tx_lst[];
 longint cycle=0;
 always @(posedge clk) cycle<=cycle+1;
 always @(negedge clk) if(stall_out) begin tm_ready<=$urandom%3!=0;mr_ready<=$urandom%3!=0;end
 // Transmitter scoreboard: every accepted sample must equal the model exactly.
 always @(posedge clk) if(rst!=RESET_ACTIVE) begin
  if(scoring&&m_valid&&tm_ready) begin
   integer re,im,last;
   rc=$fscanf(fd,"%d %d %d",re,im,last);
   if(m_re!==18'(re)||m_im!==18'(im)||m_last!==1'(last)) begin
    $display("MISMATCH tx sample %0d: %0d,%0d/%0d,%0d last %0d/%0d",checked,m_re,m_im,re,im,m_last,last);
    $fatal(1,"[NUMERIC] transmitter output");
   end
   checked=checked+1;
  end
 end
 // Receiver scoreboards: acquisitions and data symbols are bit-exact.
 always @(posedge clk) if(rst!=RESET_ACTIVE) begin
  if(scoring&&acq_valid) begin
   longint delay,frequency,phase;
   rc=$fscanf(acq_fd,"%d %d %d",delay,frequency,phase);
   if(inject&&acquired==0) delay=delay+1;
   if(acq_delay!==32'(delay)||acq_frequency!==32'(frequency)||acq_phase!==32'(phase)) begin
    $display("MISMATCH acquisition %0d: delay %0d/%0d frequency %0d/%0d phase %0d/%0d",
     acquired,acq_delay,delay,acq_frequency,frequency,acq_phase,phase);
    $fatal(1,"[NUMERIC] acquisition");
   end
   acquired=acquired+1;
  end
  if(scoring&&mr_valid&&mr_ready) begin
   integer re,im,label,last;
   rc=$fscanf(out_fd,"%d %d %d %d",re,im,label,last);
   if(inject_symbol&&symbols==0) re=re+1;
   if(mr_re!==18'(re)||mr_im!==18'(im)||mr_label!==2'(label)||mr_last!==1'(last)) begin
    $display("MISMATCH rx symbol %0d: %0d,%0d/%0d,%0d label %0d/%0d last %0d/%0d",
     symbols,mr_re,mr_im,re,im,mr_label,label,mr_last,last);
    $fatal(1,"[NUMERIC] receiver output");
   end
   symbols=symbols+1;
  end
 end
 // +TRACE: times of acquisitions and frame ends.
 always @(posedge clk) if($test$plusargs("TRACE")&&rst!=RESET_ACTIVE) begin
  if(acq_valid) $display("TRACE acquisition %0d at cycle %0d",acquired,cycle);
 end
 // +OUT_RESET: count the accepted outputs (or acquisitions) delivered while nothing is scored yet.
 always @(posedge clk) if(rst!=RESET_ACTIVE&&!scoring&&((m_valid&&tm_ready)||(mr_valid&&mr_ready)||acq_valid)) warm_out=warm_out+1;
 // Transmitter driver: the whole symbol stream, restarted by tx_run after a mid-frame reset.
 initial begin
  integer bfd,label,last,tx_total;
  wait(rst!=RESET_ACTIVE);
  wait(tx_run);
  bfd=$fopen({directory,"/tx_symbols.txt"},"r");rc=$fscanf(bfd,"%d",tx_total);
  for(integer j=0;j<tx_total;j=j+1) begin
   rc=$fscanf(bfd,"%d %d",label,last);
   @(negedge clk);s_valid=1;s_bit=2'(label);s_last=1'(last);
   do @(posedge clk); while(!s_ready);
  end
  @(negedge clk);s_valid=0;
 end
 // Receiver driver: configuration from the preamble, then the channel frames.
 // The whole receiver configuration: 192 preamble labels, cfg_last on the last one.
 task automatic configure;
  integer pfd,n,label;
  pfd=$fopen({directory,"/preamble.txt"},"r");rc=$fscanf(pfd,"%d",n);
  for(integer j=0;j<192;j=j+1) begin
   rc=$fscanf(pfd,"%d",label);
   @(negedge clk);cfg_valid=1;cfg_label=2'(label);cfg_last=j==191;
   do @(posedge clk); while(!cfg_ready);
  end
  @(negedge clk);cfg_valid=0;cfg_last=0;
  @(negedge clk);if(!configured||error) $fatal(1,"Receiver did not accept the configuration");
  $fclose(pfd);
 endtask
 initial begin
  integer vfd,n,re,im,last,blocked,tfd,tn,pfd,pn,label,n0,n1,feed,guard;
  stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
  inject=$test$plusargs("INJECT_MISMATCH");inject_symbol=$test$plusargs("INJECT_SYMBOL");
  mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
  cfg_reset=$test$plusargs("CFG_RESET");
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
  fd=$fopen({directory,"/tx_out.txt"},"r");rc=$fscanf(fd,"%d",total);
  acq_fd=$fopen({directory,"/rx_acquire.txt"},"r");rc=$fscanf(acq_fd,"%d",acq_total);
  out_fd=$fopen({directory,"/rx_out.txt"},"r");rc=$fscanf(out_fd,"%d",out_total);
  repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
  if(!(mid_reset||out_reset||cfg_reset)) tx_run=1; // as usual the transmitter starts right away
  if(!cfg_reset) configure;
  if(mid_reset||out_reset||cfg_reset) begin
   scoring=0;
   if(cfg_reset) begin
    // C = 192 cfg transfers: drive the first C/2 of them (cfg_last stays low), reset right after
    pfd=$fopen({directory,"/preamble.txt"},"r");rc=$fscanf(pfd,"%d",pn);
    for(integer j=0;j<192/2;j=j+1) begin
     rc=$fscanf(pfd,"%d",label);
     @(negedge clk);cfg_valid=1;cfg_label=2'(label);cfg_last=0;
     do @(posedge clk); while(!cfg_ready);
    end
    $fclose(pfd);
    if(configured) $fatal(1,"[CFG_RESET] already configured");
   end else begin
   // half of the first transmitter transaction (n0 = its length = index of the first last flag plus one), never its last sample
   tfd=$fopen({directory,"/tx_symbols.txt"},"r");rc=$fscanf(tfd,"%d",tn);
   tx_lab=new[tn];tx_lst=new[tn];n0=-1;
   for(integer j=0;j<tn;j=j+1) begin
    rc=$fscanf(tfd,"%d %d",tx_lab[j],tx_lst[j]);
    if(n0<0&&tx_lst[j]) n0=j+1;
   end
   $fclose(tfd);
   if(n0<0) n0=tn;
   if(out_reset) begin
    // the WHOLE first transmitter frame (with its real last flag) ...
    for(integer j=0;j<n0;j=j+1) begin
     @(negedge clk);s_valid=1;s_bit=2'(tx_lab[j]);s_last=1'(tx_lst[j]);
     do @(posedge clk); while(!s_ready);
    end
    @(negedge clk);s_valid=0;s_last=0;
    // ... then the receiver wave frame after frame until something comes out (a tx output counts too)
    tfd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(tfd,"%d",tn);
    feed=1;guard=0;
    while(warm_out==0&&guard<200000) begin
     if(feed&&$fscanf(tfd,"%d %d %d",re,im,last)!=3) feed=0;
     if(feed) begin
      @(negedge clk);v_valid=1;v_re=18'(re);v_im=18'(im);v_last=1'(last);
      do begin @(posedge clk);guard=guard+1; end while(!v_ready&&guard<200000);
     end else begin @(negedge clk);guard=guard+1; end
    end
    $fclose(tfd);
    if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
   end else begin
   for(integer j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) begin
    @(negedge clk);s_valid=1;s_bit=2'(tx_lab[j]);s_last=0;
    do @(posedge clk); while(!s_ready);
   end
   // the same half transaction on the receiver wave (n1 = its length)
   tfd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(tfd,"%d",tn);
   n1=-1;
   for(integer j=0;j<tn;j=j+1) begin
    rc=$fscanf(tfd,"%d %d %d",re,im,last);
    if(n1<0&&last) n1=j+1;
   end
   if(n1<0) n1=tn;
   rc=$fseek(tfd,0,0);rc=$fscanf(tfd,"%d",tn);
   for(integer j=0;j<((n1/2>0)?n1/2:1)&&j<n1-1;j=j+1) begin
    rc=$fscanf(tfd,"%d %d %d",re,im,last);
    @(negedge clk);v_valid=1;v_re=18'(re);v_im=18'(im);v_last=0;
    do @(posedge clk); while(!v_ready);
   end
   $fclose(tfd);
   end
   end
   @(negedge clk);cfg_valid=0;cfg_last=0;s_valid=0;s_last=0;v_valid=0;v_last=0;rst=RESET_ACTIVE;
   repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
   @(negedge clk);
   if(m_valid!==1'b0||mr_valid!==1'b0||acq_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
   if(configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
   if(error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
   repeat(2) @(negedge clk);
   scoring=1;
   tx_run=1; // the transmitter replays its whole stream from the first symbol
   configure; // the full configuration from the start, then the frames as usual
  end
  vfd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(vfd,"%d",n);blocked=0;
  for(integer j=0;j<n;j=j+1) begin
   rc=$fscanf(vfd,"%d %d %d",re,im,last);
   if(stall_in&&($urandom%8)==0) begin
    @(negedge clk);v_valid=0;repeat(1+$urandom%3) @(negedge clk);
   end else @(negedge clk);
   v_valid=1;v_re=18'(re);v_im=18'(im);v_last=1'(last);
   blocked=0;
   do begin
    @(posedge clk);
    if(v_ready) break;
    blocked=blocked+1;
    if(!stall_in&&blocked>40)
     $fatal(1,"[THROUGHPUT] receiver input stalled %0d clocks in a row (cycle %0d)",blocked,cycle);
   end while(1);
   blocked=0;
  end
  @(negedge clk);v_valid=0;
  wait(checked==total&&acquired==acq_total&&symbols==out_total);repeat(32) @(negedge clk);
  if(error||symbols!=out_total) $fatal(1,"Receiver error or extra data output");
  if(checked!=total) $fatal(1,"Incomplete transmitter output");
  check_oqpsk_bounds();
  acq_cordic_bounds.check_bounds();loop_cordic_bounds.check_bounds();acquisition_divider_bounds.check_bounds();
  $display("PASS NESTED FRACTION BYPASS: %0d",nonpositive_fraction_checks);
  tx_fir_bounds.check_bounds();rx_fir_bounds.check_bounds();
  $display("PASS OQPSK: %0d symbols, %0d acquisitions, %0d tx samples, %0d cycles",symbols,acquired,checked,cycle);
  $finish;
 end
 initial begin #20000000;$fatal(1,"OQPSK testbench did not drain"); end
endmodule
