// Expected records come from original spectra, independent integer inverse FFT,
// absolute-time overlap-add and window file; never from DUT RAM or arithmetic.
int raw_writes_total=0,raw_reads_total=0,raw_writes=0,raw_reads=0,raw_max_overlap=0;
longint raw_write_rows[][8],raw_read_rows[][2];
initial if($test$plusargs("CHECK_ACCUMULATOR")) begin
  string path;
  int fd,status;
  if(!$value$plusargs("VECTORS=%s",path))$fatal(1,"[ACCUMULATOR] missing vectors");
  fd=$fopen({path,"/istft_writes.txt"},"r");
  if(!fd)$fatal(1,"[ACCUMULATOR] missing write reference");
  status=$fscanf(fd,"%d",raw_writes_total);raw_write_rows=new[raw_writes_total];
  for(int row=0;row<raw_writes_total;row++)
    for(int col=0;col<8;col++)status=$fscanf(fd,"%d",raw_write_rows[row][col]);
  $fclose(fd);
  fd=$fopen({path,"/istft_reads.txt"},"r");
  if(!fd)$fatal(1,"[ACCUMULATOR] missing read reference");
  status=$fscanf(fd,"%d",raw_reads_total);raw_read_rows=new[raw_reads_total];
  for(int row=0;row<raw_reads_total;row++)
    for(int col=0;col<2;col++)status=$fscanf(fd,"%d",raw_read_rows[row][col]);
  $fclose(fd);
  if($bits(dut_synthesis.b_pre)!=PRODUCT_WIDTH||$bits(dut_synthesis.ram_q)!=2*ACC_WIDTH
      ||$bits(dut_synthesis.o_re)!=ACC_WIDTH||dut_synthesis.ring.WIDTH!=2*ACC_WIDTH)
    $fatal(1,"[ACCUMULATOR] unexpected physical widths");
end
always @(posedge clk) begin
  if(rst==RESET_ACTIVE)begin raw_writes=0;raw_reads=0;raw_max_overlap=0;end
  else if(scoring&&$test$plusargs("CHECK_ACCUMULATOR"))begin
    if(dut_synthesis.acc_take&&($signed(dut_synthesis.u_re)<-8388607||$signed(dut_synthesis.u_im)<-8388607))
      $fatal(1,"[PRODUCT] inverse FFT symmetric rail violated");
    if(dut_synthesis.write_acc)begin
      longint observed;
      if(raw_writes>=raw_writes_total)$fatal(1,"[ACCUMULATOR] extra write");
      observed=$signed(dut_synthesis.b_pre);
      if($test$plusargs("INJECT_PRODUCT"))observed++;
      if(observed!==raw_write_rows[raw_writes][3]
          ||$signed(dut_synthesis.b_pim)!==raw_write_rows[raw_writes][4])
        $fatal(1,"[PRODUCT] ISTFT exact window product differs");
      observed=$signed(dut_synthesis.ring.wr_data[2*ACC_WIDTH-1:ACC_WIDTH]);
      if($test$plusargs("INJECT_ACCUMULATOR"))observed++;
      if(int'(dut_synthesis.b_addr)!=raw_write_rows[raw_writes][0]
          ||$signed(dut_synthesis.acc_q_re)!==raw_write_rows[raw_writes][1]
          ||$signed(dut_synthesis.acc_q_im)!==raw_write_rows[raw_writes][2]
          ||observed!==raw_write_rows[raw_writes][5]
          ||$signed(dut_synthesis.ring.wr_data[ACC_WIDTH-1:0])!==raw_write_rows[raw_writes][6])
        $fatal(1,"[ACCUMULATOR] ISTFT prior or next raw sum differs");
      if(raw_write_rows[raw_writes][7]>raw_max_overlap)raw_max_overlap=int'(raw_write_rows[raw_writes][7]);
      if(raw_max_overlap>(N/HOP))$fatal(1,"[ACCUMULATOR] excessive live overlap");
      raw_writes++;
    end
    if(dut_synthesis.o_valid)begin
      longint observed;
      if(raw_reads>=raw_reads_total)$fatal(1,"[RAM_READ] extra emission");
      observed=$signed(dut_synthesis.o_re);
      if($test$plusargs("INJECT_RAM_READ"))observed++;
      if(observed!==raw_read_rows[raw_reads][0]||$signed(dut_synthesis.o_im)!==raw_read_rows[raw_reads][1])
        $fatal(1,"[RAM_READ] ISTFT raw emission differs");
      raw_reads++;
    end
  end
end
task automatic check_istft_widths();
  if(raw_writes!=raw_writes_total||raw_reads!=raw_reads_total||raw_reads!=so_total)
    $fatal(1,"[ACCUMULATOR] incomplete raw write/read coverage");
  $display("PASS ISTFT WIDTHS: %0d %0d %0d",raw_writes,raw_reads,raw_max_overlap);
endtask
