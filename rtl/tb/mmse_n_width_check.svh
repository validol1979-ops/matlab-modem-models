// Independent signed128 products from actual DUT operands, checked before any
// narrowing/clipping. No stimulus or random calls; warm-up reset traffic clears.
bit width_enabled;
string width_inject;
localparam int WIDTH_BANKS=2+4*N;
longint width_count[0:WIDTH_BANKS-1];
logic signed [127:0] width_min[0:WIDTH_BANKS-1],width_max[0:WIDTH_BANKS-1];
logic signed [127:0] width_expected_sum[0:2*N-1];
bit width_sum_pending=0;
initial begin
  width_enabled=$test$plusargs("CHECK_MMSE_N_WIDTHS");
  if($value$plusargs("INJECT_MMSE_N=%s",width_inject)) begin
    if(!width_enabled) $fatal(1,"[WIDTHS] injection requires width observer");
    if(width_inject!="GRAM"&&width_inject!="SUM"&&width_inject!="ROUND")
      $fatal(1,"[WIDTHS] unknown injection");
  end
  for(int j=0;j<WIDTH_BANKS;j++) begin width_count[j]=0;width_min[j]=0;width_max[j]=0;end
end
task automatic width_record(input int bank,input logic signed [127:0] value);
  if(width_count[bank]==0||value<width_min[bank]) width_min[bank]=value;
  if(width_count[bank]==0||value>width_max[bank]) width_max[bank]=value;
  width_count[bank]++;
endtask
always @(posedge clk) if(width_enabled) begin
  width_sum_pending=0;
  if(rst==RESET_ACTIVE) begin
    for(int j=0;j<WIDTH_BANKS;j++) begin width_count[j]=0;width_min[j]=0;width_max[j]=0;end
  end else begin
    if(dut.cstate==dut.C_GRAM) begin
      logic signed [127:0] re,im,actual;
      int a,b;
      a=N*int'(dut.cc)+int'(dut.ci);b=N*int'(dut.cc)+int'(dut.cj);
      re=128'(dut.sum_re)+128'(dut.hr[a])*128'(dut.hr[b])+128'(dut.hi[a])*128'(dut.hi[b]);
      im=128'(dut.sum_im)+128'(dut.hr[a])*128'(dut.hi[b])-128'(dut.hi[a])*128'(dut.hr[b]);
      if(int'(dut.cc)==N-1&&dut.ci==dut.cj) re+=128'($signed({1'b0,dut.lambda}));
      actual=128'(dut.gram_next_re);
      if(width_inject=="GRAM"&&width_count[0]==0) actual+=1;
      if(actual!==re||128'(dut.gram_next_im)!==im) $fatal(1,"[GRAM] mmse_n raw arithmetic");
      if(re!=128'(GRAM_ACC_WIDTH'(re))||im!=128'(GRAM_ACC_WIDTH'(im))) $fatal(1,"[GRAM] mmse_n raw range");
      width_record(0,re);width_record(1,im);
    end
    if(dut.take&&!dut.abort_partial) begin
      for(int row=0;row<N;row++) begin
        int a;
        a=N*row+int'(dut.index);
        width_expected_sum[2*row]=(dut.index==0?128'd0:128'(dut.yr[row]))
           +128'(dut.wr[a])*128'(s_re)-128'(dut.wi[a])*128'(s_im);
        width_expected_sum[2*row+1]=(dut.index==0?128'd0:128'(dut.yi[row]))
           +128'(dut.wr[a])*128'(s_im)+128'(dut.wi[a])*128'(s_re);
      end
      width_sum_pending=1;
    end
    if(dut.p_valid) begin
      for(int row=0;row<N;row++) for(int c=0;c<2;c++) begin
        logic signed [127:0] raw,rounded;
        logic signed [17:0] actual,expected;
        raw=c?128'(dut.yi[row]):128'(dut.yr[row]);
        rounded=(raw+128'sd8388608)>>>24;
        expected=rounded>131071?18'sd131071:rounded< -131072?18'sh20000:18'(rounded);
        actual=dut.sat18(SUM_WIDTH'(raw));
        if(width_inject=="ROUND"&&width_count[2+2*N]==0) actual^=18'd1;
        if(actual!==expected) $fatal(1,"[ROUND] mmse_n raw rounding");
        width_record(2+2*N+2*row+c,rounded);
      end
    end
  end
end
always @(negedge clk) if(width_enabled&&rst!=RESET_ACTIVE&&width_sum_pending) begin
  for(int row=0;row<N;row++) for(int c=0;c<2;c++) begin
    logic signed [127:0] actual,expected;
    actual=c?128'(dut.yi[row]):128'(dut.yr[row]);expected=width_expected_sum[2*row+c];
    if(width_inject=="SUM"&&width_count[2]==0) actual+=1;
    if(actual!==expected) $fatal(1,"[SUM] mmse_n raw accumulator");
    if(expected!=128'(SUM_WIDTH'(expected))) $fatal(1,"[SUM] mmse_n raw range");
    width_record(2+2*row+c,expected);
  end
end
task automatic check_mmse_n_widths;
if(width_enabled) begin
  $display("PASS MMSE_N WIDTHS N=%0d GRAM_ACC_WIDTH=%0d SUM_WIDTH=%0d",N,GRAM_ACC_WIDTH,SUM_WIDTH);
  for(int bank=0;bank<WIDTH_BANKS;bank++)
    $display("MMSE_N WIDTHS BANK bank=%0d count=%0d min=%0d max=%0d",bank,width_count[bank],width_min[bank],width_max[bank]);
end
endtask
