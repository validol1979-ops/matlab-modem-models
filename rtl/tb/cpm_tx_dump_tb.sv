// Drives cpm_tx with the bits of +VECTORS/bits.txt (count line, then `bit last` rows) and writes
// every accepted output sample to +VECTORS/rtl_tx.txt (`re im last`); +STALL_OUTPUT randomises
// m_ready. Used by tools/check_msk_matlab_rtl.py to compare the RTL with the MATLAB capture.
`timescale 1ns/1ps
module cpm_tx_dump_tb;
 parameter bit RESET_ACTIVE=1;
 parameter bit GMSK=0;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0,rst=RESET_ACTIVE;
 always #5 clk=!clk;
 logic s_valid=0,s_bit=0,s_last=0,s_ready,m_ready=1,m_valid,m_last;
 logic signed [17:0] m_re,m_im;
 cpm_tx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(GMSK)) dut(clk,rst,s_valid,s_bit,s_last,s_ready,m_ready,m_valid,m_last,m_re,m_im);
 string directory;
 integer bfd,ofd,rc,total,b,l,stall,written=0,done=0;
 always @(negedge clk) if(stall) m_ready<=$urandom%3!=0;
 always @(posedge clk) if(rst!=RESET_ACTIVE&&m_valid&&m_ready) begin
  $fdisplay(ofd,"%0d %0d %0d",m_re,m_im,m_last); written=written+1; if(m_last) done=1;
 end
 initial begin
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
  stall=$test$plusargs("STALL_OUTPUT");
  bfd=$fopen({directory,"/bits.txt"},"r"); rc=$fscanf(bfd,"%d",total);
  ofd=$fopen({directory,"/rtl_tx.txt"},"w");
  repeat(10) @(negedge clk); rst=!RESET_ACTIVE; repeat(3) @(negedge clk);
  for(integer j=0;j<total;j=j+1) begin
   rc=$fscanf(bfd,"%d %d",b,l);
   @(negedge clk); s_valid=1; s_bit=1'(b); s_last=1'(l);
   do @(posedge clk); while(!s_ready);
  end
  @(negedge clk); s_valid=0;
  wait(done); repeat(5) @(negedge clk);
  $fclose(ofd); $display("DUMP CPM TX: %0d samples",written); $finish;
 end
 initial begin #20000000; $fatal(1,"cpm_tx dump did not finish"); end
endmodule
