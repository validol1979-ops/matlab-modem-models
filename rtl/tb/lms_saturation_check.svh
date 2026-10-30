localparam int SAT_N=1<<LOG2N;
wire sat_done=out_total>0&&out_checked==out_total&&w_checked==w_total;
logic sat_pred_valid[0:3],sat_update_valid[0:2*SAT_N-1],sat_dump_valid[0:1];
logic signed [127:0] sat_pred_raw[0:3],sat_update_raw[0:2*SAT_N-1],sat_dump_raw[0:1];
always_comb begin
  for(int f=0;f<4;f++) begin sat_pred_valid[f]=0;sat_pred_raw[f]=0;end
  if(dut.state==dut.ERROR) begin
    for(int f=0;f<4;f++) sat_pred_valid[f]=1;
    // The DUT's own sized clamp inputs.
    sat_pred_raw[0]=128'(dut.pred_round_re);
    sat_pred_raw[1]=128'(dut.pred_round_im);
    sat_pred_raw[2]=128'(dut.error_raw_re);
    sat_pred_raw[3]=128'(dut.error_raw_im);
  end
  for(int n=0;n<SAT_N;n++) begin
    sat_update_valid[2*n]=0;sat_update_valid[2*n+1]=0;
    sat_update_raw[2*n]=0;sat_update_raw[2*n+1]=0;
    if(dut.state==dut.WEIGHT && n<int'(dut.taps)) begin
      sat_update_valid[2*n]=1;sat_update_valid[2*n+1]=1;
      sat_update_raw[2*n]=128'(dut.weight_next_re[n]);
      sat_update_raw[2*n+1]=128'(dut.weight_next_im[n]);
    end
  end
  for(int f=0;f<2;f++) begin sat_dump_valid[f]=0;sat_dump_raw[f]=0;end
  if(dut.state==dut.DUMP && (!w_valid||w_ready) && dut.dump<dut.taps) begin
    sat_dump_valid[0]=1;sat_dump_valid[1]=1;
    sat_dump_raw[0]=128'(dut.dump_round_re);
    sat_dump_raw[1]=128'(dut.dump_round_im);
  end
end
sat_group_check #(.VALUES(4),.FIELDS(4),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME("lms_pred_err"),.EXPECTED_FILE("lms_pred_err_expected.txt")) sat_pred_check
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),.valid(sat_pred_valid),.rounded(sat_pred_raw));
sat_group_check #(.VALUES(2*SAT_N),.FIELDS(2),.OUT_WIDTH(34),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME("lms_update"),.EXPECTED_FILE("lms_update_expected.txt")) sat_update_check
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),.valid(sat_update_valid),.rounded(sat_update_raw));
sat_group_check #(.VALUES(2),.FIELDS(2),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME("lms_dump"),.EXPECTED_FILE("lms_dump_expected.txt")) sat_dump_check
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),.valid(sat_dump_valid),.rounded(sat_dump_raw));
