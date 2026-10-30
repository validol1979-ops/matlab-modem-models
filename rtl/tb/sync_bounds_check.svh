// Logical accesses only: interpolation intentionally zero-fills taps outside the frame.
int sync_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) sync_bounds_checks=0;
  else begin
    if(gs_valid&&gs_ready) begin
      int observed;
      observed=int'(dut_timing.wcount);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=16384;
      if(observed<0||observed>=16384) $fatal(1,"[BOUNDS] Gardner sample write index");
      if(scoring) sync_bounds_checks++;
    end
    if(g_cfg_valid&&g_cfg_ready&&g_cfg_sps>=2&&g_cfg_count!=0) begin
      if(g_cfg_position[47]) $fatal(1,"[BOUNDS] Gardner signed start position");
      if(scoring) sync_bounds_checks++;
    end
    if(dut_timing.state==dut_timing.ISSUE) begin
      if($isunknown({dut_timing.issued,dut_timing.length})||
         int'(dut_timing.issued)>2||dut_timing.length=='0||
         int'(dut_timing.length)>16384)
        $fatal(1,"[BOUNDS] Gardner interpolation request");
      if(scoring) sync_bounds_checks++;
    end
    if(dut_timing.state==dut_timing.COLLECT&&dut_timing.r_valid) begin
      if($isunknown({dut_timing.r_tag,dut_timing.collected})||
         dut_timing.r_tag[14:2]!='0||int'(dut_timing.r_tag[1:0])>2||
         int'(dut_timing.collected)>2)
        $fatal(1,"[BOUNDS] Gardner interpolation response tag");
      if(scoring) sync_bounds_checks++;
    end
    if(dut_timing.state==dut_timing.GRADIENT||dut_timing.state==dut_timing.UPDATE) begin
      if($isunknown({dut_timing.done_count,dut_timing.count})||
         dut_timing.count=='0||dut_timing.done_count>=dut_timing.count)
        $fatal(1,"[BOUNDS] Gardner output index");
      if(scoring) sync_bounds_checks++;
    end
  end
end
task automatic check_sync_bounds();
  if(sync_bounds_checks<1) $fatal(1,"[BOUNDS] Gardner bounds monitor not exercised");
  $display("PASS BOUNDS sync: %0d checks",sync_bounds_checks);
endtask
