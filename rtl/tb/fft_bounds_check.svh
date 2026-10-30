// Simulation-only checks of live FFT addresses and queue reservations, sampled
// before the DUT's NBAs. Independent control shadows update with NBAs too, so
// constant-generate stage monitors never see shadow counters from the next edge.
// Existing g_sat_mon tags describe valid sums/differences; no second tag line or
// saturation arithmetic is implemented here. Register delay lines have static
// elaborated indices; only DEPTH>16 exposes a dynamic RAM circular pointer.
localparam int FFT_BOUND_L=N-1+4*LOG2N;
int fft_expected_in=0,fft_expected_group=0,fft_expected_fill=0,fft_expected_pending=0;
int fft_expected_out=0,fft_expected_read=0,fft_expected_wbank=0,fft_expected_rbank=0;
int fft_expected_fifo=0,fft_expected_head=0,fft_expected_tail=0;
bit fft_expected_inflight=0;
bit [1:0] fft_expected_full=0;
int fft_reorder_checks=0,fft_fifo_checks=0,fft_flush_checks=0,fft_simultaneous=0;
int fft_stage_checks[0:LOG2N-1],fft_twiddle_checks[0:LOG2N-1],fft_ram_checks[0:LOG2N-1];
int fft_sum_checks[0:LOG2N-1],fft_diff_checks[0:LOG2N-1],fft_masked_checks[0:LOG2N-1];
wire fft_bound_burst_start=(fft_expected_in==0&&fft_expected_pending==0);
wire [LOG2N-1:0] fft_bound_group_now=fft_bound_burst_start?'0:LOG2N'(fft_expected_group);

function automatic int fft_bound_bitrev(input int value);
  int reversed;
  reversed=0;
  for(int b=0;b<LOG2N;b++) reversed|=((value>>b)&1)<<(LOG2N-1-b);
  return reversed;
endfunction

