// Directed buffer safety checks; numeric equivalence is checked by bpsk_rx_rate_tb.
`timescale 1ns/1ps
module bpsk_rx_buffers_tb;
 parameter bit RESET_ACTIVE=1;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,cv=0,cb=0,cl=0,sv=0,sl=0,mr=0;
 logic [11:0] count=0;
 wire cr,configured,error,sr,mv;
 bpsk_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
  .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_bit(cb),.cfg_last(cl),.cfg_count(count),
  .cfg_ready(cr),.configured(configured),.error(error),.s_valid(sv),.s_last(sl),
  .s_re(18'sd0),.s_im(18'sd0),.s_ready(sr),.m_valid(mv),.m_ready(mr),
  .m_last(),.m_bit(),.m_index(),.m_re(),.m_im(),.m_phase(),.m_frequency(),
  .m_correction(),.m_gain(),.acquisition_valid(),.acquisition_confidence(),
  .acquisition_delay(),.acquisition_frequency(),.acquisition_phase(),.acquisition_gain(),.acquisition_score(),.cfg_enable(1'b1));

 always @(negedge clk) if(rst!=RESET_ACTIVE) begin
  if(dut.occupied!=0&&cr) $fatal(1,"[CONFIG] Configuration allowed with occupied buffer");
  if(dut.fv&&(dut.write_frame_ram>2||
     (dut.write_frame_ram==2&&dut.written[2]>=2048)))
   $fatal(1,"[BUFFER] Capture write outside physical short RAM");
 end

 task automatic reset_receiver;
  @(negedge clk);rst=RESET_ACTIVE;cv=0;sv=0;sl=0;cl=0;cb=0;mr=0;
  repeat(4) @(negedge clk);
  if(error||configured||mv||dut.occupied!=0||dut.complete!=0||dut.invalid!=0||
     dut.next_capture!=0||dut.process_frame!=0||dut.written[2]!=0)
   $fatal(1,"[RESET] Buffer state survived reset");
  rst=!RESET_ACTIVE;
 endtask

 task automatic configure(input integer n);
  count=12'(n);
  for(integer j=0;j<192;j++) begin
   @(negedge clk);cv=1;cl=j==191;
   if(!cr) $fatal(1,"[CONFIG] Idle configuration rejected");
  end
  @(negedge clk);cv=0;cl=0;
  @(negedge clk); // Observe ready after the cfg-priority combinational path settles.
  if(!configured||error||dut.next_capture!=0||dut.process_frame!=0)
   $fatal(1,"[CONFIG] Ring not initialized");
 endtask

 task automatic send(input integer n,input bit last);
  for(integer j=0;j<n;j++) begin
   @(negedge clk);sv=1;sl=last&&j==n-1;
   do @(posedge clk);while(!sr);
  end
  @(negedge clk);sv=0;sl=0;
 endtask

 task automatic fill_full_buffers(input integer n);
  send(8*n+64,1);repeat(50) @(negedge clk);
  send(8*n+64,1);repeat(50) @(negedge clk);
  if(error||dut.occupied!=3||dut.next_capture!=(n<=244?2:0))
   $fatal(1,"[BUFFER] Full buffer assignment failed");
 endtask

 task automatic retire_invalid_short;
  // The sticky protocol error stops input, but must not prevent RETIRE.
  mr=1;
  wait(dut.state==3&&dut.process_frame==2&&dut.complete[2]);
  @(negedge clk);
  if(!dut.occupied[2]||!dut.invalid[2])
   $fatal(1,"[RETIRE] Invalid short bank was not exercised");
  @(negedge clk);
  if(dut.occupied[2]||dut.occupied!=0||dut.process_frame!=0||!error||sr)
   $fatal(1,"[RETIRE] Invalid short bank leaked or error cleared");
  $display("BPSK RX invalid short RETIRE written=%0d",dut.written[2]);
  mr=0;
 endtask

 initial begin
  reset_receiver();configure(244);fill_full_buffers(244);
  // Exact fit: 8*244+64+32 = 2048. Output is held, so all three remain occupied.
  send(2016,1);repeat(50) @(negedge clk);
  if(error||dut.occupied!=7||dut.written[2]!=2048||!dut.complete[2]||sr)
   $fatal(1,"[BUFFER] Exact short capacity failed");
  // Illegal configuration traffic must not change N/training with any bank busy.
  cv=1;cb=1;cl=1;count=2048;repeat(4) @(negedge clk);cv=0;cl=0;cb=0;
  if(dut.symbol_count!=244||dut.training!=0||error)
   $fatal(1,"[CONFIG] Busy configuration changed receiver");
  // Drain without reset: the short bank eventually is the ONLY occupied bank.
  mr=1;wait(dut.occupied==4);@(negedge clk);
  if(cr) $fatal(1,"[CONFIG] Short-only occupation ignored");
  cv=1;cl=1;cb=1;repeat(2) @(negedge clk);cv=0;cl=0;cb=0;
  if(dut.symbol_count!=244||dut.training!=0||error)
   $fatal(1,"[CONFIG] Short-only busy configuration changed receiver");
  wait(dut.occupied==0);@(negedge clk);mr=0;
  configure(244);fill_full_buffers(244);
  mr=1;wait(dut.occupied==0);@(negedge clk);mr=0;
  if(dut.next_capture!=2||dut.process_frame!=2)
   $fatal(1,"[CONFIG] Reconfiguration scenario missed the short ring position");
  // Reconfiguration must initialize both pointers before changing eligibility.
  configure(245);fill_full_buffers(245);
  if(dut.occupied[2]||sr||dut.short_enabled)
   $fatal(1,"[BUFFER] Oversize configuration reserved short buffer");
  mr=1;wait(dut.occupied==0);@(negedge clk);mr=0;
  configure(244);fill_full_buffers(244);
  // Missing/late TLAST: stop accepting on sample 2016 and flush only 32 zeros.
  send(2016,0);sv=1;sl=1;repeat(50) @(negedge clk);sv=0;sl=0;
  if(!error||sr||!dut.invalid[2]||dut.written[2]!=2048||!dut.complete[2])
   $fatal(1,"[PROTOCOL] Overlong short frame not rejected safely");
  retire_invalid_short();
  reset_receiver();configure(192);fill_full_buffers(192);
  // TLAST below the configured minimum is the same sticky protocol error.
  send(100,1);repeat(50) @(negedge clk);
  if(!error||sr||!dut.invalid[2]||dut.written[2]!=132)
   $fatal(1,"[PROTOCOL] Truncated short frame not rejected");
  retire_invalid_short();
  reset_receiver();configure(192);fill_full_buffers(192);
  send(100,0);reset_receiver();configure(192);fill_full_buffers(192);
  // Reset while the short frame is draining its FIR tail.
  send(1536,1);repeat(5) @(negedge clk);reset_receiver();configure(192);
  if(dut.occupied!=0||!sr) $fatal(1,"[RESET] Short capture did not recover");
  $display("PASS BPSK RX buffer guards");$finish;
 end
 initial begin #10000000;$fatal(1,"[TIMEOUT] Buffer safety checks did not drain");end
endmodule
