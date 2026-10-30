// Register-history observer, not a RAM/ROM-address checker. References come
// solely from accepted ce && s_valid input operations and enabled-clock stages.
module bpsk_fir_bounds_check #(
  parameter bit RESET_ACTIVE=1,
  parameter string NAME="FIR"
)(
  input logic clk,rst,scoring,ce,s_valid,s_first,s_last,
  input logic signed [17:0] s_re,s_im,
  input logic [5:0] history_count,
  input logic [7:0] valid_pipe,last_pipe,
  input logic m_valid,m_last,
  input wire signed [17:0] history_re[0:31],history_im[0:31]
);
  `include "bpsk_constants.svh"
  logic [7:0] expected_valid='0,expected_last='0;
  int count=0,epoch=0;
  bit frame_open=0;
  int owner[0:31];
  logic signed [17:0] reference_re[0:31],reference_im[0:31];
  int valid_checks=0,history_checks=0,first_checks=0,pause_checks=0,last_checks=0;
  always @(posedge clk)begin
    if(rst==RESET_ACTIVE)begin
      expected_valid='0;expected_last='0;count=0;epoch=0;frame_open=0;
      valid_checks=0;history_checks=0;first_checks=0;pause_checks=0;last_checks=0;
      for(int slot=0;slot<32;slot++)begin owner[slot]=-1;reference_re[slot]='0;reference_im[slot]='0;end
    end else begin
      logic [7:0] observed_valid;
      observed_valid=valid_pipe;
      if(scoring&&!ce&&(|expected_valid)&&$test$plusargs("INJECT_FIR_VALID"))observed_valid[0]=!observed_valid[0];
      if($isunknown({ce,s_valid,history_count,observed_valid,m_valid})
         ||history_count!==6'(count)||count<0||count>32)
        $fatal(1,"[FIR_BOUNDS] %s active history count/control",NAME);
      if(observed_valid!==expected_valid||m_valid!==expected_valid[7])
        $fatal(1,"[FIR_BOUNDS] %s enabled valid pipeline",NAME);
      for(int stage=0;stage<8;stage++)if(expected_valid[stage])begin
        if(last_pipe[stage]!==expected_last[stage])$fatal(1,"[FIR_BOUNDS] %s active last pipeline",NAME);
        if(scoring)last_checks++;
      end
      if(expected_valid[7]&&m_last!==expected_last[7])$fatal(1,"[FIR_BOUNDS] %s output last marker",NAME);
      if(scoring)valid_checks++;
      if(!ce&&(|expected_valid)&&scoring)pause_checks++;
      if(ce)begin
        if(s_valid)begin
          bit used[0:31];
          if($isunknown({s_first,s_last,s_re,s_im})||s_first!==!frame_open)
            $fatal(1,"[FIR_BOUNDS] %s accepted frame first/sample",NAME);
          for(int slot=0;slot<32;slot++)used[slot]=0;
          // Exactly the static history cells used by nonzero coefficient pairs.
          // First-of-frame masks ALL old words, even when physical registers retain them.
          if(!s_first)for(int tap=0;tap<17;tap++)if(rrc_coefficient(tap)!=0)begin
            if(tap==0)begin if(count==32)used[31]=1;end
            else if(tap==16)begin if(count>=16)used[15]=1;end
            else begin
              if(count>=tap)used[tap-1]=1;
              if(count>=32-tap)used[31-tap]=1;
            end
          end
          for(int slot=0;slot<32;slot++)if(used[slot])begin
            int observed_index;
            observed_index=slot;
            if(scoring&&$test$plusargs("INJECT_FIR_INDEX"))observed_index=32;
            if(observed_index<0||observed_index>=32||observed_index>=count||owner[slot]!=epoch)
              $fatal(1,"[FIR_BOUNDS] %s active history index/lifetime",NAME);
            if(history_re[slot]!==reference_re[slot]||history_im[slot]!==reference_im[slot])
              $fatal(1,"[FIR_BOUNDS] %s active history data",NAME);
            if(scoring)history_checks+=2;
          end
          if(s_first)begin epoch++;count=1;if(scoring)first_checks++;end
          else if(count<32)count++;
          for(int slot=31;slot>0;slot--)begin
            reference_re[slot]=reference_re[slot-1];reference_im[slot]=reference_im[slot-1];owner[slot]=owner[slot-1];
          end
          reference_re[0]=s_re;reference_im[0]=s_im;owner[0]=epoch;
          frame_open=!s_last;
        end
        expected_valid={expected_valid[6:0],s_valid};
        expected_last={expected_last[6:0],s_valid?s_last:1'b0};
      end
    end
  end
  task automatic check_bounds;
    if(valid_checks<1||history_checks<1||first_checks<1||last_checks<1||expected_valid!='0||frame_open)
      $fatal(1,"[FIR_BOUNDS] %s observer not exercised/drained",NAME);
    $display("PASS FIR HISTORY %s: %0d %0d %0d %0d %0d",NAME,valid_checks,history_checks,first_checks,pause_checks,last_checks);
  endtask
endmodule
