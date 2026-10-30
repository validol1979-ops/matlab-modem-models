// Observe real FIR actions before the DUT's nonblocking assignments. Memory ports
// use constant generate indices; masked lanes may still read wrapped RAM addresses.
localparam int FIR_LANES=1<<LOG2LANES;
localparam int FIR_TMAX=1<<LOG2TMAX;
localparam int FIR_RING=4*FIR_TMAX;
int fir_state_checks=0,fir_active_checks=0;
int fir_bank_checks[0:FIR_LANES-1];
int fir_simultaneous=0;
int fir_expected_fifo=0,fir_expected_reserved=0;
int fir_expected_head=0,fir_expected_tail=0;

always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    fir_state_checks=0;fir_active_checks=0;fir_simultaneous=0;
    fir_expected_fifo=0;fir_expected_reserved=0;
    fir_expected_head=0;fir_expected_tail=0;
  end else begin
    int next_fifo,next_reserved;
    bit push,pop,reserve;
    if($isunknown({dut.wcount,dut.n,dut.step,dut.steps,dut.taps,dut.tap_count,
                   dut.fifo_count,dut.reserved,dut.fifo_head,dut.fifo_tail,
                   dut.issue,dut.take,dut.cfg_take,dut.o_valid,dut.pop}))
      $fatal(1,"[BOUNDS] FIR unknown active controls");
    push=dut.o_valid;pop=dut.pop;reserve=dut.issue&&dut.first;
    if(int'(dut.fifo_count)!=fir_expected_fifo || int'(dut.reserved)!=fir_expected_reserved)
      $fatal(1,"[BOUNDS] FIR FIFO/reservation transition");
    if(int'(dut.fifo_head)!=fir_expected_head || int'(dut.fifo_tail)!=fir_expected_tail)
      $fatal(1,"[BOUNDS] FIR FIFO pointer transition");
    if(int'(dut.fifo_count)>dut.FIFO_DEPTH || int'(dut.reserved)>dut.FIFO_DEPTH || int'(dut.fifo_count)+int'(dut.reserved)>dut.FIFO_DEPTH)
      $fatal(1,"[BOUNDS] FIR FIFO reservations exceed capacity");
    if(pop&&dut.fifo_count==0) $fatal(1,"[BOUNDS] FIR empty FIFO pop");
    if(push&&dut.reserved==0) $fatal(1,"[BOUNDS] FIR output without reservation");
    if(reserve&&int'(dut.fifo_count)+int'(dut.reserved)>=dut.FIFO_DEPTH)
      $fatal(1,"[BOUNDS] FIR first step without capacity");
    next_fifo=int'(dut.fifo_count)+int'(push)-int'(pop);
    next_reserved=int'(dut.reserved)+int'(reserve)-int'(push);
    if(next_fifo<0||next_fifo>dut.FIFO_DEPTH||next_reserved<0||next_reserved>dut.FIFO_DEPTH||next_fifo+next_reserved>dut.FIFO_DEPTH)
      $fatal(1,"[BOUNDS] FIR simultaneous FIFO/reservation actions");
    fir_expected_fifo=next_fifo;fir_expected_reserved=next_reserved;
    fir_expected_head=(int'(dut.fifo_head)+int'(pop))&(dut.FIFO_DEPTH-1);
    fir_expected_tail=(int'(dut.fifo_tail)+int'(push))&(dut.FIFO_DEPTH-1);
    if(scoring&&(push||pop||reserve||dut.take||dut.cfg_take)) fir_state_checks++;
    if(scoring&&push&&pop) fir_simultaneous++;
    if(configured&&(dut.taps==0||int'(dut.taps)>FIR_TMAX))
      $fatal(1,"[BOUNDS] FIR configured tap count");
    if(dut.take&&int'(dut.wcount)-int'(dut.n)>=FIR_RING-FIR_TMAX)
      $fatal(1,"[BOUNDS] FIR history write overwrites live ring");
    if(dut.issue) begin
      int expected_steps;
      expected_steps=(int'(dut.taps)+FIR_LANES-1)/FIR_LANES;
      if(expected_steps<1||int'(dut.steps)!=expected_steps||int'(dut.step)>=expected_steps)
        $fatal(1,"[BOUNDS] FIR active tap step");
      for(int lane=0;lane<FIR_LANES;lane++) begin
        int tap_index,sample_index,observed_index;
        tap_index=int'(dut.step)*FIR_LANES+lane;
        sample_index=int'(dut.n)-tap_index;
        if(tap_index<int'(dut.taps)&&sample_index>=0&&sample_index<int'(dut.wcount)) begin
          observed_index=tap_index;
          // Corrupt only the monitor's active index; the DUT and vectors stay intact.
          if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed_index=int'(dut.taps);
          if(observed_index<0||observed_index>=int'(dut.taps)||observed_index>=FIR_TMAX)
            $fatal(1,"[BOUNDS] FIR active tap index");
          if(int'(dut.wcount)-sample_index>FIR_RING)
            $fatal(1,"[BOUNDS] FIR active history overwritten");
          if(scoring) fir_active_checks++;
        end
      end
    end
  end
end

for(genvar bank=0;bank<FIR_LANES;bank++) begin : g_fir_bounds_bank
  bit expected_i_use=0,expected_r_use=0;
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) begin
      fir_bank_checks[bank]=0;expected_i_use=0;expected_r_use=0;
    end else begin
      int tap_index,sample_index,history_address;
      bit cfg_write,hist_write;
      cfg_write=dut.cfg_take&&int'(dut.tap_count)<FIR_TMAX
                &&((int'(dut.tap_count)&(FIR_LANES-1))==bank);
      hist_write=dut.take&&((int'(dut.wcount)&(FIR_LANES-1))==bank);
      if(dut.g_bank[bank].tap_bank.wr_en!==cfg_write || dut.g_bank[bank].hist_bank.wr_en!==hist_write
         ||dut.g_bank[bank].tap_bank.rd_en!==dut.issue ||dut.g_bank[bank].hist_bank.rd_en!==dut.issue)
        $fatal(1,"[BOUNDS] FIR bank enables");
      if(cfg_write) begin
        if($isunknown(dut.g_bank[bank].tap_bank.wr_addr)
           ||int'(dut.g_bank[bank].tap_bank.wr_addr)!=(int'(dut.tap_count)>>LOG2LANES))
          $fatal(1,"[BOUNDS] FIR coefficient bank write address");
        if(scoring) fir_bank_checks[bank]++;
      end
      if(hist_write) begin
        if($isunknown(dut.g_bank[bank].hist_bank.wr_addr)
           ||int'(dut.g_bank[bank].hist_bank.wr_addr)!=((int'(dut.wcount)>>LOG2LANES)&(FIR_RING/FIR_LANES-1)))
          $fatal(1,"[BOUNDS] FIR history bank write address");
        if(scoring) fir_bank_checks[bank]++;
      end
      if(dut.issue) begin
        // Read ports are active even when the corresponding lane is masked.
        history_address=(((int'(dut.n)-bank)>>LOG2LANES)-int'(dut.step))&(FIR_RING/FIR_LANES-1);
        if($isunknown({dut.g_bank[bank].tap_bank.rd_addr,dut.g_bank[bank].hist_bank.rd_addr})
           ||int'(dut.g_bank[bank].tap_bank.rd_addr)!=int'(dut.step)
           ||int'(dut.g_bank[bank].hist_bank.rd_addr)!=history_address)
          $fatal(1,"[BOUNDS] FIR coefficient/history bank read address");
        if(scoring) fir_bank_checks[bank]++;
      end
      if(dut.i_use[bank]!==expected_i_use || dut.r_use[bank]!==expected_r_use)
        $fatal(1,"[BOUNDS] FIR active sample mask pipeline");
      expected_r_use=dut.i_use[bank];
      tap_index=int'(dut.step)*FIR_LANES+bank;
      sample_index=int'(dut.n)-tap_index;
      expected_i_use=dut.issue&&tap_index<int'(dut.taps)&&sample_index>=0&&sample_index<int'(dut.wcount);
    end
  end
end

task automatic check_fir_bounds();
  int bank_checks;
  bank_checks=0;
  for(int bank=0;bank<FIR_LANES;bank++) begin
    if(fir_bank_checks[bank]<1) $fatal(1,"[BOUNDS] FIR bank monitor not exercised");
    bank_checks+=fir_bank_checks[bank];
  end
  if(fir_active_checks<1||fir_state_checks<1||bank_checks<1)
    $fatal(1,"[BOUNDS] FIR monitor not exercised");
  if(dut.fifo_count!=0||dut.reserved!=0) $fatal(1,"[BOUNDS] FIR FIFO not drained");
  $display("PASS BOUNDS fir counts: %0d %0d %0d %0d",fir_active_checks,fir_state_checks,bank_checks,fir_simultaneous);
endtask
