// signed192 reference covers the full signed145 left-shift result.
bit scale_check_enabled;
string scale_inject;
longint scale_count[0:3];
logic signed [191:0] scale_min[0:3],scale_max[0:3];
initial begin
  scale_check_enabled=$test$plusargs("CHECK_SCALE_UPDATES");
  if($value$plusargs("INJECT_SCALE_UPDATE=%s",scale_inject)) begin
    if(!scale_check_enabled) $fatal(1,"[ARITHMETIC] disabled scale observer");
  end
  for(int b=0;b<4;b++) begin scale_count[b]=0;scale_min[b]=0;scale_max[b]=0;end
end
task automatic scale_record(input int b,input logic signed [191:0] v);
  if(scale_count[b]==0||v<scale_min[b]) scale_min[b]=v;
  if(scale_count[b]==0||v>scale_max[b]) scale_max[b]=v;
  scale_count[b]++;
endtask
task automatic scale_compare(input logic signed [105:0] v,input int c);
  logic signed [191:0] p,y,actual;
  bit bad,got_bad;
  int amount;
  if(dut.r<24'd4194304||dut.r>24'd8388608||dut.shift<8||dut.shift>134)
    $fatal(1,"[ARITHMETIC] normalized scale contract");
  p=192'(v)*192'($signed({1'b0,dut.r}));amount=int'(dut.shift)-24;
  y=amount>0?(p+(192'sd1<<<(amount-1)))>>>amount:p<<<(-amount);
  actual=192'(dut.scale_product(v));
  if(scale_inject=="PRODUCT"&&scale_count[c]==0) actual+=1;
  if(actual!==p) $fatal(1,"[PRODUCT] MMSE3 raw multiply");
  actual=192'(dut.wround(v));
  if(scale_inject=="SCALE"&&scale_count[c]==0) actual+=1;
  if(actual!==y) $fatal(1,"[SCALE] MMSE3 raw weight");
  bad=y<-(192'sd1<<<63)||y>=(192'sd1<<<63);
  got_bad=dut.coefficient_overflow(SCALE_WIDTH'(actual));
  if(scale_inject=="OVERFLOW"&&scale_count[c]==0) got_bad=!got_bad;
  if(got_bad!==bad) $fatal(1,"[OVERFLOW] MMSE3 coefficient guard");
  scale_record(c,p);scale_record(c+2,y);
endtask
always @(posedge clk) if(scale_check_enabled&&rst!=RESET_ACTIVE&&dut.cstate==dut.C_WEIGHT) begin
  scale_compare(dut.mr[dut.entry],0);scale_compare(dut.mi[dut.entry],1);
end
task automatic check_scale_updates;
  if(scale_check_enabled) begin
    for(int b=0;b<4;b++) $display("WIDTH BANK bank=%0d count=%0d min=%0d max=%0d",b,scale_count[b],scale_min[b],scale_max[b]);
    $display("PASS WIDTH OBSERVER scale");
  end
endtask
