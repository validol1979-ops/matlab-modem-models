// History values and EPS come from original pin-vector files, not DUT history/power.
longint energy_re[0:(1<<LOG2N)-1],energy_im[0:(1<<LOG2N)-1];
longint energy_power=0,energy_total=0,energy_peak=0;
int energy_bits=0,energy_mantissa=0,energy_reciprocal=0;
int energy_inputs=0,energy_checks=0,energy_rom_checks=0;
initial if($bits(dut.power)!=ENERGY_WIDTH||$bits(dut.p_total)!=ENERGY_WIDTH)
  $fatal(1,"[ENERGY] unexpected physical energy widths");
always @(posedge clk) begin
  if(rst==RESET_ACTIVE)begin
    energy_power=0;energy_total=0;energy_peak=0;energy_inputs=0;energy_checks=0;energy_rom_checks=0;
    for(int k=0;k<(1<<LOG2N);k++)begin energy_re[k]=0;energy_im[k]=0;end
  end else if(scoring&&$test$plusargs("CHECK_ENERGY"))begin
    if(dut.take)begin
      if(energy_inputs>=in_total)$fatal(1,"[ENERGY] extra input");
      if(s_re!==18'(in_xre[energy_inputs])||s_im!==18'(in_xim[energy_inputs])
          ||s_dre!==18'(in_dre[energy_inputs])||s_dim!==18'(in_dim[energy_inputs])||s_last!==1'(in_last[energy_inputs]))
        $fatal(1,"[ENERGY] input differs from original pin file");
      for(int k=cfg_taps_v-1;k>0;k--)begin energy_re[k]=energy_re[k-1];energy_im[k]=energy_im[k-1];end
      energy_re[0]=in_xre[energy_inputs];energy_im[0]=in_xim[energy_inputs];energy_power=0;
      for(int k=0;k<cfg_taps_v;k++)energy_power+=energy_re[k]*energy_re[k]+energy_im[k]*energy_im[k];
      energy_total=energy_power+cfg_eps_v;energy_bits=0;
      for(int b=0;b<63;b++)if((energy_total>>b)!=0)energy_bits=b+1;
      if(cfg_nlms_v)begin
        energy_mantissa=int'(energy_total>>(energy_bits-10))-512;
        energy_reciprocal=(524288+(energy_mantissa+512)/2)/(energy_mantissa+512);
      end
      if(energy_power>energy_peak)energy_peak=energy_power;
      energy_inputs++;
    end
    if(dut.state==dut.PRODUCT)begin
      longint observed;
      observed=64'(dut.power);
      if($test$plusargs("INJECT_ENERGY"))observed++;
      if(observed!==energy_power||64'(dut.p_total)!==energy_total)
        $fatal(1,"[ENERGY] exact history energy/epsilon sum differs");
      energy_checks++;
    end
    if(cfg_nlms_v&&dut.state==dut.ERROR)begin
      int observed;
      observed=int'(dut.mantissa);
      if($test$plusargs("INJECT_MANTISSA"))observed++;
      if(int'(dut.p_bits)!=energy_bits||observed!=energy_mantissa)
        $fatal(1,"[NORMALIZATION] NLMS bit length or reciprocal address differs");
    end
    if(cfg_nlms_v&&dut.state==dut.STEP)begin
      int observed;
      observed=int'(dut.r_q);
      if($test$plusargs("INJECT_RECIPROCAL"))observed++;
      if(observed!=energy_reciprocal||int'(dut.s)!=energy_bits)
        $fatal(1,"[RECIPROCAL] NLMS ROM result or normalization exponent differs");
      energy_rom_checks++;
    end
    if(dut.state==dut.DUMP&&(!w_valid||w_ready)&&dut.dump==dut.taps)begin
      for(int k=0;k<(1<<LOG2N);k++)begin energy_re[k]=0;energy_im[k]=0;end
    end
  end
end
task automatic check_lms_energy();
  if(energy_inputs!=in_total||energy_checks!=in_total||energy_rom_checks!=(cfg_nlms_v?in_total:0))
    $fatal(1,"[ENERGY] incomplete energy/ROM observations");
  $display("PASS LMS ENERGY: %0d %0d %0d",energy_checks,energy_rom_checks,energy_peak);
endtask
