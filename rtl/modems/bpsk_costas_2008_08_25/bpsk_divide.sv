// Shared restoring divider for acquisition. Exact signed nearest-even result.
// Terminal remainder comparison, rounding and sign restoration are pipelined.
module bpsk_divide #(parameter bit RESET_ACTIVE=1,parameter int STEPS_PER_CYCLE=2)(
 input logic clk,rst,start,
 input logic signed [63:0] numerator,
 input logic [31:0] denominator,
 output logic busy,done,
 output logic signed [63:0] result
);
 initial begin
  if(STEPS_PER_CYCLE!=1&&STEPS_PER_CYCLE!=2) $fatal(1,"STEPS_PER_CYCLE must be 1 or 2");
 end
 logic negative;
 logic [63:0] bits_left,quotient,rounded;
 logic [31:0] remainder,divisor;
 logic [5:0] step;
 logic finish_round,finish_sign;
 wire [32:0] trial={remainder,bits_left[63]};
 // Invariant remainder < divisor makes the signed difference fit 33 bits.
 wire [32:0] difference=trial-{1'b0,divisor};
 wire subtract=!difference[32];
 wire [31:0] next_rem=subtract?difference[31:0]:trial[31:0];
 wire [63:0] next_q={quotient[62:0],subtract};
 // Второй шаг в точности повторяет первый с его остатком и следующим битом.
 wire [32:0] trial_two={next_rem,bits_left[62]};
 wire [32:0] difference_two=trial_two-{1'b0,divisor};
 wire subtract_two=!difference_two[32];
 wire [31:0] next_rem_two=subtract_two?difference_two[31:0]:trial_two[31:0];
 wire [63:0] next_q_two={next_q[62:0],subtract_two};
 wire round_up={remainder,1'b0}>{1'b0,divisor}||({remainder,1'b0}=={1'b0,divisor}&&quotient[0]);
 always_ff @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin busy<=0;done<=0;end
  else begin
   done<=0;
   if(start&&!busy) begin
    busy<=1;negative<=numerator<0;bits_left<=numerator<0?$unsigned(-numerator):$unsigned(numerator);
    quotient<=0;remainder<=0;divisor<=denominator;step<=0;finish_round<=0;finish_sign<=0;
   end else if(busy) begin
    if(!finish_round&&!finish_sign) begin
     if(STEPS_PER_CYCLE==2) begin
      bits_left<={bits_left[61:0],2'b0};remainder<=next_rem_two;quotient<=next_q_two;step<=step+6'd2;
      if(step==62) finish_round<=1;
     end else begin
      bits_left<={bits_left[62:0],1'b0};remainder<=next_rem;quotient<=next_q;step<=step+1'b1;
      if(step==63) finish_round<=1;
     end
    end else if(finish_round) begin rounded<=quotient+{63'd0,round_up};finish_round<=0;finish_sign<=1;end
    else begin busy<=0;done<=1;result<=negative?-$signed(rounded):$signed(rounded);end
   end
  end
 end
endmodule
