// Real FIFO occupancy/reservations and accesses, including simultaneous pop/push.
int mmse_bounds_checks=0;
always @(posedge clk) begin
  if (rst == RESET_ACTIVE) mmse_bounds_checks=0;
  else begin
    if ($isunknown({dut.fifo_count,dut.pending,dut.count,dut.cstate}))
      $fatal(1,"[BOUNDS] mmse unknown control state");
    if (int'(dut.fifo_count)>8 || int'(dut.fifo_count)+2*int'(dut.pending)>8)
      $fatal(1,"[BOUNDS] mmse FIFO reservations");
    if (dut.pop && dut.fifo_count==0) $fatal(1,"[BOUNDS] mmse empty read");
    if (dut.e_valid && int'(dut.fifo_count)+2-int'(dut.pop)>8)
      $fatal(1,"[BOUNDS] mmse pair write lacks space");
    if (dut.cfg_valid && dut.cfg_ready && dut.count<4 && scoring) begin
      int observed;
      observed=int'(dut.count);
      if ($test$plusargs("INJECT_BOUND_MISMATCH")) observed=4;
      if (observed<0 || observed>=4) $fatal(1,"[BOUNDS] mmse config address");
      mmse_bounds_checks+=1;
    end
    if (scoring && (dut.take || dut.pop || dut.e_valid)) mmse_bounds_checks+=1;
  end
end
task automatic check_mmse_bounds();
  if (mmse_bounds_checks<1) $fatal(1,"[BOUNDS] mmse monitor not exercised");
  $display("PASS BOUNDS mmse: %0d checks",mmse_bounds_checks);
endtask
