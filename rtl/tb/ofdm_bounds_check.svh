int ofdm_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) ofdm_bounds_checks=0;
  else begin
    if($isunknown({dut_tx.fifo_count,dut_tx.inflight,dut_tx.rpos,dut_rx.cnt}))
      $fatal(1,"[BOUNDS] OFDM unknown controls");
    if(int'(dut_tx.fifo_count)+int'(dut_tx.inflight)>4)
      $fatal(1,"[BOUNDS] OFDM TX FIFO reservations");
    if(dut_tx.pop&&dut_tx.fifo_count==0) $fatal(1,"[BOUNDS] OFDM TX empty FIFO read");
    if(dut_tx.inflight && int'(dut_tx.fifo_count)+1-int'(dut_tx.pop)>4)
      $fatal(1,"[BOUNDS] OFDM TX write lacks FIFO space");
    if(dut_rx.take) begin
      int observed;
      observed=int'(dut_rx.cnt);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=FRAME;
      if(observed<0||observed>=FRAME) $fatal(1,"[BOUNDS] OFDM RX prefix/frame index");
      if(scoring) ofdm_bounds_checks+=1;
    end
    if(dut_tx.read_issue) begin
      int expected;
      if(int'(dut_tx.rpos)>=FRAME) $fatal(1,"[BOUNDS] OFDM TX prefix/frame position");
      expected=int'(dut_tx.rpos)<CP ? N-CP+int'(dut_tx.rpos) : int'(dut_tx.rpos)-CP;
      if(expected<0 || expected>=N || int'(dut_tx.ridx)!=expected)
        $fatal(1,"[BOUNDS] OFDM TX prefix address mapping");
      if(scoring) ofdm_bounds_checks+=1;
    end
    if(dut_tx.write&&dut_tx.full[dut_tx.wbank]) $fatal(1,"[BOUNDS] OFDM TX overwrite full bank");
  end
end
task automatic check_ofdm_bounds();
  if(ofdm_bounds_checks<1) $fatal(1,"[BOUNDS] OFDM monitor not exercised");
  $display("PASS BOUNDS ofdm: %0d checks",ofdm_bounds_checks);
endtask
