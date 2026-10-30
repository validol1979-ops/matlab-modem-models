// Count the raw gradient consumed by Gardner's symmetric Q30 limiter.
int sync_grad_eval=0,sync_grad_pos=0,sync_grad_neg=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    sync_grad_eval=0;sync_grad_pos=0;sync_grad_neg=0;
  end else if(scoring && dut_timing.state==dut_timing.GRADIENT &&
              (!gm_valid || gm_ready)) begin
    longint raw;
    if($isunknown(dut_timing.gardner)) $fatal(1,"[SATURATION] unknown Gardner gradient");
    raw=longint'($signed(dut_timing.gardner));
    sync_grad_eval++;
    if(raw>1073741824) sync_grad_pos++;
    if(raw< -1073741824) sync_grad_neg++;
  end
end

task automatic check_sync_gradient();
  int fd,fields,got,want_eval,want_pos,want_neg,extra;
  fd=$fopen({directory,"/sync_gradient_expected.txt"},"r");
  if(!fd) $fatal(1,"[SATURATION] missing Gardner expectations");
  got=$fscanf(fd,"%d",fields);
  if(got!=1||fields!=1) $fatal(1,"[SATURATION] invalid Gardner fields");
  got=$fscanf(fd,"%d %d %d",want_eval,want_pos,want_neg);
  if(got!=3||want_eval<1||want_pos<0||want_neg<0||want_pos+want_neg>want_eval)
    $fatal(1,"[SATURATION] malformed Gardner expectation");
  if($fscanf(fd,"%d",extra)==1) $fatal(1,"[SATURATION] extra Gardner rows");
  $fclose(fd);
  if($test$plusargs("INJECT_SAT_MISMATCH")) want_pos++;
  if($test$plusargs("INJECT_SAT_EVAL_MISMATCH")) want_eval++;
  if(sync_grad_eval!=want_eval||sync_grad_pos!=want_pos||sync_grad_neg!=want_neg)
    $fatal(1,"[SATURATION] Gardner eval %0d/%0d pos %0d/%0d neg %0d/%0d",
           sync_grad_eval,want_eval,sync_grad_pos,want_pos,sync_grad_neg,want_neg);
  $display("PASS SATURATION sync_gradient: %0d evaluations, %0d events",
           sync_grad_eval,sync_grad_pos+sync_grad_neg);
endtask