always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    fft_expected_in<=0;fft_expected_group<=0;fft_expected_fill<=0;fft_expected_pending<=0;
    fft_expected_out<=0;fft_expected_read<=0;fft_expected_wbank<=0;fft_expected_rbank<=0;
    fft_expected_fifo<=0;fft_expected_head<=0;fft_expected_tail<=0;fft_expected_inflight<=0;
    fft_expected_full<=0;
    fft_reorder_checks=0;fft_fifo_checks=0;fft_flush_checks=0;fft_simultaneous=0;
  end else begin
    int fill_now,next_fifo;
    bit [1:0] next_full;
    bit expected_read_issue;
    if($isunknown({dut.in_count,dut.gcount,dut.fill,dut.pending,dut.out_count,dut.ridx,
                   dut.wbank,dut.rbank,dut.full,dut.fifo_count,dut.fifo_head,dut.fifo_tail,
                   dut.inflight,dut.take,dut.bubble,dut.adv,dut.chain_valid,dut.write,dut.read_issue,dut.pop}))
      $fatal(1,"[BOUNDS] FFT unknown active controls");
    if(int'(dut.in_count)!=fft_expected_in||int'(dut.gcount)!=fft_expected_group||
       int'(dut.fill)!=fft_expected_fill||int'(dut.pending)!=fft_expected_pending)
      $fatal(1,"[BOUNDS] FFT input/group/fill/pending transition");
    if(int'(dut.fill)>FFT_BOUND_L||int'(dut.pending)>FFT_BOUND_L)
      $fatal(1,"[BOUNDS] FFT fill/pending exceeds chain latency");
    if(dut.burst_start!==fft_bound_burst_start||dut.gcount_now!==fft_bound_group_now)
      $fatal(1,"[BOUNDS] FFT burst group restart");
    fill_now=fft_bound_burst_start?0:fft_expected_fill;
    if(dut.chain_valid!==(fill_now==FFT_BOUND_L)||dut.write!==(dut.adv&&fill_now==FFT_BOUND_L))
      $fatal(1,"[BOUNDS] FFT write outside established chain");
    if(dut.take!==(s_valid&&s_ready)||dut.adv!==(dut.take||dut.bubble)||
       (dut.bubble&&dut.take)|| (dut.draining&&dut.take))
      $fatal(1,"[BOUNDS] FFT advance/take/flush controls");
    // Scored valid output tags must be exactly those consumed by reorder writes;
    // uninitialized warm-up and fully drained bubbles must never become writes.
    if(scoring&&dut.adv&&dut.write!==g_sat_mon[LOG2N-1].pipe_valid[3])
      $fatal(1,"[BOUNDS] FFT chain write versus valid pipeline tag");
    if(int'(dut.out_count)!=fft_expected_out||int'(dut.ridx)!=fft_expected_read||
       int'(dut.wbank)!=fft_expected_wbank||int'(dut.rbank)!=fft_expected_rbank||dut.full!==fft_expected_full)
      $fatal(1,"[BOUNDS] FFT reorder bank/index transition");
    if(int'(dut.fifo_count)!=fft_expected_fifo||int'(dut.fifo_head)!=fft_expected_head||
       int'(dut.fifo_tail)!=fft_expected_tail||dut.inflight!==fft_expected_inflight)
      $fatal(1,"[BOUNDS] FFT FIFO/inflight transition");
    if(int'(dut.fifo_count)>4||int'(dut.fifo_count)+int'(dut.inflight)>4)
      $fatal(1,"[BOUNDS] FFT FIFO/inflight reservation exceeds capacity");
    expected_read_issue=fft_expected_full[fft_expected_rbank]&&(fft_expected_fifo+int'(fft_expected_inflight)<4);
    if(dut.read_issue!==expected_read_issue||m_valid!==(fft_expected_fifo!=0)||dut.pop!==(m_valid&&m_ready))
      $fatal(1,"[BOUNDS] FFT reader/FIFO active controls");
    if(dut.pop&&dut.fifo_count==0) $fatal(1,"[BOUNDS] FFT empty FIFO pop");
    next_fifo=fft_expected_fifo+int'(dut.inflight)-int'(dut.pop);
    if(next_fifo<0||next_fifo>4) $fatal(1,"[BOUNDS] FFT simultaneous FIFO actions");
    if(dut.reorder.wr_en!==dut.write||dut.reorder.rd_en!==dut.read_issue)
      $fatal(1,"[BOUNDS] FFT reorder RAM enables");
    next_full=fft_expected_full;
    if(dut.write) begin
      if(dut.full[dut.wbank]!==1'b0||$isunknown(dut.reorder.wr_addr)||
         int'(dut.reorder.wr_addr)!=fft_expected_wbank*N+fft_bound_bitrev(fft_expected_out))
        $fatal(1,"[BOUNDS] FFT active reorder write address/bank ownership");
      if(scoring) fft_reorder_checks++;
      fft_expected_out<=(fft_expected_out+1)&(N-1);
      if(fft_expected_out==N-1) begin
        next_full[fft_expected_wbank]=1;
        fft_expected_wbank<=1-fft_expected_wbank;
      end
    end
    if(dut.read_issue) begin
      if(dut.full[dut.rbank]!==1'b1||$isunknown({dut.reorder.rd_addr,dut.bank_inverse[dut.rbank]})||
         int'(dut.reorder.rd_addr)!=fft_expected_rbank*N+fft_expected_read)
        $fatal(1,"[BOUNDS] FFT active reorder read address/bank ownership");
      if(scoring) fft_reorder_checks++;
      fft_expected_read<=(fft_expected_read+1)&(N-1);
      if(fft_expected_read==N-1) begin
        next_full[fft_expected_rbank]=0;
        fft_expected_rbank<=1-fft_expected_rbank;
      end
    end
    fft_expected_full<=next_full;
    fft_expected_fifo<=next_fifo;fft_expected_inflight<=dut.read_issue;
    fft_expected_head<=(fft_expected_head+int'(dut.pop))&3;
    fft_expected_tail<=(fft_expected_tail+int'(dut.inflight))&3;
    if(dut.take) fft_expected_in<=(fft_expected_in+1)&(N-1);
    if(dut.adv) begin
      fft_expected_group<=(int'(fft_bound_group_now)+1)&(N-1);
      fft_expected_fill<=fill_now==FFT_BOUND_L?fill_now:fill_now+1;
    end
    if(dut.take&&fft_expected_in==N-1) fft_expected_pending<=FFT_BOUND_L;
    else if(dut.adv&&fft_expected_pending!=0) fft_expected_pending<=fft_expected_pending-1;
    if(scoring&&(dut.read_issue||dut.inflight||dut.pop)) fft_fifo_checks++;
    if(scoring&&dut.adv&&dut.bubble) fft_flush_checks++;
    if(scoring&&dut.inflight&&dut.pop) fft_simultaneous++;
  end
end

for(genvar stage=0;stage<LOG2N;stage++) begin : g_fft_bounds_stage
  localparam int D=N>>(stage+1);
  localparam int GROUP=2*D;
  localparam int OFFSET=(N-(N>>stage)+4*stage)%N;
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) begin
      fft_stage_checks[stage]=0;fft_sum_checks[stage]=0;fft_diff_checks[stage]=0;fft_masked_checks[stage]=0;
    end else if(dut.adv) begin
      int expected_c;
      expected_c=(int'(fft_bound_group_now)-OFFSET)&(GROUP-1);
      if($isunknown({dut.g_stage[stage].c,dut.g_stage[stage].upper})||
         int'(dut.g_stage[stage].c)!=expected_c||dut.g_stage[stage].upper!==(expected_c>=D)||
         dut.g_stage[stage].line.ce!==dut.adv)
        $fatal(1,"[BOUNDS] FFT stage %0d commutator/delay enable",stage);
      if(scoring) begin
        fft_stage_checks[stage]++;
        if(g_sat_mon[stage].operation_valid) begin
          if(dut.g_stage[stage].upper) fft_sum_checks[stage]++;
          else fft_diff_checks[stage]++;
        end else fft_masked_checks[stage]++;
      end
    end
  end
  if(stage<LOG2N-1) begin : g_twiddle
    always @(posedge clk) begin
      if(rst==RESET_ACTIVE) fft_twiddle_checks[stage]=0;
      else begin
        if(dut.g_stage[stage].g_twiddle.rom.rd_en!==dut.adv)
          $fatal(1,"[BOUNDS] FFT twiddle read enable");
        if(dut.adv) begin
          int expected_c,expected_k,observed_k;
          expected_c=(int'(fft_bound_group_now)-OFFSET)&(GROUP-1);
          expected_k=expected_c>=D?0:(expected_c&(D-1))<<stage;
          if($isunknown(dut.g_stage[stage].g_twiddle.rom.rd_addr))
            $fatal(1,"[BOUNDS] FFT unknown active twiddle address");
          observed_k=int'(dut.g_stage[stage].g_twiddle.rom.rd_addr);
          // Corrupt a monitored address only for a REAL valid butterfly action.
          if(scoring&&g_sat_mon[stage].operation_valid&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed_k=N/2;
          if(observed_k<0||observed_k>=N/2||observed_k!=expected_k)
            $fatal(1,"[BOUNDS] FFT active twiddle address stage %0d",stage);
          if(scoring) fft_twiddle_checks[stage]++;
        end
      end
    end
  end else begin : g_no_twiddle
    always @(posedge clk) if(rst==RESET_ACTIVE) fft_twiddle_checks[stage]=0;
  end
  if(D>16) begin : g_ram_delay
    int expected_pointer=0;
    always @(posedge clk) begin
      if(rst==RESET_ACTIVE) begin expected_pointer<=0;fft_ram_checks[stage]=0;end
      else begin
        if($isunknown(dut.g_stage[stage].line.g_ram.wa)||
           int'(dut.g_stage[stage].line.g_ram.wa)!=expected_pointer||
           dut.g_stage[stage].line.g_ram.ram.wr_en!==dut.adv||
           dut.g_stage[stage].line.g_ram.ram.rd_en!==dut.adv)
          $fatal(1,"[BOUNDS] FFT delay RAM pointer/enable stage %0d",stage);
        if(dut.adv) begin
          int next_pointer;
          next_pointer=(expected_pointer+1)%D;
          if($isunknown({dut.g_stage[stage].line.g_ram.ram.wr_addr,dut.g_stage[stage].line.g_ram.ram.rd_addr})||
             int'(dut.g_stage[stage].line.g_ram.ram.wr_addr)!=expected_pointer||
             int'(dut.g_stage[stage].line.g_ram.ram.rd_addr)!=next_pointer)
            $fatal(1,"[BOUNDS] FFT active delay RAM addresses stage %0d",stage);
          expected_pointer<=next_pointer;
          if(scoring) fft_ram_checks[stage]++;
        end
      end
    end
  end else begin : g_static_delay
    always @(posedge clk) if(rst==RESET_ACTIVE) fft_ram_checks[stage]=0;
  end
end

task automatic check_fft_bounds();
  int stages,twiddles,ram,sums,diffs,masked;
  stages=0;twiddles=0;ram=0;sums=0;diffs=0;masked=0;
  for(int stage=0;stage<LOG2N;stage++) begin
    if(fft_stage_checks[stage]<1||fft_sum_checks[stage]<1||fft_diff_checks[stage]<1||fft_masked_checks[stage]<1)
      $fatal(1,"[BOUNDS] FFT stage monitor not exercised");
    if(stage<LOG2N-1&&fft_twiddle_checks[stage]<1) $fatal(1,"[BOUNDS] FFT twiddle monitor not exercised");
    if((N>>(stage+1))>16&&fft_ram_checks[stage]<1) $fatal(1,"[BOUNDS] FFT delay RAM monitor not exercised");
    stages+=fft_stage_checks[stage];twiddles+=fft_twiddle_checks[stage];ram+=fft_ram_checks[stage];
    sums+=fft_sum_checks[stage];diffs+=fft_diff_checks[stage];masked+=fft_masked_checks[stage];
  end
  if(fft_reorder_checks<1||fft_fifo_checks<1||fft_flush_checks<1)
    $fatal(1,"[BOUNDS] FFT reorder/FIFO/flush monitor not exercised");
  if(dut.fifo_count!=0||dut.inflight||dut.full!=0||dut.pending!=0)
    $fatal(1,"[BOUNDS] FFT reorder/FIFO/chain not drained");
  $display("PASS BOUNDS fft counts: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
           stages,twiddles,ram,fft_reorder_checks,fft_fifo_checks,sums,diffs,masked,fft_flush_checks,fft_simultaneous);
endtask
