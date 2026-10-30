// Check actual elimination operands in signed192, independently of narrow nets.
bit update_check_enabled;
string update_inject;
longint update_count[0:7];
logic signed [191:0] update_min[0:7],update_max[0:7];
initial begin
  update_check_enabled=$test$plusargs("CHECK_SCALE_UPDATES");
  if($value$plusargs("INJECT_SCALE_UPDATE=%s",update_inject)) begin
    if(!update_check_enabled) $fatal(1,"[ARITHMETIC] disabled update observer");
  end
  for(int b=0;b<8;b++) begin update_count[b]=0;update_min[b]=0;update_max[b]=0;end
end
// Keep hierarchical array reads in the caller. Questa 2024.1 can crash
// when a task itself resolves parameterized hierarchical array handles.
task automatic update_compare(input bit is_b,
  input logic signed [191:0] mr,mi,sr,si,cr,ci,
  input logic signed [191:0] actual_pr,actual_pi,actual_ur,actual_ui);
  logic signed [191:0] pr,pi,ur,ui,ap,ai,au,av;
  int bank;
  bank=is_b?4:0;
  pr=mr*sr-mi*si;pi=mr*si+mi*sr;
  ur=cr-((pr+192'sd536870912)>>>30);ui=ci-((pi+192'sd536870912)>>>30);
  ap=actual_pr;ai=actual_pi;au=actual_ur;av=actual_ui;
  if(update_count[bank]==0) begin
    if(((is_b&&update_inject=="B_PRODUCT")||(!is_b&&update_inject=="A_PRODUCT"))) ap+=1;
    if(((is_b&&update_inject=="B_UPDATE")||(!is_b&&update_inject=="A_UPDATE"))) au+=1;
  end
  if(ap!==pr||ai!==pi) begin
    if(is_b) $fatal(1,"[B_PRODUCT] MMSE_N raw multiply");else $fatal(1,"[A_PRODUCT] MMSE_N raw multiply");
  end
  if(au!==ur||av!==ui) begin
    if(is_b) $fatal(1,"[B_UPDATE] MMSE_N raw update");else $fatal(1,"[A_UPDATE] MMSE_N raw update");
  end
  for(int c=0;c<4;c++) begin
    logic signed [191:0] v;
    case(c) 0:v=pr;1:v=pi;2:v=ur;3:v=ui;endcase
    if(update_count[bank+c]==0||v<update_min[bank+c]) update_min[bank+c]=v;
    if(update_count[bank+c]==0||v>update_max[bank+c]) update_max[bank+c]=v;
    update_count[bank+c]++;
  end
endtask
always @(posedge clk) if(update_check_enabled&&rst!=RESET_ACTIVE) begin
  int slot,source,dest;
  slot=int'(dut.ci);source=N*int'(dut.ck)+int'(dut.cj);dest=N*int'(dut.ci)+int'(dut.cj);
  if(dut.cstate==dut.C_UPD_A)
    update_compare(0,192'(dut.mr[slot]),192'(dut.mi[slot]),192'(dut.ar[source]),192'(dut.ai[source]),
      192'(dut.ar[dest]),192'(dut.ai[dest]),192'(dut.ua_re),192'(dut.ua_im),192'(dut.upd_a_re),192'(dut.upd_a_im));
  if(dut.cstate==dut.C_UPD_B)
    update_compare(1,192'(dut.mr[slot]),192'(dut.mi[slot]),192'(dut.br[source]),192'(dut.bi[source]),
      192'(dut.br[dest]),192'(dut.bi[dest]),192'(dut.ub_re),192'(dut.ub_im),192'(dut.upd_b_re),192'(dut.upd_b_im));
end
task automatic check_scale_updates;
  if(update_check_enabled) begin
    for(int b=0;b<8;b++) $display("WIDTH BANK bank=%0d count=%0d min=%0d max=%0d",b,update_count[b],update_min[b],update_max[b]);
    $display("PASS WIDTH OBSERVER updates");
  end
endtask
