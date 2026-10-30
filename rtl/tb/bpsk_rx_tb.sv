`timescale 1ns/1ps
module bpsk_rx_tb;
 import uvm_pkg::*;
 `include "uvm_macros.svh"
 parameter bit RESET_ACTIVE=1,LOOPBACK=0;
 // SIMO=1: simo_rx (two branches, known gains from gains.txt) with ORDER=4, DIFFERENTIAL=1.
 parameter bit SIMO=0;
 parameter integer SYMBOLS=768;
 parameter integer ORDER=2;
 parameter integer AMPLITUDE=ORDER==8?32768:ORDER==4?23170:16384;
 parameter bit DIFFERENTIAL=ORDER==2,TX_AXIS=0,FEEDFORWARD=0,TIMING_LOOP=1;
 parameter bit PI4=0;
 // EQUALIZER (ORDER=16): 1 = NLMS, 2 = DFE.
 parameter integer EQUALIZER=0;
 // BITS: label width (2 for pi/4-QPSK); INDEX_BITS: table index width.
 localparam integer BITS=ORDER==64?6:ORDER==16?4:ORDER==8?(PI4?2:3):ORDER==4?2:1,INDEX_BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0;always #5 clk=~clk;
 logic [11:0] cfg_count=12'(SYMBOLS);
 logic rst=RESET_ACTIVE,cv=0,cl=0,sv=0,sl=0,mr=1;
 logic [BITS-1:0] cb=0;
 logic signed [17:0] sr=0,si=0,sr2=0,si2=0;
 logic gv=0;
 logic signed [17:0] gain_cfg[0:3];
 logic [15:0] variance_cfg[0:1];
 wire gain_ready,gain_configured,gain_error,saturated;
 wire cr,configured,error,ready,rx_ready,tx_ready,tx_valid,tx_last,mv,ml,av,confidence;
 wire [BITS-1:0] mb;
 wire [INDEX_BITS-1:0] mi;
 wire signed [17:0] re,im,tx_re,tx_im;
 assign ready=LOOPBACK?tx_ready:rx_ready;
 bpsk_tx #(.RESET_ACTIVE(RESET_ACTIVE),.ORDER(ORDER),.AMPLITUDE(AMPLITUDE),.DIFFERENTIAL(DIFFERENTIAL),.TX_AXIS(TX_AXIS),.PI4(PI4)) transmitter(clk,rst,sv&&LOOPBACK,sr[BITS-1:0],sl,tx_ready,rx_ready,tx_valid,tx_last,tx_re,tx_im);
 wire signed [31:0] phase,freq,correction,ad,af,ap;
 wire [24:0] gain,ag;
 wire [63:0] score;
 generate
 if(SIMO) begin:g_simo
  simo_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
   .clk(clk),.rst(rst),.gain_valid(gv),.gain_a_re(gain_cfg[0]),.gain_a_im(gain_cfg[1]),.gain_b_re(gain_cfg[2]),.gain_b_im(gain_cfg[3]),
   .variance_a(variance_cfg[0]),.variance_b(variance_cfg[1]),.gain_ready(gain_ready),.gain_configured(gain_configured),.gain_error(gain_error),.saturated(saturated),
   .cfg_valid(cv),.cfg_bit(2'(cb)),.cfg_last(cl),.cfg_count(cfg_count),.cfg_ready(cr),.configured(configured),.error(error),
   .s_valid(LOOPBACK?tx_valid:sv),.s_last(LOOPBACK?tx_last:sl),.s_a_re(LOOPBACK?tx_re:sr),.s_a_im(LOOPBACK?tx_im:si),
   .s_b_re(LOOPBACK?tx_re:sr2),.s_b_im(LOOPBACK?tx_im:si2),.s_ready(rx_ready),
   .m_valid(mv),.m_last(ml),.m_bit(mb),.m_index(mi),.m_ready(mr),.m_re(re),.m_im(im),.m_phase(phase),.m_frequency(freq),.m_correction(correction),.m_gain(gain),
   .acquisition_valid(av),.acquisition_confidence(confidence),.acquisition_delay(ad),.acquisition_frequency(af),.acquisition_phase(ap),.acquisition_gain(ag),.acquisition_score(score));
 end else begin:g_single
  bpsk_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(ORDER),.AMPLITUDE(AMPLITUDE),.DIFFERENTIAL(DIFFERENTIAL),
   .FEEDFORWARD(FEEDFORWARD),.TIMING_LOOP(TIMING_LOOP),.PI4(PI4),.EQUALIZER(EQUALIZER)) dut(
   clk,rst,cv,cb,cl,cfg_count,cr,configured,error,LOOPBACK?tx_valid:sv,LOOPBACK?tx_last:sl,LOOPBACK?tx_re:sr,LOOPBACK?tx_im:si,rx_ready,mv,ml,mb,mi,mr,re,im,phase,freq,correction,gain,av,confidence,ad,af,ap,ag,score,1'b1);
  assign gain_ready=1'b0;assign gain_configured=1'b0;assign gain_error=1'b0;assign saturated=1'b0;
 end
 endgenerate
 // A: фронт принятия start до фронта наблюдения done родителем.
 wire acq_start_probe,acq_done_probe;
 generate
 if(SIMO) begin:g_acq_simo_probe
  assign acq_start_probe=g_simo.dut.receiver.acquisition_start;
  assign acq_done_probe=g_simo.dut.receiver.acquisition_done;
 end else begin:g_acq_single_probe
  assign acq_start_probe=g_single.dut.acquisition_start;
  assign acq_done_probe=g_single.dut.acquisition_done;
 end
 endgenerate
 integer acq_start_cycle=-1,acq_measure_cycle=0;
 always @(posedge clk) begin
  acq_measure_cycle=acq_measure_cycle+1;
  if(rst==RESET_ACTIVE) acq_start_cycle=-1;
  else begin
   if(acq_start_probe) acq_start_cycle=acq_measure_cycle;
   if(acq_done_probe) begin
    if(acq_start_cycle<0) $fatal(1,"[ACQUISITION] done without start");
    $display("RX ACQUISITION start=%0d done=%0d A=%0d",acq_start_cycle,acq_measure_cycle,acq_measure_cycle-acq_start_cycle);
    acq_start_cycle=-1;
   end
  end
 end
 longint signed expected[0:19999][0:9],acq[0:31][0:5];
 integer checked=0,acquired=0,ntrace,nacq,rc,fd,nwave,payload_errors=0,cycle=0,blocked=0,boundary_cycles=0;
 integer ser_frames=0,frame_payload_errors=0,frame_payload_symbols=0;
 bit ser_recording=1;
 bit inject=0,stall_mode=0,allow_error=0;
 string directory;
 integer random_state=891;
 always @(negedge clk) if(stall_mode) begin random_state=random_state*1664525+1013904223;mr=(random_state&7)!=0;end
 always @(posedge clk) begin
  cycle=cycle+1;
  if(rst!=RESET_ACTIVE) begin
   if(error&&!allow_error) `uvm_fatal("PROTOCOL","Unexpected receiver error")
   if(gain_error||saturated) `uvm_fatal("PROTOCOL","Unexpected combiner error or saturation")
   if(av) begin
    if(acquired>=nacq) `uvm_fatal("NUMERIC","Unexpected acquisition")
    if(64'(ad)!==acq[acquired][0]||64'(af)!==acq[acquired][1]||64'(ap)!==acq[acquired][2]||64'(ag)!==acq[acquired][3]||score!==acq[acquired][4]||64'(confidence)!==acq[acquired][5])
     `uvm_fatal("NUMERIC",$sformatf("acquisition frame=%0d got d=%0d f=%0d p=%0d g=%0d score=%0d expected d=%0d f=%0d p=%0d g=%0d score=%0d",acquired,ad,af,ap,ag,score,acq[acquired][0],acq[acquired][1],acq[acquired][2],acq[acquired][3],acq[acquired][4]))
    acquired=acquired+1;
   end
   if(mv&&mr) begin
    if(checked>=ntrace) `uvm_fatal("NUMERIC","Unexpected decoded symbol")
    if(64'(re)!==(expected[checked][0]+longint'(inject&&checked==200))||64'(im)!==expected[checked][1]||64'(phase)!==expected[checked][2]||64'(freq)!==expected[checked][3]||64'(gain)!==expected[checked][4]||64'(correction)!==expected[checked][5]||64'(mi)!==expected[checked][6]||64'(mb)!==expected[checked][7]||64'(ml)!==expected[checked][8])
     `uvm_fatal("NUMERIC",$sformatf("symbol=%0d got I=%0d Q=%0d phase=%0d freq=%0d gain=%0d corr=%0d idx=%0d bit=%0d last=%0d; expected I=%0d Q=%0d phase=%0d freq=%0d gain=%0d corr=%0d idx=%0d bit=%0d last=%0d",checked,re,im,phase,freq,gain,correction,mi,mb,ml,expected[checked][0],expected[checked][1],expected[checked][2],expected[checked][3],expected[checked][4],expected[checked][5],expected[checked][6],expected[checked][7],expected[checked][8]))
    // Column 7 is the fixed decoded label (numeric scoreboard above). Column 9
    // is the ORIGINAL transmitted label; count raw actual-DUT payload errors.
    if(checked%int'(cfg_count)>=192) begin
     frame_payload_symbols++;
     if(64'(mb)!=expected[checked][9]) begin payload_errors++;frame_payload_errors++;end
    end
    if(ml) begin
     if(frame_payload_symbols!=int'(cfg_count)-192) `uvm_fatal("SER","Payload denominator disagrees with frame length")
     if(ser_recording) $display("RTL PAYLOAD SER frame=%0d errors=%0d symbols=%0d",ser_frames,frame_payload_errors,frame_payload_symbols);
     ser_frames++;frame_payload_errors=0;frame_payload_symbols=0;
    end
    checked=checked+1;
   end
  end
 end
 property output_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) mv&&!mr |=> mv&&$stable({re,im,phase,freq,gain,correction,mi,mb,ml});endproperty
 assert property(output_hold) else `uvm_fatal("STALL","Receiver output changed under backpressure")
 property source_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) sv&&!ready |=> sv&&$stable({sl,sr,si,sr2,si2});endproperty
 assert property(source_hold) else `uvm_fatal("STALL","Source changed a blocked input")
 wire [2:0] review_occupied;
 wire [1:0] review_capture;
 wire [1:0] review_next,review_process;
 wire [5:0] review_tail;
 wire review_active,review_first;
 integer review_short_frames=0;
 task automatic configure_receiver(input integer collision=-1);
  integer cfgfd,total,read_count,wait_count;
  longint signed bit_value,g[0:5];
  if(SIMO) begin
   cfgfd=$fopen({directory,"/gains.txt"},"r");read_count=$fscanf(cfgfd,"%d",total);
   for(integer k=0;k<6;k=k+1) read_count=$fscanf(cfgfd,"%d",g[k]);$fclose(cfgfd);
   for(integer k=0;k<4;k=k+1) gain_cfg[k]=18'(g[k]);
   variance_cfg[0]=16'(g[4]);variance_cfg[1]=16'(g[5]);
   @(negedge clk);if(!gain_ready) `uvm_fatal("CONFIG","Combiner configuration backpressured while idle")
   gv=1;@(negedge clk);gv=0;wait_count=0;
   while(!gain_configured) begin @(negedge clk);wait_count=wait_count+1;if(gain_error||wait_count>400) `uvm_fatal("CONFIG","Combiner weights failed") end
  end
  cfgfd=$fopen({directory,"/preamble.txt"},"r");read_count=$fscanf(cfgfd,"%d",total);
  for(integer j=0;j<total;j=j+1) begin
   @(negedge clk);cv=1;read_count=$fscanf(cfgfd,"%d",bit_value);cb=BITS'(bit_value);cl=j==total-1;
   if(collision==j) begin
    if(LOOPBACK) `uvm_fatal("CONFIG_ARB","Collision test requires waveform input")
    fd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(fd,"%d",nwave);
    read_sample();sv=1;
   end
   @(posedge clk);
   if(!cr) `uvm_fatal("CONFIG","Configuration backpressured while idle")
   if(sv&&rx_ready) `uvm_fatal("CONFIG_ARB","Data accepted with configuration")
  end
  @(negedge clk);cv=0;cl=0;$fclose(cfgfd);
  if(!configured) `uvm_fatal("CONFIG","Training did not configure")
  if(collision>=0) begin
   @(posedge clk);
   if(!rx_ready) `uvm_fatal("CONFIG_ARB","Held first sample did not resume")
   @(negedge clk);sv=0;
   $display("BPSK RX cfg collision index=%0d accepted_cfg=192 blocked_data=%0d",collision,192-collision);
  end
 endtask
 task automatic read_sample;
  longint signed a,b,c,d,e;
  if(SIMO&&!LOOPBACK) begin rc=$fscanf(fd,"%d %d %d %d %d",a,b,c,d,e);sr=18'(a);si=18'(b);sr2=18'(c);si2=18'(d);sl=1'(e);end
  else begin rc=$fscanf(fd,"%d %d %d",a,b,c);sr=18'(a);si=18'(b);sl=1'(c);end
 endtask

 task automatic load_reference;
  checked=0;acquired=0;payload_errors=0;ser_frames=0;frame_payload_errors=0;frame_payload_symbols=0;
  fd=$fopen({directory,"/rx_trace.txt"},"r");rc=$fscanf(fd,"%d",ntrace);
  for(integer j=0;j<ntrace;j=j+1) for(integer k=0;k<10;k=k+1) rc=$fscanf(fd,"%d",expected[j][k]);$fclose(fd);
  fd=$fopen({directory,"/rx_acquire.txt"},"r");rc=$fscanf(fd,"%d",nacq);
  for(integer j=0;j<nacq;j=j+1) for(integer k=0;k<6;k=k+1) rc=$fscanf(fd,"%d",acq[j][k]);$fclose(fd);
 endtask
 task automatic directed_wave(input integer reset_mode=0,input bit skip_first=0,input integer max_frames=0);
  integer frame_inputs,part;
  frame_inputs=0;part=0;
  if(!skip_first) begin fd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(fd,"%d",nwave);end
  for(integer j=int'(skip_first);j<nwave;j++) begin
   @(negedge clk);sv=1;read_sample();
   do @(posedge clk);while(!rx_ready);
   part++;
   if(sl) begin frame_inputs++;part=0;end
   if(max_frames!=0&&frame_inputs==max_frames) break;
   if((reset_mode==1&&frame_inputs==2&&part==100)||(reset_mode==2&&frame_inputs==3)) break;
  end
  @(negedge clk);sv=0;sl=0;$fclose(fd);
  if(reset_mode!=0) begin
   if(reset_mode==2) repeat(5) @(negedge clk);
   if(SIMO) `uvm_fatal("RESET","Short bank test requires direct RX")
   if(review_capture!=2||!review_occupied[2]||!review_active||
      (reset_mode==2&&review_tail==0)) `uvm_fatal("RESET","Reset missed short capture/tail")
   rst=RESET_ACTIVE;repeat(4) @(negedge clk);
   if(mv||configured||error||review_occupied!=0) `uvm_fatal("RESET","Short bank reset did not clear state")
   rst=!RESET_ACTIVE;
   $display("BPSK RX short reset mode=%0d",reset_mode);
  end else begin
   wait(checked==(max_frames!=0?max_frames*int'(cfg_count):ntrace)&&acquired==(max_frames!=0?max_frames:nacq)&&cr);repeat(4) @(negedge clk);
   if(review_short_frames!=(cfg_count<=244&&max_frames!=2?1:0))
    `uvm_fatal("BUFFER","Numeric epoch did not use the expected short bank")
   $display("BPSK RX review epoch N=%0d symbols=%0d acquisitions=%0d short_frames=%0d",cfg_count,checked,acquired,review_short_frames);
  end
 endtask
 // Observe reservation as well as numeric outputs, so a recovery test cannot
 // accidentally pass using only the two full banks.
 generate if(!SIMO) begin:g_review_observe
  assign review_occupied=g_single.dut.occupied;
  assign review_capture=g_single.dut.capture_frame;
  assign review_tail=g_single.dut.tail;
  assign review_active=g_single.dut.capture_active;
  assign review_first=g_single.dut.first&&g_single.dut.input_frame==2;
  assign review_next=g_single.dut.next_capture;assign review_process=g_single.dut.process_frame;
 end else begin:g_review_simo
  assign review_occupied=g_simo.dut.receiver.occupied;
  assign review_capture=g_simo.dut.receiver.capture_frame;
  assign review_tail=g_simo.dut.receiver.tail;
  assign review_active=g_simo.dut.receiver.capture_active;
  assign review_first=g_simo.dut.receiver.first&&g_simo.dut.receiver.input_frame==2;
  assign review_next=g_simo.dut.receiver.next_capture;assign review_process=g_simo.dut.receiver.process_frame;
 end endgenerate
 always @(posedge clk) begin
  if(rst==RESET_ACTIVE||cv&&cr&&cl) review_short_frames=0;
  else if(review_first) review_short_frames++;
 end
 initial begin:tests
  integer collision;string review_root;
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"Missing VECTORS");
  if($test$plusargs("SHORT_RECOVERY")) begin review_root=directory;directory={review_root,"/epoch0"};end
  inject=$test$plusargs("INJECT_MISMATCH");stall_mode=$test$plusargs("STALL_OUTPUT");
  load_reference();
  repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
  if($test$plusargs("SHORT_RECOVERY")) begin
   for(integer epoch=0;epoch<7;epoch++) begin
    directory=$sformatf("%s/epoch%0d",review_root,epoch);
    cfg_count=12'((epoch==3||epoch==5)?245:244);
    // The negative run must reach recovery from both resets before corruption.
    inject=$test$plusargs("INJECT_MISMATCH")&&epoch==2;
    load_reference();configure_receiver();directed_wave();
    if(epoch==0||epoch==1) begin
     // Dirty the short RAM again, then abort capture or its FIR tail.
     load_reference();configure_receiver();directed_wave(epoch==0?1:2);
    end
   end
   $display("PASS BPSK RX short recovery: 7 epochs, 21 frames, 5130 symbols, 21 acquisitions");$finish;
  end
  if($value$plusargs("CFG_COLLISION=%d",collision)) begin
   if(collision!=0&&collision!=191) `uvm_fatal("CONFIG_ARB","Unsupported collision index")
   // Already configured and empty: the old bug is invisible immediately after reset.
   configure_receiver();directed_wave(0,0,2);
   if(review_next!=2||review_process!=2||review_occupied!=0)
    `uvm_fatal("CONFIG_ARB","Collision did not start at empty short ring position")
   load_reference();configure_receiver(collision);directed_wave(0,1);
   $display("PASS BPSK RX cfg arbitration index=%0d symbols=%0d acquisitions=%0d",collision,checked,acquired);$finish;
  end
  if($test$plusargs("PROTOCOL_ONLY")) begin
   allow_error=1;
   // Incomplete preamble must neither configure nor accept samples.
   @(negedge clk);cv=1;cb=0;cl=1;
   @(negedge clk);cv=0;cl=0;
   if(configured||!error||ready) `uvm_fatal("PROTOCOL","Incomplete training was accepted")
   rst=RESET_ACTIVE;repeat(4) @(negedge clk);rst=!RESET_ACTIVE;configure_receiver();
   // A truncated packet is discarded before acquisition and requires reset.
   for(integer j=0;j<100;j=j+1) begin @(negedge clk);sv=1;sl=j==99;sr=0;si=0;end
   @(negedge clk);sv=0;sl=0;repeat(200) @(negedge clk);
   if(!error||mv||ready) `uvm_fatal("PROTOCOL","Truncated frame did not reject correctly")
   rst=RESET_ACTIVE;repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
   if(error||mv||configured) `uvm_fatal("RESET","Reset did not clear invalid frame/configuration")
   $display("PASS BPSK protocol guards");$finish;
  end
  configure_receiver();
  if($test$plusargs("RESET_MID_FRAME")) begin
   ser_recording=0;
   fd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(fd,"%d",nwave);
   for(integer j=0;j<3600;j=j+1) begin
    @(negedge clk);sv=1;read_sample();
    @(posedge clk);if(!ready) `uvm_fatal("RESET","Unexpected input stall during partial frame")
   end
   @(negedge clk);sv=0;stall_mode=0;mr=0;repeat(30) @(negedge clk);
   if(!mv) `uvm_fatal("RESET","Reset scenario never filled the output pipeline")
   rst=RESET_ACTIVE;repeat(4) @(negedge clk);
   if(mv) `uvm_fatal("RESET","Reset did not discard pending outputs")
   $display("Discarded partial BPSK frame on reset after %0d decoded symbols",checked);
   checked=0;acquired=0;payload_errors=0;ser_frames=0;frame_payload_errors=0;frame_payload_symbols=0;
   ser_recording=1;blocked=0;boundary_cycles=0;rst=!RESET_ACTIVE;mr=1;$fclose(fd);
   configure_receiver();
  end
  fd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(fd,"%d",nwave);
  for(integer j=0;j<nwave;j=j+1) begin
   @(negedge clk);sv=1;read_sample();
   do begin
    @(posedge clk);
    if(ready) break;
    blocked=blocked+1;
    if(!LOOPBACK&&!stall_mode&&boundary_cycles>=32) `uvm_fatal("THROUGHPUT","Input stalled beyond the 32 matched-filter tail clocks")
    boundary_cycles=boundary_cycles+1;
   end while(1);
   if(sl) boundary_cycles=0;
  end
  @(negedge clk);sv=0;$fclose(fd);wait(checked==ntrace);repeat(50) @(negedge clk);
  if(frame_payload_symbols!=0||ser_frames!=nacq) `uvm_fatal("SER","Incomplete per-frame SER evidence")
  $display("PASS BPSK receiver: %0d symbols, %0d acquisitions, %0d payload errors, %0d input wait clocks, %0d cycles",checked,acquired,payload_errors,blocked,cycle);$finish;
 end
 initial begin #10000000;`uvm_fatal("TIMEOUT","BPSK receiver did not drain") end
endmodule
