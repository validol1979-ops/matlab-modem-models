// Full raw arithmetic, before fits()/casts; independent signed192 reference.
bit nb_enabled;
string nb_inject;
longint nb_count[0:9];
logic signed [191:0] nb_min[0:9],nb_max[0:9];
logic signed [191:0] nb_next_re,nb_next_im,nb_div_expected;
bit nb_div_pending=0;
initial begin
  nb_enabled=$test$plusargs("CHECK_NORM_BACK");
  if($value$plusargs("INJECT_NORM_BACK=%s",nb_inject)&&!nb_enabled)
    $fatal(1,"[ARITHMETIC] disabled norm/back observer");
  for(int b=0;b<10;b++) begin nb_count[b]=0;nb_min[b]=0;nb_max[b]=0;end
end
function automatic logic signed [191:0] nb_round(input logic signed [191:0] v,input int shift);
  if(shift>0) return (v+(192'sd1<<<(shift-1)))>>>shift;
  return v<<<(-shift);
endfunction
task automatic nb_pair(input int bank,input string tag,
  input logic signed [191:0] re,im,actual_re,actual_im);
  logic signed [191:0] ar,ai;
  ar=actual_re;ai=actual_im;
  if(nb_count[bank]==0&&nb_inject==tag) ar+=1;
  if(ar!==re||ai!==im) $fatal(1,"[%s] norm/back raw arithmetic bank=%0d",tag,bank);
  for(int c=0;c<2;c++) begin
    logic signed [191:0] v;
    v=c==0?re:im;
    if(nb_count[bank+c]==0||v<nb_min[bank+c]) nb_min[bank+c]=v;
    if(nb_count[bank+c]==0||v>nb_max[bank+c]) nb_max[bank+c]=v;
    nb_count[bank+c]++;
  end
endtask
always @(posedge clk) if(nb_enabled) begin
  if(rst==RESET_ACTIVE) nb_div_pending=0;
  else begin
    int dest,source,aslot,shift;
    logic signed [191:0] re,im,pr,pi;
    dest=N*int'(dut.ci)+int'(dut.cj);source=N*int'(dut.cc)+int'(dut.cj);
    aslot=N*int'(dut.ck)+int'(dut.cc);shift=int'(dut.escale);
    if(nb_div_pending&&192'(dut.div_num)!==nb_div_expected)
      $fatal(1,"[DIVIDER] norm/back numerator sign extension");
    nb_div_pending=0;
    if(dut.cstate==dut.C_NORM&&dut.cj>=dut.ci) begin
      re=nb_round(192'(dut.gr[dest]),shift);im=nb_round(192'(dut.gi[dest]),shift);
      nb_pair(0,"NORM",re,im,192'(dut.norm_re),192'(dut.norm_im));
    end
    if(dut.cstate==dut.C_MULT&&!dut.div_wait&&!dut.div_busy) begin
      int slot;
      slot=N*int'(dut.ck)+int'(dut.ci);
      re=192'(dut.ar[slot])<<<30;im=-(192'(dut.ai[slot])<<<30);
      // One bank event per complex numerator, although the divider launches twice.
      if(!dut.div_phase) nb_pair(2,"MULT",re,im,192'(dut.mult_num_re),192'(dut.mult_num_im));
      nb_div_expected=dut.div_phase?im:re;nb_div_pending=1;
    end
    if(dut.cstate==dut.C_BACK) begin
      if(int'(dut.cc)==int'(dut.ck)+1) begin
        int slot;
        slot=N*int'(dut.ck)+int'(dut.cj);
        nb_next_re=192'(dut.br[slot])<<<30;nb_next_im=192'(dut.bi[slot])<<<30;
      end
      nb_pair(6,"ACC",nb_next_re,nb_next_im,192'(dut.acc_re),192'(dut.acc_im));
      if(int'(dut.cc)<N) begin
        pr=192'(dut.ar[aslot])*192'(dut.br[source])-192'(dut.ai[aslot])*192'(dut.bi[source]);
        pi=192'(dut.ar[aslot])*192'(dut.bi[source])+192'(dut.ai[aslot])*192'(dut.br[source]);
        nb_pair(4,"PRODUCT",pr,pi,192'(dut.back_product_re),192'(dut.back_product_im));
        nb_next_re-=pr;nb_next_im-=pi;
        if(192'(dut.back_re)!==nb_next_re||192'(dut.back_im)!==nb_next_im)
          $fatal(1,"[ACC] norm/back subtraction");
      end
    end
    if(dut.cstate==dut.C_SOLVE&&!dut.div_wait&&!dut.div_busy) begin
      nb_div_expected=dut.div_phase?nb_next_im:nb_next_re;nb_div_pending=1;
    end
    if(dut.cstate==dut.C_WEIGHT) begin
      re=nb_round(192'(dut.br[dest]),shift+15);im=nb_round(192'(dut.bi[dest]),shift+15);
      nb_pair(8,"WEIGHT",re,im,192'(dut.weight_re),192'(dut.weight_im));
    end
  end
end
task automatic check_norm_back;
  if(nb_enabled) begin
    for(int b=0;b<10;b++) $display("NORM BACK BANK bank=%0d count=%0d min=%0d max=%0d",b,nb_count[b],nb_min[b],nb_max[b]);
    $display("PASS WIDTH OBSERVER norm_back");
  end
endtask
