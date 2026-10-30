int oset_bounds_checks=0;
always @(posedge clk) begin
  if (rst==RESET_ACTIVE) oset_bounds_checks=0;
  else begin
    if ($isunknown({dut_notch.pos,dut_notch.configured,dut_kalman.gcount,dut_kalman.gstate,dut_kalman.converged}))
      $fatal(1,"[BOUNDS] notch/kalman unknown control state");
    if (dut_notch.configured) begin
      int observed;
      observed=int'(dut_notch.pos);
      if (dut_notch.take&&scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=3;
      if (observed>2) $fatal(1,"[BOUNDS] notch history selector");
    end
    if (dut_kalman.gcount>4) $fatal(1,"[BOUNDS] kalman gain FIFO occupancy");
    if (dut_kalman.gstate==dut_kalman.G_UPDATE&&
        int'(dut_kalman.gcount)+1-int'(dut_kalman.take&&dut_kalman.gcount!=0)>4)
      $fatal(1,"[BOUNDS] kalman gain write lacks space");
    if (dut_kalman.take&&!dut_kalman.converged&&dut_kalman.gcount==0)
      $fatal(1,"[BOUNDS] kalman missing gain on input");
    if (scoring&&(dut_notch.take||dut_notch.ce&&dut_notch.a_valid||dut_kalman.take||dut_kalman.update))
      oset_bounds_checks+=1;
  end
end
task automatic check_oset_bounds();
  if (oset_bounds_checks<1) $fatal(1,"[BOUNDS] oset checker not exercised");
  $display("PASS BOUNDS oset: %0d checks",oset_bounds_checks);
endtask
