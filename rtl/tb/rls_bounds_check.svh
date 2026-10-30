// RLS row and dump counters are initialized on entry to their active states.
int rls_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) rls_bounds_checks=0;
  else begin
    if($isunknown({configured,dut.state,dut.take,w_valid}))
      $fatal(1,"[BOUNDS] rls unknown control");
    if(configured) begin
      if($isunknown(dut.taps) || int'(dut.taps)<1 || int'(dut.taps)>(1<<LOG2N))
        $fatal(1,"[BOUNDS] rls tap count");
      if(dut.state==dut.U || dut.state==dut.PT || dut.state==dut.PN) begin
        int observed;
        observed=int'(dut.row);
        if(scoring && $test$plusargs("INJECT_BOUND_MISMATCH")) observed=int'(dut.taps);
        if($isunknown(dut.row) || observed<0 || observed>=int'(dut.taps) || observed>=(1<<LOG2N))
          $fatal(1,"[BOUNDS] rls matrix row address");
        if(scoring) rls_bounds_checks+=1;
      end
      if(dut.state==dut.DUMP) begin
        if($isunknown(dut.dump) || int'(dut.dump)>int'(dut.taps))
          $fatal(1,"[BOUNDS] rls dump counter");
        if((!w_valid || w_ready) && dut.dump!=dut.taps) begin
          if(int'(dut.dump)>=(1<<LOG2N)) $fatal(1,"[BOUNDS] rls dump address");
          if(scoring) rls_bounds_checks+=1;
        end
      end
    end
  end
end
task automatic check_rls_bounds();
  if(rls_bounds_checks<1) $fatal(1,"[BOUNDS] rls monitor not exercised");
  $display("PASS BOUNDS rls: %0d checks",rls_bounds_checks);
endtask
