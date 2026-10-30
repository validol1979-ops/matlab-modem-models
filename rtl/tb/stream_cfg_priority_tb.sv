// Приоритет повторной конфигурации: удержанный первый отсчёт и численный результат.
`timescale 1ns/1ps
module stream_cfg_priority_tb;
 parameter bit RESET_ACTIVE=1;
 parameter integer FAMILY=0; // 0=Alamouti, 1=beamform, 2=PFB
 parameter MEM_DIR="rtl/common/mem";
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,cv=0,cl=0,sv=0,sl=0,mr=0;
 logic signed [17:0] cf=0,xr=1024,xi=-512;
 wire cr,sr,configured,error,mv,ml;
 wire signed [23:0] yr,yi;
 integer got=0;
 localparam integer NO=FAMILY==2?4:FAMILY==1?1:2;
 generate if(FAMILY==2) begin:g_pfb
  pfb_analysis #(.RESET_ACTIVE(RESET_ACTIVE),.LOG2TMAX(2),.TWIDDLE_FILE({MEM_DIR,"/fft_twiddle_4.mem"})) dut(
   .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_last(cl),.cfg_tap(cf),.cfg_decimation(3'd1),.cfg_ready(cr),.configured(configured),
   .s_valid(sv),.s_last(sl),.s_re(xr),.s_im(xi),.s_ready(sr),
   .m_valid(mv),.m_last(ml),.m_re(yr),.m_im(yi),.m_ready(mr),.error(error));
 end else begin:g_pair
  wire signed [17:0] pr,pi;
  assign yr=24'(pr);assign yi=24'(pi);
  if(FAMILY==1) begin:g_beam
   beamform #(.RESET_ACTIVE(RESET_ACTIVE),.LOG2M(1)) dut(
    .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_last(cl),.cfg_re(cf),.cfg_im(18'd0),.cfg_ready(cr),.configured(configured),
    .s_valid(sv),.s_last(sl),.s_re(xr),.s_im(xi),.s_ready(sr),
    .m_valid(mv),.m_last(ml),.m_re(pr),.m_im(pi),.m_ready(mr),.error(error));
  end else begin:g_alamouti
   alamouti_rx #(.RESET_ACTIVE(RESET_ACTIVE)) dut(
    .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_last(cl),.cfg_re(cf),.cfg_im(18'd0),.cfg_ready(cr),.configured(configured),
    .s_valid(sv),.s_last(sl),.s_re(xr),.s_im(xi),.s_ready(sr),
    .m_valid(mv),.m_last(ml),.m_re(pr),.m_im(pi),.m_ready(mr),.error(error));
  end
 end endgenerate
 always @(posedge clk) begin
  if(rst==RESET_ACTIVE) got=0;
  else begin
   if(error) $fatal(1,"[CONFIG_ARB] Unexpected core error");
   if(mv&&mr) begin
    if(got>=NO||yr!=(FAMILY==2?2048:FAMILY==0&&got==1?2048:1024)+
       (got==0&&$test$plusargs("INJECT_MISMATCH")?1:0)||
       yi!=(FAMILY==2?-1024:FAMILY==0&&got==1?256:-512)||ml!=(got==NO-1))
     $fatal(1,"[NUMERIC] family=%0d output=%0d got=(%0d,%0d,%0b)",FAMILY,got,yr,yi,ml);
    got=got+1;
   end
  end
 end
 task automatic configure(input bit fresh,input integer collision=-1);
  for(integer i=0;i<2;i++) begin
   @(negedge clk);cv=1;cl=i==1;
   cf=fresh?(FAMILY==2?18'sd32768:18'sd16384):(i==0?(FAMILY==2?18'sd65536:18'sd32768):18'sd0);
   if(i==collision) begin
    // Ready не зависит от valid источника данных.
    #1;if(sr) $fatal(1,"[CONFIG_ARB] Ready high on accepted cfg without data valid");
    sv=1;#1;if(sr) $fatal(1,"[CONFIG_ARB] Configuration must exclude held data");
   end
   @(posedge clk);if(!cr) $fatal(1,"[CONFIG_ARB] Empty core rejected configuration");
  end
  @(negedge clk);cv=0;cl=0;
  while(!configured) @(negedge clk);
 endtask
 initial begin
  for(integer collision=0;collision<2;collision++) begin
   rst=RESET_ACTIVE;cv=0;sv=0;mr=0;xr=1024;xi=-512;sl=FAMILY==2;
   repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
   configure(1);configure(0,collision);
   // Первый отсчёт сохранялся на протяжении загрузки и нормировки коэффициентов.
   @(posedge clk);if(!sr) $fatal(1,"[CONFIG_ARB] Held data failed to resume");
   @(negedge clk);sv=0;
   if(FAMILY!=2) begin
    // Непринятое предложение cfg не должно мешать завершению пары/снимка.
    cv=1;cl=0;cf=32768;
    repeat(8) begin
     @(posedge clk);if(cr||!sr) $fatal(1,"[CONFIG_ARB] Busy cfg blocked open transaction");
     @(negedge clk);
    end
    xr=-2048;xi=256;sl=1;sv=1;
    @(posedge clk);if(cr||!sr) $fatal(1,"[CONFIG_ARB] Final input blocked");
    @(negedge clk);sv=0;cv=0;
   end
   wait(mv);repeat(8) @(negedge clk);mr=1;
   wait(got==NO);@(negedge clk);mr=0;
   repeat(16) begin @(posedge clk);if(mv) $fatal(1,"[NUMERIC] Extra output");end
   $display("CFG priority family=%0d collision=%0d outputs=%0d",FAMILY,collision,got);
  end
  $display("PASS STREAM CFG priority family=%0d",FAMILY);$finish;
 end
 initial begin #200000;$fatal(1,"[TIMEOUT] Stream cfg priority");end
endmodule
