// Raw arithmetic observer: deliberately independent signed 128-bit products and
// additions, fed by the DUT's actual operands. No random calls or stimulus.
bit width_enabled;
string width_inject;
longint width_gram_count=0,width_sum_count=0,width_round_count=0;
longint width_count[0:13];
logic signed [127:0] width_min[0:13],width_max[0:13];
logic signed [127:0] width_expected_gram[0:1],width_expected_sum[0:5];
bit width_gram_pending=0,width_sum_pending=0;
int width_entry;
initial begin
  width_enabled=$test$plusargs("CHECK_MMSE3_WIDTHS");
  if($value$plusargs("INJECT_MMSE3=%s",width_inject)) begin
    if(!width_enabled) $fatal(1,"[WIDTHS] INJECT_MMSE3 requires CHECK_MMSE3_WIDTHS");
    if(width_inject!="GRAM"&&width_inject!="SUM"&&width_inject!="ROUND")
      $fatal(1,"[WIDTHS] unknown INJECT_MMSE3");
  end
  for(int j=0;j<14;j++) begin width_count[j]=0;width_min[j]=0;width_max[j]=0;end
end
task automatic width_record(input int bank,input logic signed [127:0] value);
  if(width_count[bank]==0||value<width_min[bank]) width_min[bank]=value;
  if(width_count[bank]==0||value>width_max[bank]) width_max[bank]=value;
  width_count[bank]++;
endtask
function automatic logic signed [127:0] width_gram(input int row,col,input bit imag_part);
  logic signed [127:0] total;
  total=0;
  for(int k=0;k<3;k++) begin
    if(imag_part) total+=128'(dut.hr[3*k+row])*128'(dut.hi[3*k+col])
                             -128'(dut.hi[3*k+row])*128'(dut.hr[3*k+col]);
    else total+=128'(dut.hr[3*k+row])*128'(dut.hr[3*k+col])
               +128'(dut.hi[3*k+row])*128'(dut.hi[3*k+col]);
  end
  if(!imag_part&&row==col) total+=128'($signed({1'b0,dut.lambda}));
  return total;
endfunction
function automatic logic signed [127:0] width_sum(input int row,input bit imag_part);
  logic signed [127:0] total,xr,xi;
  total=0;
  for(int k=0;k<3;k++) begin
    xr=k==2?128'(s_re):128'(dut.obs_re[k]);
    xi=k==2?128'(s_im):128'(dut.obs_im[k]);
    if(imag_part) total+=128'(dut.wr[3*row+k])*xi+128'(dut.wi[3*row+k])*xr;
    else total+=128'(dut.wr[3*row+k])*xr-128'(dut.wi[3*row+k])*xi;
  end
  return total;
endfunction
function automatic logic signed [17:0] width_sat(input logic signed [127:0] value);
  logic signed [127:0] rounded;
  rounded=(value+128'sd8388608)>>>24;
  if(rounded>131071) return 18'sd131071;
  if(rounded< -131072) return 18'sh20000;
  return rounded[17:0];
endfunction
always @(posedge clk) if(width_enabled) begin
  width_gram_pending=0;width_sum_pending=0;
  if(rst==RESET_ACTIVE) begin
    width_gram_count=0;width_sum_count=0;width_round_count=0;
    for(int j=0;j<14;j++) begin width_count[j]=0;width_min[j]=0;width_max[j]=0;end
  end else begin
    if(dut.cstate==dut.C_GRAM) begin
      width_entry=int'(dut.entry);
      for(int c=0;c<2;c++) begin
        width_expected_gram[c]=width_gram(width_entry/3,width_entry%3,1'(c));
        width_record(c,width_expected_gram[c]);
        if(width_expected_gram[c] != 128'(GRAM_WIDTH'(width_expected_gram[c])))
          $fatal(1,"[GRAM] MMSE3 range component=%0d",c);
      end
      width_gram_pending=1;
    end
    if(dut.take&&dut.index==2) begin
      for(int row=0;row<3;row++) for(int c=0;c<2;c++)
        width_expected_sum[2*row+c]=width_sum(row,1'(c));
      width_sum_pending=1;
    end
    if(dut.p_valid) begin
      for(int row=0;row<3;row++) for(int c=0;c<2;c++) begin
        logic signed [127:0] raw,rounded;
        logic signed [17:0] actual,expected;
        raw=c?128'(dut.yi[row]):128'(dut.yr[row]);
        rounded=(raw+128'sd8388608)>>>24;
        width_record(8+2*row+c,rounded);
        actual=dut.sat18(SUM_WIDTH'(raw));expected=width_sat(raw);
        if(width_inject=="ROUND"&&width_round_count==0) expected^=18'd1;
        if(actual!==expected) $fatal(1,"[ROUND] MMSE3 row=%0d component=%0d",row,c);
        width_round_count++;
      end
    end
  end
end
always @(negedge clk) if(width_enabled&&rst!=RESET_ACTIVE) begin
  if(width_gram_pending) begin
    for(int c=0;c<2;c++) begin
      logic signed [127:0] actual,expected;
      actual=c?128'(dut.gi[width_entry]):128'(dut.gr[width_entry]);
      expected=width_expected_gram[c];
      if(width_inject=="GRAM"&&width_gram_count==0) expected+=1;
      if(actual!==expected) $fatal(1,"[GRAM] MMSE3 entry=%0d component=%0d actual=%0d expected=%0d",width_entry,c,actual,expected);
      width_gram_count++;
    end
  end
  if(width_sum_pending) begin
    if(!dut.p_valid) $fatal(1,"[SUM] MMSE3 missing p_valid");
    for(int row=0;row<3;row++) for(int c=0;c<2;c++) begin
      logic signed [127:0] actual,expected;
      actual=c?128'(dut.yi[row]):128'(dut.yr[row]);expected=width_expected_sum[2*row+c];
      width_record(2+2*row+c,expected);
      if(expected != 128'(SUM_WIDTH'(expected))) $fatal(1,"[SUM] MMSE3 range");
      if(width_inject=="SUM"&&width_sum_count==0) expected+=1;
      if(actual!==expected) $fatal(1,"[SUM] MMSE3 row=%0d component=%0d actual=%0d expected=%0d",row,c,actual,expected);
      width_sum_count++;
    end
  end
end
task automatic check_mmse3_widths;
if(width_enabled) begin
  $display("PASS MMSE3 WIDTHS GRAM_WIDTH=%0d SUM_WIDTH=%0d gram=%0d sum=%0d round=%0d",GRAM_WIDTH,SUM_WIDTH,width_gram_count,width_sum_count,width_round_count);
  for(int bank=0;bank<14;bank++)
    $display("MMSE3 WIDTHS BANK bank=%0d count=%0d min=%0d max=%0d",bank,width_count[bank],width_min[bank],width_max[bank]);
end
endtask
