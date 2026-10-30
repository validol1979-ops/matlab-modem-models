// Короткий сигнал не допускает смены nnoise до полного выхода из конвейера.
`timescale 1ns/1ps
module omlsa_cfg_priority_tb;
 parameter bit RESET_ACTIVE=1;
 parameter bit MID_SIGNAL=1;
 parameter MEM_DIR="rtl/common/mem";
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,cv=0,sv=0,sl=0,mr=0;
 logic [4:0] nn=1;
 logic signed [17:0] xr=0,xi=0;
 wire cr,sr,configured,error,mv,ml;
 wire signed [17:0] yr,yi;
 integer got=0,sent=0,cfgs=0,retired=0;
 integer ni,no,fd,rc;
 integer ix[0:161],iy[0:161],il[0:161],ox[0:161],oy[0:161],ol[0:161];
 string data;
 omlsa #(.RESET_ACTIVE(RESET_ACTIVE),.MEM_DIR(MEM_DIR)) dut(
  .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_nnoise(nn),.cfg_alpha(17'd58982),.cfg_ready(cr),.configured(configured),
  .s_valid(sv),.s_last(sl),.s_re(xr),.s_im(xi),.s_ready(sr),
  .m_valid(mv),.m_last(ml),.m_re(yr),.m_im(yi),.m_ready(mr),.error(error));
 always @(posedge clk) begin
  if(rst!=RESET_ACTIVE) begin
   if(error) $fatal(1,"[CONFIG_ARB] Unexpected OM-LSA error");
   // Внешний handshake и запись в pad должны совпадать даже при коллизии.
   if((sv&&sr)!=(dut.pad.s_valid&&dut.pad_in_ready))
    $fatal(1,"[CONFIG_ARB] Hidden reflect_pad input transfer");
   if(cv&&cr) begin
    if(sr) $fatal(1,"[CONFIG_ARB] OM-LSA accepted cfg and data together");
    if(nn==16&&(sent!=33||retired!=1)) $fatal(1,"[CONFIG_ARB] Configuration accepted before pipeline drained");
    cfgs=cfgs+1;
   end
   if(sv&&sr) sent=sent+1;
   if(mv&&mr) begin
    if(got>=no||32'(yr)!=ox[got]+(got==0&&$test$plusargs("INJECT_MISMATCH")?1:0)||32'(yi)!=oy[got]||ml!=1'(ol[got]))
     $fatal(1,"[NUMERIC] OM-LSA output=%0d got=(%0d,%0d,%0b)",got,yr,yi,ml);
    got=got+1;
   end
   if(dut.y_take&&dut.y_last) retired=retired+1;
  end
 end
 task automatic word(input integer i);
  xr=18'(ix[i]);xi=18'(iy[i]);sl=1'(il[i]);sv=1;
 endtask
 task automatic cfg(input integer n);
  @(negedge clk);cv=1;nn=5'(n);
  @(posedge clk);while(!cr) @(posedge clk);
  @(negedge clk);cv=0;
 endtask
 initial begin
  if(!$value$plusargs("DATA=%s",data)) $fatal(1,"[VECTOR] Missing DATA");
  fd=$fopen(data,"r");if(fd==0) $fatal(1,"[VECTOR] Cannot open DATA");
  rc=$fscanf(fd,"%d %d",ni,no);if(rc!=2||ni!=162||no!=162) $fatal(1,"[VECTOR] Invalid counts");
  for(integer i=0;i<ni;i++) begin rc=$fscanf(fd,"%d %d %d",ix[i],iy[i],il[i]);if(rc!=3) $fatal(1,"[VECTOR] Invalid input");end
  for(integer i=0;i<no;i++) begin rc=$fscanf(fd,"%d %d %d",ox[i],oy[i],ol[i]);if(rc!=3) $fatal(1,"[VECTOR] Invalid output");end
  $fclose(fd);
  repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
  cfg(MID_SIGNAL?1:2);
  if(!MID_SIGNAL) begin
   @(negedge clk);cv=1;nn=1;
   #1;if(!cr||sr) $fatal(1,"[CONFIG_ARB] OM-LSA cfg priority depends on data valid");
   word(0);#1;if(sr) $fatal(1,"[CONFIG_ARB] OM-LSA cfg failed to exclude data");
   @(posedge clk);if(!cr) $fatal(1,"[CONFIG_ARB] Empty OM-LSA rejected cfg");
   @(negedge clk);cv=0;
  end else begin @(negedge clk);word(0);end
  @(posedge clk);while(!sr) @(posedge clk);
  @(negedge clk);sv=0;
  // Новое предложение сохраняется до окончания текущего сигнала и его хвоста.
  if(MID_SIGNAL) begin cv=1;nn=16;end
  repeat(12) begin
   @(posedge clk);if(cr) $fatal(1,"[CONFIG_ARB] Configuration available in paused input signal");
   @(negedge clk);
  end
  for(integer i=1;i<33;i++) begin
   word(i);@(posedge clk);while(!sr) @(posedge clk);
   if(cr) $fatal(1,"[CONFIG_ARB] Configuration available inside input signal");
   @(negedge clk);sv=0;
  end
  wait(mv);
  repeat(20) begin
   @(posedge clk);if(cr) $fatal(1,"[CONFIG_ARB] Configuration available with blocked output");
   @(negedge clk);
  end
  mr=1;
  if(MID_SIGNAL) begin
   @(posedge clk);while(!cr) @(posedge clk);
   @(negedge clk);cv=0;
  end else cfg(16);
  // После отложенного cfg следующий сигнал использует уже nnoise=16.
  for(integer i=33;i<ni;i++) begin
   word(i);@(posedge clk);while(!sr) @(posedge clk);
   @(negedge clk);sv=0;
  end
  wait(got==no&&retired==2);repeat(24) @(negedge clk);
  if(!cr||sent!=ni||cfgs!=(MID_SIGNAL?2:3)||mv) $fatal(1,"[CONFIG_ARB] Incomplete OM-LSA recovery");
  $display("PASS OMLSA CFG priority mid=%0d inputs=%0d outputs=%0d cfg=%0d",MID_SIGNAL,sent,got,cfgs);$finish;
 end
 initial begin #20000000;$fatal(1,"[TIMEOUT] OM-LSA cfg priority");end
endmodule
