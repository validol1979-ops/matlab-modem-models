// Actual frame scheduling, retained ring samples and final-flag FIFO lifetime.
int an_bounds_checks=0,an_queued=0;
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin an_bounds_checks=0;an_queued=0;end
  else begin
    bit push_flag,pop_flag;
    push_flag=!`ANALYSIS_DUT.reading && `ANALYSIS_DUT.have_frame && `ANALYSIS_DUT.next_known;
    pop_flag=`ANALYSIS_DUT.f_valid && `ANALYSIS_DUT.m_ready && `ANALYSIS_DUT.f_last;
    if($isunknown({`ANALYSIS_DUT.wcount,`ANALYSIS_DUT.frame_start,`ANALYSIS_DUT.reading,`ANALYSIS_DUT.k}))
      $fatal(1,"[BOUNDS] STFT analysis unknown controls");
    if(pop_flag && an_queued==0) $fatal(1,"[BOUNDS] STFT analysis empty flag FIFO");
    if(push_flag && an_queued+1-int'(pop_flag)>8) $fatal(1,"[BOUNDS] STFT analysis full flag FIFO");
    an_queued+=int'(push_flag)-int'(pop_flag);
    if(`ANALYSIS_DUT.issue) begin
      int observed;
      observed=int'(`ANALYSIS_DUT.k);
      if(scoring && $test$plusargs("INJECT_BOUND_MISMATCH")) observed=1<<LOG2N;
      if(observed<0 || observed>=(1<<LOG2N)) $fatal(1,"[BOUNDS] STFT window address");
      if(int'(`ANALYSIS_DUT.wcount)<=int'(`ANALYSIS_DUT.frame_start)+int'(`ANALYSIS_DUT.k) ||
         int'(`ANALYSIS_DUT.wcount)-int'(`ANALYSIS_DUT.frame_start)-int'(`ANALYSIS_DUT.k)>(2<<LOG2N))
        $fatal(1,"[BOUNDS] STFT history unavailable or overwritten");
      if(scoring) an_bounds_checks+=1;
    end
    // Window multiplication narrows; it has no saturating branch.
    if(`ANALYSIS_DUT.ce && `ANALYSIS_DUT.v2) begin
      logic signed [35:0] re,im;
      re=(36'(`ANALYSIS_DUT.p_re)+36'sd4096)>>>13;
      im=(36'(`ANALYSIS_DUT.p_im)+36'sd4096)>>>13;
      if($isunknown({re,im}) || re>2097151 || re< -2097152 || im>2097151 || im< -2097152)
        $fatal(1,"[BOUNDS] STFT window narrowing: rounded %0d,%0d products %0d,%0d",re,im,`ANALYSIS_DUT.p_re,`ANALYSIS_DUT.p_im);
    end
  end
end
