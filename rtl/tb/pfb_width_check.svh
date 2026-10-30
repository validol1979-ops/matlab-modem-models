// Reconstruct each phase from original files before rounding or saturation.
// Frame position follows file TLAST and decimation, independently of DUT indices.
int raw_frame_offset=0,raw_frame_length=0,raw_expected_end=0;
longint raw_phase_checks=0,raw_peak=0;
initial if($bits(dut.acc_re[0])!=ACC_WIDTH||$bits(dut.acc_im[0])!=ACC_WIDTH)
  $fatal(1,"[ACCUMULATOR] unexpected physical accumulator width");
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    raw_frame_offset=0;raw_frame_length=0;raw_expected_end=0;
    raw_phase_checks=0;raw_peak=0;
  end else if(scoring&&$test$plusargs("CHECK_ACCUMULATOR")&&dut.state==dut.DONE&&!dut.feeding) begin
    if(raw_frame_length==0) begin
      if(raw_frame_offset>=in_total)$fatal(1,"[ACCUMULATOR] extra output time");
      for(int q=raw_frame_offset;q<in_total;q++) begin
        raw_frame_length++;
        if(in_last[q])break;
      end
    end
    if(int'(dut.cur_end)!=raw_expected_end)$fatal(1,"[ACCUMULATOR] wrong output time");
    for(int phase=0;phase<M;phase++) begin
      longint re,im,observed,tap,xr,xi;
      re=0;im=0;
      for(int j=phase;j<tap_total&&j<=raw_expected_end;j+=M) begin
        tap=taps[j];xr=in_re[raw_frame_offset+raw_expected_end-j];
        xi=in_im[raw_frame_offset+raw_expected_end-j];
        re+=tap*xr;im+=tap*xi;
      end
      observed=$signed(dut.acc_re[phase]);
      if($test$plusargs("INJECT_ACCUMULATOR")&&phase==0)observed++;
      if(observed!==re||$signed(dut.acc_im[phase])!==im)
        $fatal(1,"[ACCUMULATOR] PFB raw phase %0d differs",phase);
      if(re>raw_peak)raw_peak=re;
      if(im>raw_peak)raw_peak=im;
      raw_phase_checks++;
    end
    raw_expected_end+=decimation;
    if(raw_expected_end>=raw_frame_length) begin
      raw_frame_offset+=raw_frame_length;raw_frame_length=0;raw_expected_end=0;
    end
  end
end
task automatic check_pfb_accumulators();
  if(raw_phase_checks!=out_total||raw_frame_offset!=in_total||raw_frame_length!=0)
    $fatal(1,"[ACCUMULATOR] incomplete raw phase coverage");
  $display("PASS PFB ACCUMULATOR: %0d %0d",raw_phase_checks,raw_peak);
endtask
