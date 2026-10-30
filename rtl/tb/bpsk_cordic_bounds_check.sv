// Static vectoring stages, not a RAM/ROM observer. Request lifetime and tags
// advance only on accepted CE operations; inactive unreset data are ignored.
module bpsk_cordic_bounds_check #(
  parameter int WIDTH=49,TAG_WIDTH=4,
  parameter bit RESET_ACTIVE=1,
  parameter string NAME="CORDIC"
)(
  input logic clk,rst,scoring,ce,s_valid,m_valid,
  input logic signed [WIDTH-1:0] s_x,s_y,
  input logic [TAG_WIDTH-1:0] s_tag,m_tag,
  input logic signed [31:0] m_phase,
  input logic [20:0] valid_pipe,zero_pipe,
  input wire signed [WIDTH+1:0] x[0:18],y[0:19],
  input wire signed [31:0] angle[0:20],
  input wire [TAG_WIDTH-1:0] tag_pipe[0:20]
);
  logic [20:0] expected_valid='0,expected_zero='0,hold_mask='0;
  logic signed [WIDTH+1:0] held_x[0:18],held_y[0:19];
  logic signed [31:0] held_angle[0:20];
  logic [TAG_WIDTH-1:0] expected_tag[0:20];
  int valid_checks=0,stage_checks=0,requests=0,responses=0,zeros=0,pauses=0,peak=0;
  always @(posedge clk)begin
    if(rst==RESET_ACTIVE)begin
      expected_valid='0;expected_zero='0;hold_mask='0;
      valid_checks=0;stage_checks=0;requests=0;responses=0;zeros=0;pauses=0;peak=0;
    end else begin
      int live;
      if($isunknown({ce,s_valid,m_valid,valid_pipe})||valid_pipe!==expected_valid||m_valid!==expected_valid[20])
        $fatal(1,"[NESTED_BOUNDS] %s CE/valid lifetime",NAME);
      live=$countones(expected_valid);if(live>peak)peak=live;
      for(int stage=0;stage<21;stage++)if(expected_valid[stage])begin
        int observed_stage;
        logic [TAG_WIDTH-1:0] observed_tag;
        observed_stage=stage;observed_tag=tag_pipe[stage];
        if(scoring&&$test$plusargs("INJECT_CORDIC_STAGE"))observed_stage=21;
        if(scoring&&$test$plusargs("INJECT_CORDIC_TAG"))observed_tag[0]=!observed_tag[0];
        if(observed_stage<0||observed_stage>=21||observed_tag!==expected_tag[stage]
           ||zero_pipe[stage]!==expected_zero[stage]||$isunknown(angle[stage]))
          $fatal(1,"[NESTED_BOUNDS] %s active stage/tag/zero lifetime",NAME);
        if(stage<19)begin if($isunknown(x[stage]))$fatal(1,"[NESTED_BOUNDS] %s active x stage",NAME);end
        if(stage<20)begin if($isunknown(y[stage]))$fatal(1,"[NESTED_BOUNDS] %s active y stage",NAME);end
        if(hold_mask[stage])begin
          logic signed [31:0] observed_angle;
          observed_angle=angle[stage];
          if(scoring&&$test$plusargs("INJECT_CORDIC_HOLD"))observed_angle[0]=!observed_angle[0];
          if(observed_angle!==held_angle[stage])$fatal(1,"[NESTED_BOUNDS] %s paused active angle",NAME);
          if(stage<19)begin if(x[stage]!==held_x[stage])$fatal(1,"[NESTED_BOUNDS] %s paused active x",NAME);end
          if(stage<20)begin if(y[stage]!==held_y[stage])$fatal(1,"[NESTED_BOUNDS] %s paused active y",NAME);end
        end
        held_angle[stage]=angle[stage];
        if(stage<19)held_x[stage]=x[stage];
        if(stage<20)held_y[stage]=y[stage];
        if(scoring)stage_checks++;
      end
      if(expected_valid[20])begin
        if($isunknown(m_phase)||m_tag!==expected_tag[20]||(expected_zero[20]&&m_phase!==32'sd0))
          $fatal(1,"[NESTED_BOUNDS] %s valid output/zero vector",NAME);
      end
      if(scoring)valid_checks++;
      if(!ce&&live>0&&scoring)pauses++;
      hold_mask=ce?'0:expected_valid;
      if(ce)begin
        if(s_valid)begin
          if($isunknown({s_x,s_y,s_tag}))$fatal(1,"[NESTED_BOUNDS] %s accepted request",NAME);
          if(scoring)requests++;
        end
        if(expected_valid[20]&&scoring)begin responses++;if(expected_zero[20])zeros++;end
        for(int stage=20;stage>0;stage--)expected_tag[stage]=expected_tag[stage-1];
        if(s_valid)expected_tag[0]=s_tag;
        expected_zero={expected_zero[19:0],s_valid&&(s_x==0&&s_y==0)};
        expected_valid={expected_valid[19:0],s_valid};
      end
    end
  end
  task automatic check_bounds;
    if(valid_checks<1||stage_checks<1||requests<1||requests!=responses||expected_valid!='0)
      $fatal(1,"[NESTED_BOUNDS] %s request lifetime not exercised/drained",NAME);
    $display("PASS NESTED CORDIC %s: %0d %0d %0d %0d %0d %0d %0d",NAME,valid_checks,stage_checks,requests,responses,zeros,pauses,peak);
  endtask
endmodule
