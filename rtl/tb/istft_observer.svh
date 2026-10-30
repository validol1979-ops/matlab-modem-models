// Included in a generate block with SYNTH_DUT macro, check_prefix and check_done.
localparam int CHECK_EW=69-(17+4+24-2*LOG2N);
logic check_in_valid[0:1],check_out_valid[0:1];
logic signed [127:0] check_in_raw[0:1],check_out_raw[0:1];
logic signed [CHECK_EW-1:0] check_rounded_re,check_rounded_im;
always_comb begin
  check_rounded_re=(`SYNTH_DUT.e2_re+CHECK_EW'(1))>>>1;
  check_rounded_im=(`SYNTH_DUT.e2_im+CHECK_EW'(1))>>>1;
  for(int f=0;f<2;f++) begin
    check_in_valid[f]=`SYNTH_DUT.take;check_out_valid[f]=`SYNTH_DUT.e2_valid;
  end
  check_in_raw[0]=128'(`SYNTH_DUT.s_re);check_in_raw[1]=128'(`SYNTH_DUT.s_im);
  check_out_raw[0]=128'(check_rounded_re);check_out_raw[1]=128'(check_rounded_im);
end
sat_group_check #(.VALUES(2),.FIELDS(2),.OUT_WIDTH(23),.RESET_ACTIVE(RESET_ACTIVE),
  .LOW_BOUND(-128'sd4194303),.HIGH_BOUND(128'sd4194303),
  .NAME({check_prefix,"_spectrum"}),.EXPECTED_FILE({check_prefix,"_spectrum_expected.txt"})) check_spectrum
  (.clk(clk),.rst(rst),.scoring(scoring),.done(check_done),.valid(check_in_valid),.rounded(check_in_raw));
sat_group_check #(.VALUES(2),.FIELDS(2),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME({check_prefix,"_output"}),.EXPECTED_FILE({check_prefix,"_output_expected.txt"})) check_output
  (.clk(clk),.rst(rst),.scoring(scoring),.done(check_done),.valid(check_out_valid),.rounded(check_out_raw));
int local_bounds_checks=0;
assign sy_bounds_checks=local_bounds_checks;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) local_bounds_checks=0;
  else begin
    if($isunknown({`SYNTH_DUT.state,`SYNTH_DUT.fifo_count,`SYNTH_DUT.inflight}))
      $fatal(1,"[BOUNDS] ISTFT unknown controls");
    if(int'(`SYNTH_DUT.fifo_count)+int'(`SYNTH_DUT.inflight)>8)
      $fatal(1,"[BOUNDS] ISTFT FIFO reservations");
    if(`SYNTH_DUT.pop && `SYNTH_DUT.fifo_count==0) $fatal(1,"[BOUNDS] ISTFT empty FIFO read");
    if(`SYNTH_DUT.e3_valid && int'(`SYNTH_DUT.fifo_count)+1-int'(`SYNTH_DUT.pop)>8)
      $fatal(1,"[BOUNDS] ISTFT FIFO write lacks space");
    if(`SYNTH_DUT.acc_take && `SYNTH_DUT.write_clear)
      $fatal(1,"[BOUNDS] ISTFT simultaneous accumulation and clearing");
    if(`SYNTH_DUT.write_acc && `SYNTH_DUT.write_clear)
      $fatal(1,"[BOUNDS] ISTFT RAM write collision");
    if(`SYNTH_DUT.emit) begin
      int observed;
      observed=int'(`SYNTH_DUT.p);
      if(scoring && $test$plusargs("INJECT_BOUND_MISMATCH")) observed=1<<LOG2HOP;
      if($isunknown({`SYNTH_DUT.p,`SYNTH_DUT.block,`SYNTH_DUT.blocks,`SYNTH_DUT.mask}) ||
          observed<0 || observed>=(1<<LOG2HOP) || `SYNTH_DUT.block>=`SYNTH_DUT.blocks || `SYNTH_DUT.mask==0)
        $fatal(1,"[BOUNDS] ISTFT emission/reciprocal address");
      if(scoring) local_bounds_checks+=1;
    end
  end
end
