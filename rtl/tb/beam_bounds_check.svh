int beam_bounds_checks=0;
always @(posedge clk) begin
  if (rst==RESET_ACTIVE) beam_bounds_checks=0;
  else begin
    if ($isunknown({dut_beamform.fifo_count,dut_beamform.pending,dut_beamform.loaded,dut_beamform.c,
                    dut_alamouti.fifo_count,dut_alamouti.pending}))
      $fatal(1,"[BOUNDS] beam/alamouti unknown control state");
    if (int'(dut_beamform.fifo_count)+int'(dut_beamform.pending)>8)
      $fatal(1,"[BOUNDS] beam reservations exceed FIFO");
    if (int'(dut_alamouti.fifo_count)+2*int'(dut_alamouti.pending)>8)
      $fatal(1,"[BOUNDS] alamouti pair reservations exceed FIFO");
    if (dut_beamform.pop&&dut_beamform.fifo_count==0 || dut_alamouti.pop&&dut_alamouti.fifo_count==0)
      $fatal(1,"[BOUNDS] beam/alamouti empty read");
    if (dut_beamform.e_valid&&int'(dut_beamform.fifo_count)+1-int'(dut_beamform.pop)>8)
      $fatal(1,"[BOUNDS] beam output write lacks space");
    if (dut_alamouti.e_valid&&int'(dut_alamouti.fifo_count)+2-int'(dut_alamouti.pop)>8)
      $fatal(1,"[BOUNDS] alamouti pair write lacks space");
    if (dut_beamform.take) begin
      int observed;
      observed=int'(dut_beamform.c);
      if (scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=int'(dut_beamform.loaded);
      if (dut_beamform.loaded<1 || int'(dut_beamform.loaded)>(1<<LOG2M) || observed>=int'(dut_beamform.loaded))
        $fatal(1,"[BOUNDS] beam weight address outside loaded coefficients");
    end
    if (scoring&&(dut_beamform.take||dut_beamform.pop||dut_beamform.e_valid||
                  dut_alamouti.take||dut_alamouti.pop||dut_alamouti.e_valid)) beam_bounds_checks+=1;
  end
end
task automatic check_beam_bounds();
  if (beam_bounds_checks<1) $fatal(1,"[BOUNDS] beam checker not exercised");
  $display("PASS BOUNDS beam: %0d checks",beam_bounds_checks);
endtask
