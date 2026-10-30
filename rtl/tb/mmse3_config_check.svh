// Optional configuration observer, independent raw signed128 arithmetic over
// actual DUT operands. Counts include warm-up configurations before resets.
// Banks 0..5: ADJ real/imag, DET real/imag, M real/imag.
bit mm3_cfg_enabled,mm3_cfg_in_reset=0;
string mm3_cfg_inject;
longint mm3_cfg_epochs=0,mm3_cfg_count[0:5];
logic signed [127:0] mm3_cfg_min[0:5],mm3_cfg_max[0:5];
logic signed [127:0] mm3_cfg_expected[0:1];
int mm3_cfg_pending=0,mm3_cfg_entry;
initial begin
  mm3_cfg_enabled=$test$plusargs("CHECK_MMSE3_CONFIG");
  if($value$plusargs("INJECT_MMSE3_CONFIG=%s",mm3_cfg_inject)) begin
    if(!mm3_cfg_enabled) $fatal(1,"[MMSE3_CONFIG] injection requires CHECK_MMSE3_CONFIG");
    if(mm3_cfg_inject!="ADJ"&&mm3_cfg_inject!="DET"&&mm3_cfg_inject!="M")
      $fatal(1,"[MMSE3_CONFIG] unknown injection");
  end
  for(int j=0;j<6;j++) begin mm3_cfg_count[j]=0;mm3_cfg_min[j]=0;mm3_cfg_max[j]=0;end
end
function automatic logic signed [127:0] mm3_cfg_adj(input int row,col,input bit imag_part);
  int ra,rb,ca,cb;
  logic signed [127:0] total;
  ra=col==0?1:0;rb=col==2?1:2;ca=row==0?1:0;cb=row==2?1:2;
  if(imag_part)
    total=128'(dut.gr[3*ra+ca])*128'(dut.gi[3*rb+cb])+128'(dut.gi[3*ra+ca])*128'(dut.gr[3*rb+cb])
         -128'(dut.gr[3*ra+cb])*128'(dut.gi[3*rb+ca])-128'(dut.gi[3*ra+cb])*128'(dut.gr[3*rb+ca]);
  else
    total=128'(dut.gr[3*ra+ca])*128'(dut.gr[3*rb+cb])-128'(dut.gi[3*ra+ca])*128'(dut.gi[3*rb+cb])
         -128'(dut.gr[3*ra+cb])*128'(dut.gr[3*rb+ca])+128'(dut.gi[3*ra+cb])*128'(dut.gi[3*rb+ca]);
  return ((row+col)&1)?-total:total;
endfunction
function automatic logic signed [127:0] mm3_cfg_det(input bit imag_part);
  logic signed [127:0] total;
  total=0;
  for(int k=0;k<3;k++) begin
    if(imag_part) total+=128'(dut.gr[k])*128'(dut.ai[3*k])+128'(dut.gi[k])*128'(dut.ar[3*k]);
    else total+=128'(dut.gr[k])*128'(dut.ar[3*k])-128'(dut.gi[k])*128'(dut.ai[3*k]);
  end
  return total;
endfunction
function automatic logic signed [127:0] mm3_cfg_m(input int row,col,input bit imag_part);
  logic signed [127:0] total;
  total=0;
  for(int k=0;k<3;k++) begin
    if(imag_part) total+=128'(dut.ai[3*row+k])*128'(dut.hr[3*col+k])-128'(dut.ar[3*row+k])*128'(dut.hi[3*col+k]);
    else total+=128'(dut.ar[3*row+k])*128'(dut.hr[3*col+k])+128'(dut.ai[3*row+k])*128'(dut.hi[3*col+k]);
  end
  return total;
endfunction
task automatic mm3_cfg_record(input int bank,input logic signed [127:0] raw);
  if(mm3_cfg_count[bank]==0||raw<mm3_cfg_min[bank]) mm3_cfg_min[bank]=raw;
  if(mm3_cfg_count[bank]==0||raw>mm3_cfg_max[bank]) mm3_cfg_max[bank]=raw;
  mm3_cfg_count[bank]++;
endtask
task automatic mm3_cfg_compare(input int stage,component,input logic signed [127:0] actual,expected);
  if(actual!==expected)
    case(stage)
      1:$fatal(1,"[MMSE3_CONFIG_ADJ] entry=%0d component=%0d actual=%0d expected=%0d",mm3_cfg_entry,component,actual,expected);
      2:$fatal(1,"[MMSE3_CONFIG_DET] component=%0d actual=%0d expected=%0d",component,actual,expected);
      3:$fatal(1,"[MMSE3_CONFIG_M] entry=%0d component=%0d actual=%0d expected=%0d",mm3_cfg_entry,component,actual,expected);
    endcase
