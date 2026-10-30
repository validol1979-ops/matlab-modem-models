// Observe only active LDPC clamps: one edge in A1 and n columns in C.
int ldpc_sat_eval[0:1],ldpc_sat_pos[0:1],ldpc_sat_neg[0:1];
localparam int LDPC_NMAX=1<<LOG2NMAX;
localparam longint LDPC_HIGH=32767, LDPC_LOW=-32768;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    for(int field=0;field<2;field++) begin
      ldpc_sat_eval[field]=0;ldpc_sat_pos[field]=0;ldpc_sat_neg[field]=0;
    end
  end else if(scoring) begin
    if(dut_ldpc_decoder.state==dut_ldpc_decoder.A1) begin
      longint raw;
      if($isunknown({dut_ldpc_decoder.post[dut_ldpc_decoder.col_q],dut_ldpc_decoder.old_msg}))
        $fatal(1,"[SATURATION] LDPC active v operand unknown");
      raw=longint'($signed(dut_ldpc_decoder.post[dut_ldpc_decoder.col_q]))-
          longint'($signed(dut_ldpc_decoder.old_msg));
      ldpc_sat_eval[0]++;
      if(raw>LDPC_HIGH) ldpc_sat_pos[0]++;
      if(raw<LDPC_LOW) ldpc_sat_neg[0]++;
    end
    if(dut_ldpc_decoder.state==dut_ldpc_decoder.C) begin
      for(int column=0;column<LDPC_NMAX;column++) if(column<int'(dut_ldpc_decoder.n)) begin
        longint raw;
        if($isunknown({dut_ldpc_decoder.llr[column],dut_ldpc_decoder.acc[column]}))
          $fatal(1,"[SATURATION] LDPC active posterior operand unknown at %0d",column);
        raw=longint'($signed(dut_ldpc_decoder.llr[column]))+
            longint'($signed(dut_ldpc_decoder.acc[column]));
        ldpc_sat_eval[1]++;
        if(raw>LDPC_HIGH) ldpc_sat_pos[1]++;
        if(raw<LDPC_LOW) ldpc_sat_neg[1]++;
      end
    end
  end
end

task automatic check_ldpc_saturation();
  int fd,header,got,evaluations,positive,negative,extra,total_eval,total_events;
  fd=$fopen({directory,"/ldpc_sat_expected.txt"},"r");
  if(!fd) $fatal(1,"[SATURATION] missing LDPC expected counts");
  got=$fscanf(fd,"%d",header);
  if(got!=1||header!=2) $fatal(1,"[SATURATION] invalid LDPC count header");
  total_eval=0;total_events=0;
  for(int field=0;field<2;field++) begin
    got=$fscanf(fd,"%d %d %d",evaluations,positive,negative);
    if(got!=3||evaluations<0||positive<0||negative<0||positive+negative>evaluations)
      $fatal(1,"[SATURATION] malformed LDPC row %0d",field);
    if(field==0&&$test$plusargs("INJECT_SAT_MISMATCH")) positive++;
    if(field==0&&$test$plusargs("INJECT_SAT_EVAL_MISMATCH")) evaluations++;
    if(ldpc_sat_eval[field]!=evaluations||ldpc_sat_pos[field]!=positive||ldpc_sat_neg[field]!=negative)
      $fatal(1,"[SATURATION] LDPC field %0d eval %0d/%0d pos %0d/%0d neg %0d/%0d",field,
             ldpc_sat_eval[field],evaluations,ldpc_sat_pos[field],positive,ldpc_sat_neg[field],negative);
    total_eval+=ldpc_sat_eval[field];total_events+=ldpc_sat_pos[field]+ldpc_sat_neg[field];
  end
  if($fscanf(fd,"%d",extra)==1) $fatal(1,"[SATURATION] extra LDPC rows");
  $fclose(fd);
  $display("PASS SATURATION ldpc_sat: %0d evaluations, %0d events",total_eval,total_events);
endtask
