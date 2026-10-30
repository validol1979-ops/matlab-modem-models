// Simulation-only logical bounds over the real FSK accesses: the accepted config writes into
// the step tables, the step table reads taken with a label, the configured symbol index (t < n
// while a symbol is active), the RX rounding shift, the RX pending + FIFO reservations
// including a simultaneous pop/push, and the argmax staying inside the loaded tones.
// +INJECT_BOUND_MISMATCH corrupts the observed index of a real access through the same
// validator. Unreset data (n, t, shift, step contents) is only inspected when its enable
// (configured/active/take/c_valid/e_valid) is true.
int fsk_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) fsk_bounds_checks=0;
  else begin
    if($isunknown({t_configured,t_error,dut_tx.loaded,dut_tx.count,dut_tx.active,dut_tx.e_valid,dut_tx.o_valid,
                   r_configured,r_error,dut_rx.loaded,dut_rx.count,dut_rx.t,dut_rx.pending,
                   dut_rx.fifo_count,dut_rx.fifo_head,dut_rx.fifo_tail,dut_rx.a_valid,dut_rx.e_valid}))
      $fatal(1,"[BOUNDS] fsk unknown controls");
    // Accepted config write: the step table cell written must exist, and the n sampled with
    // cfg_last must be a legal symbol length whenever this transfer configures the DUT.
    if(t_cfg_valid&&t_cfg_ready) begin
      int observed;
      observed=int'(dut_tx.count);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=1<<LOG2M;
      if(observed<0||observed>=(1<<LOG2M)) $fatal(1,"[BOUNDS] fsk_tx config write address");
      if(t_cfg_last&&t_cfg_n!=0&&observed<(1<<LOG2M)
         &&(int'(t_cfg_n)<1||int'(t_cfg_n)>(1<<LOG2NMAX))) $fatal(1,"[BOUNDS] fsk_tx config n");
      if(scoring) fsk_bounds_checks+=1;
    end
    if(r_cfg_valid&&r_cfg_ready) begin
      int observed;
      observed=int'(dut_rx.count);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=1<<LOG2M;
      if(observed<0||observed>=(1<<LOG2M)) $fatal(1,"[BOUNDS] fsk_rx config write address");
      if(r_cfg_last&&r_cfg_n!=0&&observed<(1<<LOG2M)
         &&(int'(r_cfg_n)<1||int'(r_cfg_n)>(1<<LOG2NMAX))) $fatal(1,"[BOUNDS] fsk_rx config n");
      if(scoring) fsk_bounds_checks+=1;
    end
    // Step table read taken with the input label: the address must be a table cell and a
    // loaded tone (a label beyond loaded raises the DUT error instead of using the data).
    if(ts_valid&&ts_ready) begin
      int observed;
      observed=int'(ts_label);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=1<<LOG2M;
      if(observed<0||observed>=(1<<LOG2M)) $fatal(1,"[BOUNDS] fsk_tx step table read");
      if(t_error===1'b0&&observed>=int'(dut_tx.loaded)) $fatal(1,"[BOUNDS] fsk_tx label beyond loaded steps");
      if(scoring) fsk_bounds_checks+=1;
    end
    // Configured symbol index of the running transmitter: only when a symbol is active.
    if(dut_tx.active) begin
      if($isunknown({dut_tx.t,dut_tx.n})||dut_tx.n=='0||int'(dut_tx.t)>=int'(dut_tx.n))
        $fatal(1,"[BOUNDS] fsk_tx symbol index t<n");
      if(scoring&&dut_tx.emit) fsk_bounds_checks+=1;
    end
    // Symbol index of the sample the receiver accepts: configured by s_ready, so n is live.
    if(rs_valid&&rs_ready) begin
      if($isunknown({dut_rx.t,dut_rx.n})||dut_rx.n=='0||int'(dut_rx.t)>=int'(dut_rx.n))
        $fatal(1,"[BOUNDS] fsk_rx symbol index t<n");
      if(scoring) fsk_bounds_checks+=1;
    end
    // Rounding shift, only meaningful when the rounding stage consumes a snapshot.
    if(dut_rx.c_valid) begin
      if($isunknown(dut_rx.shift)||int'(dut_rx.shift)<17||int'(dut_rx.shift)>(17+LOG2NMAX))
        $fatal(1,"[BOUNDS] fsk_rx rounding shift");
      if(scoring) fsk_bounds_checks+=1;
    end
    // RX reservations: pending symbols hold FIFO space, a pop needs a nonempty FIFO and an
    // e_valid write must still fit while pop frees a slot in the same cycle.
    if(int'(dut_rx.fifo_count)+int'(dut_rx.pending)>8)
      $fatal(1,"[BOUNDS] fsk_rx pending+FIFO reservations");
    if(dut_rx.pop&&dut_rx.fifo_count=='0) $fatal(1,"[BOUNDS] fsk_rx empty FIFO read");
    if(dut_rx.e_valid&&int'(dut_rx.fifo_count)+1-int'(dut_rx.pop)>8)
      $fatal(1,"[BOUNDS] fsk_rx FIFO write lacks space");
    if(dut_rx.take&&dut_rx.symbol_end&&int'(dut_rx.fifo_count)+int'(dut_rx.pending)+1-int'(dut_rx.pop)>8)
      $fatal(1,"[BOUNDS] fsk_rx symbol reservation overflow");
    if(scoring&&(dut_rx.take||dut_rx.pop||dut_rx.e_valid)) fsk_bounds_checks+=1;
    // The decided label must be one of the loaded tones (the argmax only walks m < loaded).
    if(dut_rx.e_valid) begin
      if($isunknown(dut_rx.best_label)||int'(dut_rx.best_label)>=int'(dut_rx.loaded))
        $fatal(1,"[BOUNDS] fsk_rx label beyond loaded tones");
      if(scoring) fsk_bounds_checks+=1;
    end
  end
end
task automatic check_fsk_bounds();
  if(fsk_bounds_checks<1) $fatal(1,"[BOUNDS] fsk monitor not exercised");
  $display("PASS BOUNDS fsk: %0d checks",fsk_bounds_checks);
endtask