endtask
always @(posedge clk) if(mm3_cfg_enabled) begin
  mm3_cfg_pending=0;
  if(rst==RESET_ACTIVE) begin
    if(!mm3_cfg_in_reset) mm3_cfg_epochs++;
    mm3_cfg_in_reset=1;
  end else begin
    mm3_cfg_in_reset=0;
    mm3_cfg_entry=int'(dut.entry);
    if(dut.cstate==dut.C_ADJ) mm3_cfg_pending=1;
    else if(dut.cstate==dut.C_DET) mm3_cfg_pending=2;
    else if(dut.cstate==dut.C_M) mm3_cfg_pending=3;
    if(mm3_cfg_pending!=0) for(int c=0;c<2;c++) begin
      logic signed [127:0] actual,raw,narrow;
      case(mm3_cfg_pending)
        1:begin raw=mm3_cfg_adj(mm3_cfg_entry/3,mm3_cfg_entry%3,1'(c));
          actual=128'(dut.adjugate(mm3_cfg_entry/3,mm3_cfg_entry%3,1'(c)));narrow=128'(ADJ_WIDTH'(raw));end
        2:begin raw=mm3_cfg_det(1'(c));actual=128'(dut.determinant(1'(c)));narrow=128'(DET_WIDTH'(raw));end
        3:begin raw=mm3_cfg_m(mm3_cfg_entry/3,mm3_cfg_entry%3,1'(c));
          actual=128'(dut.mentry(mm3_cfg_entry/3,mm3_cfg_entry%3,1'(c)));narrow=128'(M_WIDTH'(raw));end
        default:begin raw=0;actual=0;narrow=0;end
      endcase
      if(raw!==narrow) $fatal(1,"[MMSE3_CONFIG_RANGE] stage=%0d component=%0d",mm3_cfg_pending,c);
      // Perturb the actual function observation; the regular stage comparator
      // must catch the error with its exact stage tag.
      if(c==0&&mm3_cfg_count[2*(mm3_cfg_pending-1)]==0&&
         ((mm3_cfg_pending==1&&mm3_cfg_inject=="ADJ")||
          (mm3_cfg_pending==2&&mm3_cfg_inject=="DET")||
          (mm3_cfg_pending==3&&mm3_cfg_inject=="M"))) actual+=1;
      mm3_cfg_compare(mm3_cfg_pending,c,actual,raw);
      mm3_cfg_expected[c]=raw;
      mm3_cfg_record(2*(mm3_cfg_pending-1)+c,raw);
    end
  end
end
always @(negedge clk) if(mm3_cfg_enabled&&rst!=RESET_ACTIVE&&mm3_cfg_pending!=0) begin
  for(int c=0;c<2;c++) begin
    logic signed [127:0] actual;
    case(mm3_cfg_pending)
      1:actual=c?128'(dut.ai[mm3_cfg_entry]):128'(dut.ar[mm3_cfg_entry]);
      // DET imag is checked as a function above; the DUT only stores real DET.
      2:actual=c?mm3_cfg_expected[1]:128'(dut.det);
      3:actual=c?128'(dut.mi[mm3_cfg_entry]):128'(dut.mr[mm3_cfg_entry]);
      default:actual=0;
    endcase
    mm3_cfg_compare(mm3_cfg_pending,c,actual,mm3_cfg_expected[c]);
  end
end
task automatic check_mmse3_config;
  longint total;
  if(mm3_cfg_enabled) begin
    total=0;
    for(int bank=0;bank<6;bank++) begin
      total+=mm3_cfg_count[bank];
      $display("MMSE3 CONFIG BANK bank=%0d count=%0d min=%0d max=%0d",bank,mm3_cfg_count[bank],mm3_cfg_min[bank],mm3_cfg_max[bank]);
    end
    $display("PASS MMSE3 CONFIG ADJ_WIDTH=%0d DET_WIDTH=%0d M_WIDTH=%0d epochs=%0d adj_re=%0d adj_im=%0d det_re=%0d det_im=%0d m_re=%0d m_im=%0d total=%0d",
      ADJ_WIDTH,DET_WIDTH,M_WIDTH,mm3_cfg_epochs,mm3_cfg_count[0],mm3_cfg_count[1],mm3_cfg_count[2],mm3_cfg_count[3],mm3_cfg_count[4],mm3_cfg_count[5],total);
  end
endtask
