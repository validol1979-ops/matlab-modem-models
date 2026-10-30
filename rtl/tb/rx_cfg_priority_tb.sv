// Pin-level arbitration checks for the other buffered receivers of this family.
`timescale 1ns/1ps
module rx_cfg_priority_tb;
 parameter bit RESET_ACTIVE=1;
 parameter integer FAMILY=0; // 0=MSK, 1=GMSK, 2=OQPSK
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,cv=0,cl=0,sv=0;
 wire cr,sr,configured,error;
 wire unused_mv,unused_ml,unused_av;
 wire [1:0] unused_label;
 wire signed [35:0] unused_value;
 wire signed [17:0] unused_re,unused_im;
 wire signed [31:0] unused_delay,unused_freq,unused_phase;
 generate if(FAMILY==2) begin:g_oqpsk
  oqpsk_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
   .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_last(cl),.cfg_label(2'd0),.cfg_count(12'd244),.cfg_ready(cr),.configured(configured),.error(error),
   .s_valid(sv),.s_last(1'b0),.s_re(18'sd1234),.s_im(-18'sd567),.s_ready(sr),
   .m_valid(unused_mv),.m_last(unused_ml),.m_label(unused_label),.m_ready(1'b1),.m_re(unused_re),.m_im(unused_im),
   .acquisition_valid(unused_av),.acquisition_delay(unused_delay),.acquisition_frequency(unused_freq),.acquisition_phase(unused_phase));
  assign unused_value=0;
 end else begin:g_cpm
  cpm_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(FAMILY==1)) dut(
   .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_last(cl),.cfg_bit(1'b0),.cfg_count(12'd244),.cfg_ready(cr),.configured(configured),.error(error),
   .s_valid(sv),.s_last(1'b0),.s_re(18'sd1234),.s_im(-18'sd567),.s_ready(sr),
   .m_valid(unused_mv),.m_last(unused_ml),.m_bit(unused_label[0]),.m_ready(1'b1),.m_value(unused_value),
   .acquisition_valid(unused_av),.acquisition_delay(unused_delay),.acquisition_frequency(unused_freq),.acquisition_phase(unused_phase));
  assign unused_label[1]=0;assign unused_re=0;assign unused_im=0;
 end endgenerate
 task automatic configure(input integer collision=-1);
  for(integer i=0;i<192;i++) begin
   @(negedge clk);cv=1;cl=i==191;if(i==collision) sv=1;
   @(posedge clk);
   if(!cr||sv&&sr) $fatal(1,"[CONFIG_ARB] Configuration must exclude data");
  end
  @(negedge clk);cv=0;cl=0;
  if(!configured||error) $fatal(1,"[CONFIG_ARB] Configuration incomplete");
 endtask
 initial begin
  for(integer index=0;index<2;index++) begin
   rst=RESET_ACTIVE;sv=0;cv=0;cl=0;repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
   configure();configure(index==0?0:191);
   // Keep the held first word unchanged; only accepted cfg may suppress data.
   @(posedge clk);if(!sr) $fatal(1,"[CONFIG_ARB] Held data failed to resume");
   @(negedge clk);cv=1;
   repeat(100) begin
    @(posedge clk);if(cr||!sr||error) $fatal(1,"[CONFIG_ARB] Busy cfg offer blocked open frame");
    @(negedge clk);
   end
   // Reset aborts both offers; no incomplete frame is treated as valid.
   rst=RESET_ACTIVE;sv=0;cv=0;
   $display("RX CFG priority family=%0d index=%0d",FAMILY,index==0?0:191);
  end
  $display("PASS RX family cfg priority family=%0d",FAMILY);$finish;
 end
 initial begin #100000;$fatal(1,"[TIMEOUT] RX cfg priority");end
endmodule
