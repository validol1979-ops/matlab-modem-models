// Independent energy from original coefficient files; reciprocal uses integer nearest-even.
longint unsigned beam_energy_expected=0;
int beam_energy_inputs=0,beam_energy_checks=0,beam_reciprocal_checks=0;
bit beam_energy_pending=0;
longint beam_first_take=-1,beam_last_pop=-1;
longint beam_last_cfg=-1,beam_configuration_cycles=0;
initial if($bits(dut_beamform.energy)!=ENERGY_WIDTH || $bits(dut_beamform.norm.energy)!=ENERGY_WIDTH)
  $fatal(1,"[ENERGY] unexpected beam energy/reciprocal widths");
always @(posedge clk) begin
  if(rst==RESET_ACTIVE)begin
    beam_energy_expected=0;beam_energy_inputs=0;beam_energy_checks=0;beam_reciprocal_checks=0;
    beam_energy_pending=0;beam_first_take=-1;beam_last_pop=-1;
    beam_last_cfg=-1;beam_configuration_cycles=0;
  end else if(scoring&&$test$plusargs("CHECK_ENERGY"))begin
    if(beam_energy_pending)begin
      longint unsigned observed;
      observed=64'(dut_beamform.energy);
      if($test$plusargs("INJECT_ENERGY"))observed++;
      if(observed!==beam_energy_expected)$fatal(1,"[ENERGY] beam exact coefficient energy differs");
      beam_energy_checks++;beam_energy_pending=0;
    end
    if(b_cfg_valid&&b_cfg_ready)begin
      longint re,im;
      if(beam_energy_inputs>=bcfg_total)$fatal(1,"[ENERGY] extra coefficient");
      re=bcfg_re[beam_energy_inputs];im=bcfg_im[beam_energy_inputs];
      if(b_cfg_re!==18'(re)||b_cfg_im!==18'(im)||b_cfg_last!==1'(beam_energy_inputs==bcfg_total-1))
        $fatal(1,"[ENERGY] coefficient differs from original file");
      beam_energy_expected+=64'(re*re+im*im);beam_energy_inputs++;beam_energy_pending=1;
      if(b_cfg_last)beam_last_cfg=cycle;
    end
    if(dut_beamform.norm_done)begin
      logic [127:0] numerator,quotient,remainder;
      int bits,observed_shift,observed_r;
      bits=0;
      for(int b=0;b<63;b++)if((beam_energy_expected>>b)!=0)bits=b+1;
      numerator=128'd1<<(22+bits);quotient=numerator/128'(beam_energy_expected);
      remainder=numerator%128'(beam_energy_expected);
      if(2*remainder>128'(beam_energy_expected) || (2*remainder==128'(beam_energy_expected)&&quotient[0]))quotient++;
      observed_shift=int'(dut_beamform.shift);observed_r=int'(dut_beamform.r);
      if($test$plusargs("INJECT_NORMALIZATION"))observed_shift++;
      if($test$plusargs("INJECT_RECIPROCAL"))observed_r++;
      if(observed_shift!=7+bits)$fatal(1,"[NORMALIZATION] beam reciprocal shift differs");
      if(observed_r!=int'(quotient)||dut_beamform.norm_zero!==1'b0)$fatal(1,"[RECIPROCAL] beam reciprocal value differs");
      beam_reciprocal_checks++;
      beam_configuration_cycles=cycle-beam_last_cfg;
    end
    if(dut_beamform.take&&beam_first_take<0)beam_first_take=cycle;
    if(dut_beamform.pop)beam_last_pop=cycle;
  end
end
task automatic check_beam_energy();
  if(beam_energy_inputs!=bcfg_total||beam_energy_checks!=bcfg_total||beam_reciprocal_checks!=1||beam_last_pop<beam_first_take||beam_first_take<0||beam_configuration_cycles<=0)
    $fatal(1,"[ENERGY] incomplete beam energy/reciprocal observations");
  $display("PASS BEAM ENERGY: %0d %0d %0d %0d %0d",beam_energy_checks,beam_reciprocal_checks,beam_energy_expected,beam_last_pop-beam_first_take+1,beam_configuration_cycles);
endtask
