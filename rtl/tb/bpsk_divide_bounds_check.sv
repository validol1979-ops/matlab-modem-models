// Progress/invariants from accepted start&&!busy, independently of DUT flags.
// The remainder invariant is checked on registered state, never on trial shift.
module bpsk_divide_bounds_check #(
  parameter bit RESET_ACTIVE=1,parameter int STEPS_PER_CYCLE=2
)(
  input logic clk,rst,scoring,start,busy,done,
  input logic signed [63:0] numerator,result,
  input logic [31:0] denominator,divisor,remainder,
  input logic [5:0] step,
  input logic finish_round,finish_sign
);
  typedef enum {IDLE,RUN,ROUND,SIGN} phase_t;
  phase_t phase=IDLE;
  bit expected_busy=0,expected_done=0;
  int expected_step=0,requests=0,responses=0,iterations=0,terminal_checks=0,ignored_starts=0;
  logic [31:0] saved_divisor;
  logic signed [63:0] expected_result;
  function automatic logic signed [63:0] reference_divide(input logic signed [63:0] n,input logic [31:0] d);
    logic [63:0] magnitude,q,r;
    logic [64:0] twice;
    magnitude=n<0?(~$unsigned(n))+64'd1:$unsigned(n);
    q=magnitude/64'(d);r=magnitude%64'(d);twice={1'b0,r}<<1;
    if(twice>65'(d)||(twice==65'(d)&&q[0]))q++;
    return n<0?-$signed(q):$signed(q);
  endfunction
  always @(posedge clk)begin
    if(rst==RESET_ACTIVE)begin
      phase=IDLE;expected_busy=0;expected_done=0;expected_step=0;
      requests=0;responses=0;iterations=0;terminal_checks=0;ignored_starts=0;
    end else begin
      int observed_step;
      logic [31:0] observed_denominator;
      if($isunknown({start,busy,done})||busy!==expected_busy||done!==expected_done)
        $fatal(1,"[NESTED_BOUNDS] divider request/busy/done lifetime");
      if(done)begin
        if(result!==expected_result)$fatal(1,"[NESTED_BOUNDS] divider nearest-even/sign result");
        if(scoring)responses++;
      end
      expected_done=0;
      if(start&&!busy)begin
        observed_denominator=denominator;
        if(scoring&&$test$plusargs("INJECT_DIVISOR_ZERO"))observed_denominator='0;
        if($isunknown({numerator,observed_denominator})||observed_denominator==0)
          $fatal(1,"[NESTED_BOUNDS] divider accepted zero/unknown divisor");
        saved_divisor=denominator;expected_result=reference_divide(numerator,denominator);
        expected_busy=1;phase=RUN;expected_step=0;if(scoring)requests++;
      end else if(busy)begin
        if($isunknown({divisor,remainder,step,finish_round,finish_sign})||divisor!==saved_divisor||remainder>=divisor)
          $fatal(1,"[NESTED_BOUNDS] divider latched divisor/registered remainder");
        if(start&&scoring)ignored_starts++;
        if(phase==RUN)begin
          observed_step=int'(step);
          if(scoring&&$test$plusargs("INJECT_DIVIDER_STEP"))observed_step=64;
          if(observed_step<0||observed_step>=64||observed_step!=expected_step||finish_round||finish_sign)
            $fatal(1,"[NESTED_BOUNDS] divider active iteration index/progress");
          if(scoring)iterations++;
          if(expected_step==64-STEPS_PER_CYCLE)begin expected_step=0;phase=ROUND;end else expected_step+=STEPS_PER_CYCLE;
        end else if(phase==ROUND)begin
          if(!finish_round||finish_sign||step!==6'd0)$fatal(1,"[NESTED_BOUNDS] divider terminal rounding state");
          phase=SIGN;if(scoring)terminal_checks++;
        end else if(phase==SIGN)begin
          if(finish_round||!finish_sign||step!==6'd0)$fatal(1,"[NESTED_BOUNDS] divider terminal sign state");
          expected_busy=0;expected_done=1;phase=IDLE;if(scoring)terminal_checks++;
        end else $fatal(1,"[NESTED_BOUNDS] divider busy outside active request");
      end
    end
  end
  task automatic check_bounds;
    if(expected_busy||expected_done||requests<1||requests!=responses||iterations!=(64/STEPS_PER_CYCLE)*requests||terminal_checks!=2*requests)
      $fatal(1,"[NESTED_BOUNDS] divider request/iteration accounting not drained");
    $display("PASS NESTED DIVIDER: %0d %0d %0d %0d %0d",requests,responses,iterations,terminal_checks,ignored_starts);
  endtask
endmodule
