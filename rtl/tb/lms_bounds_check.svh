// Check initialized controls and actual indexed accesses only.
int lms_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) lms_bounds_checks=0;
  else begin
    if($isunknown({configured,dut.state,dut.take,w_valid}))
      $fatal(1,"[BOUNDS] lms unknown control");
    if(configured) begin
      if($isunknown(dut.taps) || int'(dut.taps)<1 || int'(dut.taps)>(1<<LOG2N))
        $fatal(1,"[BOUNDS] lms tap count");
      if(dut.take) begin
        int observed;
        observed=int'(dut.taps)-1;
        if(scoring && $test$plusargs("INJECT_BOUND_MISMATCH")) observed=int'(dut.taps);
        if(observed<0 || observed>=int'(dut.taps) || observed>=(1<<LOG2N))
          $fatal(1,"[BOUNDS] lms history address");
        if(scoring) lms_bounds_checks+=1;
      end
      if(dut.state==dut.ERROR && dut.nlms) begin
        if($isunknown({dut.p_total,dut.p_bits,dut.mantissa}) || dut.p_total<512 || dut.p_bits<10 || int'(dut.p_bits)>$bits(dut.p_total))
          $fatal(1,"[BOUNDS] nlms reciprocal normalization");
        if((dut.p_total>>(int'(dut.p_bits)-10))<512 || (dut.p_total>>(int'(dut.p_bits)-10))>1023)
          $fatal(1,"[BOUNDS] nlms reciprocal ROM address");
        if(scoring) lms_bounds_checks+=1;
      end
      if(dut.state==dut.DUMP) begin
        if($isunknown(dut.dump) || int'(dut.dump)>int'(dut.taps))
          $fatal(1,"[BOUNDS] lms dump counter");
        if((!w_valid || w_ready) && dut.dump!=dut.taps) begin
          if(int'(dut.dump)>=(1<<LOG2N)) $fatal(1,"[BOUNDS] lms dump address");
          if(scoring) lms_bounds_checks+=1;
        end
      end
    end
  end
end
task automatic check_lms_bounds();
  if(lms_bounds_checks<1) $fatal(1,"[BOUNDS] lms monitor not exercised");
  $display("PASS BOUNDS lms: %0d checks",lms_bounds_checks);
endtask
