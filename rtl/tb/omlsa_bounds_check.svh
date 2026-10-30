int omlsa_bounds_checks=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) omlsa_bounds_checks=0;
  else begin
    if($isunknown({dut.len_count,dut.pad.phase,dut.pad.fifo_count,dut.pad.inflight,dut.gain.state,dut.gain.k}))
      $fatal(1,"[BOUNDS] OM-LSA unknown controls");
    if(int'(dut.len_count)>4) $fatal(1,"[BOUNDS] OM-LSA length FIFO occupancy");
    if(dut.y_take&&dut.y_last&&dut.len_count==0) $fatal(1,"[BOUNDS] OM-LSA missing signal length");
    if(dut.take&&dut.s_last&&int'(dut.len_count)+1-int'(dut.y_take&&dut.y_last)>4)
      $fatal(1,"[BOUNDS] OM-LSA length FIFO write lacks space");
    if(int'(dut.pad.fifo_count)+int'(dut.pad.inflight)>4)
      $fatal(1,"[BOUNDS] reflection FIFO reservations");
    if(dut.pad.r_valid&&int'(dut.pad.fifo_count)+1-int'(dut.pad.pop)>4)
      $fatal(1,"[BOUNDS] reflection FIFO write lacks space");
    if(dut.pad.pop&&dut.pad.fifo_count==0) $fatal(1,"[BOUNDS] reflection empty FIFO read");
    if(dut.pad.issue) begin
      if($isunknown(dut.pad.index) || dut.pad.index>=dut.pad.wcount || int'(dut.pad.wcount)-int'(dut.pad.index)>(8<<LOG2N))
        $fatal(1,"[BOUNDS] reflection history unavailable or overwritten");
      if(dut.pad.phase==dut.pad.PRE && (dut.pad.index<1 || dut.pad.index>(1<<LOG2N)))
        $fatal(1,"[BOUNDS] reflection prefix index");
      if(dut.pad.phase==dut.pad.POST && (dut.pad.index<dut.pad.length-(1<<LOG2N)-1 || dut.pad.index>dut.pad.length-2))
        $fatal(1,"[BOUNDS] reflection suffix index");
      if(scoring) omlsa_bounds_checks+=1;
    end
    if(configured && (dut.nnoise<1 || dut.nnoise>16 || dut.alpha>65536))
      $fatal(1,"[BOUNDS] OM-LSA noise/alpha configuration");
    if(dut.gain.store && dut.gain.frames_in>=16) $fatal(1,"[BOUNDS] OM-LSA frame RAM write");
    if(dut.gain.state==dut.gain.PICK && dut.gain.frame_out<dut.gain.stored && dut.gain.frame_out>=16)
      $fatal(1,"[BOUNDS] OM-LSA stored frame RAM read");
    if(dut.gain.state==dut.gain.G4 || dut.gain.state==dut.gain.G11) begin
      logic [31:0] argument;
      int bits_count,mantissa;
      argument=dut.gain.state==dut.gain.G4 ? dut.gain.one_xi : dut.gain.one_t;
      bits_count=int'(dut.gain.bits(argument));
      mantissa=int'(argument>>(bits_count-12));
      if($isunknown(argument) || bits_count<17 || bits_count>32 || mantissa<2048 || mantissa>4095)
        $fatal(1,"[BOUNDS] OM-LSA reciprocal table argument");
      if(scoring) omlsa_bounds_checks+=1;
    end
    if(dut.gain.state==dut.gain.G12 && ($isunknown(dut.gain.ln_addr) || dut.gain.ln_addr>4096))
      $fatal(1,"[BOUNDS] OM-LSA logarithm table address");
  end
end
task automatic check_omlsa_bounds();
  if(omlsa_bounds_checks<1 || an_bounds_checks<1 || sy_bounds_checks<1 || an_queued!=0)
    $fatal(1,"[BOUNDS] OM-LSA monitor not exercised/drained");
  $display("PASS BOUNDS omlsa: %0d checks",omlsa_bounds_checks+an_bounds_checks+sy_bounds_checks);
endtask
