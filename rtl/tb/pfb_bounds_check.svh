int pfb_bounds_checks=0,pfb_queued=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin pfb_bounds_checks=0;pfb_queued=0;end
  else begin
    bit push_flag,pop_flag;
    int observed;
    push_flag=dut.state==dut.DONE&&!dut.feeding;
    pop_flag=dut.f_valid&&m_ready&&dut.f_last;
    if($isunknown({dut.state,dut.wcount,dut.cur_end,dut.next_end,dut.feeding}))
      $fatal(1,"[BOUNDS] PFB unknown controls");
    observed=pfb_queued;
    if(push_flag&&scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=9;
    if(observed<0 || observed>8 || push_flag&&observed+1-int'(pop_flag)>8)
      $fatal(1,"[BOUNDS] PFB flag FIFO occupancy");
    if(pop_flag&&observed==0) $fatal(1,"[BOUNDS] PFB empty flag FIFO");
    pfb_queued+=int'(push_flag)-int'(pop_flag);
    if(dut.cfg_take) begin
      if(dut.tap_count>=(1<<LOG2TMAX)) $fatal(1,"[BOUNDS] PFB tap RAM write");
      if(scoring) pfb_bounds_checks+=1;
    end
    if(configured && (dut.taps==0 || dut.taps>(1<<LOG2TMAX) || dut.decimation==0 || dut.decimation>M))
      $fatal(1,"[BOUNDS] PFB configuration bounds");
    if(dut.issue) begin
      if($isunknown({dut.step,dut.steps}) || dut.step>=dut.steps)
        $fatal(1,"[BOUNDS] PFB tap-bank read step");
      for(int lane=0;lane<(1<<LOG2LANES);lane++) begin
        int tap_index,sample_index;
        tap_index=(int'(dut.step)<<LOG2LANES)+lane;
        if(tap_index<int'(dut.taps) && tap_index<=int'(dut.cur_end)) begin
          sample_index=int'(dut.cur_end)-tap_index;
          if(sample_index>=int'(dut.wcount) || int'(dut.wcount)-sample_index>dut.RING)
            $fatal(1,"[BOUNDS] PFB history unavailable or overwritten");
          if(scoring) pfb_bounds_checks+=1;
        end
      end
    end
  end
end
task automatic check_pfb_bounds();
  if(pfb_bounds_checks<1 || pfb_queued!=0) $fatal(1,"[BOUNDS] PFB monitor not exercised/drained");
  $display("PASS BOUNDS pfb: %0d checks",pfb_bounds_checks);
endtask
