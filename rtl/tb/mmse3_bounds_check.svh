// Check actual occupancy and triple reservations before each registered transition.
int mmse3_bounds_checks=0,mmse3_simultaneous=0;
int mmse3_expected_fifo=0,mmse3_expected_pending=0;
int mmse3_expected_head=0,mmse3_expected_tail=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    mmse3_bounds_checks=0;mmse3_simultaneous=0;
    mmse3_expected_fifo=0;mmse3_expected_pending=0;
    mmse3_expected_head=0;mmse3_expected_tail=0;
  end else begin
    int next_fifo,next_pending;
    if($isunknown({dut.count,dut.entry,dut.index,dut.fifo_count,dut.pending,
                   dut.fifo_head,dut.fifo_tail,dut.take,dut.pop,dut.e_valid,
                   dut.reserve,dut.cancel,dut.cstate}))
      $fatal(1,"[BOUNDS] MMSE3 unknown active controls");
    if(int'(dut.fifo_count)!=mmse3_expected_fifo || int'(dut.pending)!=mmse3_expected_pending
       ||int'(dut.fifo_head)!=mmse3_expected_head||int'(dut.fifo_tail)!=mmse3_expected_tail)
      $fatal(1,"[BOUNDS] MMSE3 FIFO/reservation transition");
    next_fifo=int'(dut.fifo_count)+3*int'(dut.e_valid)-int'(dut.pop);
    next_pending=int'(dut.pending)+int'(dut.reserve)-int'(dut.e_valid)-int'(dut.cancel);
    if(next_fifo<0||next_fifo>16||next_pending<0||next_fifo+3*next_pending>16)
      $fatal(1,"[BOUNDS] MMSE3 FIFO triple reservation capacity");
    if(dut.pop&&dut.fifo_count==0) $fatal(1,"[BOUNDS] MMSE3 empty read");
    if(dut.e_valid&&dut.pending==0) $fatal(1,"[BOUNDS] MMSE3 unreserved triple write");
    if(dut.index>2||dut.count>9||dut.entry>8) $fatal(1,"[BOUNDS] MMSE3 matrix/input index");
    if(dut.take&&scoring) begin
      int observed;
      observed=int'(dut.index);
      if($test$plusargs("INJECT_BOUND_MISMATCH")) observed=3;
      if(observed<0||observed>=3) $fatal(1,"[BOUNDS] MMSE3 active observation index");
    end
    mmse3_expected_fifo=next_fifo;mmse3_expected_pending=next_pending;
    mmse3_expected_head=(int'(dut.fifo_head)+int'(dut.pop))&15;
    mmse3_expected_tail=(int'(dut.fifo_tail)+3*int'(dut.e_valid))&15;
    if(scoring&&(dut.take||dut.pop||dut.e_valid||dut.cfg_take)) mmse3_bounds_checks++;
    if(scoring&&dut.e_valid&&dut.pop) mmse3_simultaneous++;
  end
end
task automatic check_mmse3_bounds();
  if(mmse3_bounds_checks<1||dut.fifo_count!=0||dut.pending!=0)
    $fatal(1,"[BOUNDS] MMSE3 monitor not exercised or FIFO not drained");
  $display("PASS BOUNDS mmse3: %0d checks, %0d simultaneous",mmse3_bounds_checks,mmse3_simultaneous);
endtask
