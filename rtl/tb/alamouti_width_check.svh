// Each pipeline stage is indexed independently into the original input/configuration files.
longint unsigned al_energy_expected=0;
int al_cfg_inputs=0,al_energy_checks=0,al_reciprocal_checks=0,al_data_inputs=0;
int al_product_pairs=0,al_sum_pairs=0,al_scale_pairs=0,al_expected_r=0,al_expected_shift=0;
bit al_energy_pending=0;
longint al_sum_max=0,al_sum_min=0,al_scale_peak=0;
longint al_first_take=-1,al_last_pop=-1,al_last_cfg=-1,al_configuration_cycles=0;
initial if($bits(dut_alamouti.energy)!=AL_ENERGY_WIDTH || $bits(dut_alamouti.norm.energy)!=AL_ENERGY_WIDTH
    || $bits(dut_alamouti.y0r)!=AL_SUM_WIDTH || $bits(dut_alamouti.q0r)!=AL_SCALE_WIDTH || $bits(dut_alamouti.p[0])!=36)
  $fatal(1,"[WIDTH] unexpected Alamouti physical widths");
function automatic longint al_product(input int pair_index,term);
  longint h0r,h0i,h1r,h1i,ar,ai,br,bi;
  h0r=acfg_re[0];h0i=acfg_im[0];h1r=acfg_re[1];h1i=acfg_im[1];
  ar=ai_re[2*pair_index];ai=ai_im[2*pair_index];br=ai_re[2*pair_index+1];bi=ai_im[2*pair_index+1];
  case(term)
    0:return h0r*ar;1:return h0i*ai;2:return h1r*br;3:return h1i*bi;
    4:return h0r*ai;5:return h0i*ar;6:return h1i*br;7:return h1r*bi;
    8:return h1r*ar;9:return h1i*ai;10:return h0r*br;11:return h0i*bi;
    12:return h1r*ai;13:return h1i*ar;14:return h0i*br;15:return h0r*bi;
    default:return 0;
  endcase
endfunction
function automatic longint al_raw(input int pair_index,field);
  case(field)
    0:return al_product(pair_index,0)+al_product(pair_index,1)+al_product(pair_index,2)+al_product(pair_index,3);
    1:return al_product(pair_index,4)-al_product(pair_index,5)+al_product(pair_index,6)-al_product(pair_index,7);
    2:return al_product(pair_index,8)+al_product(pair_index,9)-al_product(pair_index,10)-al_product(pair_index,11);
    3:return al_product(pair_index,12)-al_product(pair_index,13)-al_product(pair_index,14)+al_product(pair_index,15);
    default:return 0;
  endcase
endfunction
always @(posedge clk) begin
  if(rst==RESET_ACTIVE)begin
    al_energy_expected=0;al_cfg_inputs=0;al_energy_checks=0;al_reciprocal_checks=0;al_data_inputs=0;
    al_product_pairs=0;al_sum_pairs=0;al_scale_pairs=0;al_energy_pending=0;
    al_expected_r=0;al_expected_shift=0;al_sum_max=0;al_sum_min=0;al_scale_peak=0;
    al_first_take=-1;al_last_pop=-1;al_last_cfg=-1;al_configuration_cycles=0;
  end else if(scoring&&$test$plusargs("CHECK_ALAMOUTI_WIDTHS"))begin
    if(al_energy_pending)begin
      longint unsigned observed;
      observed=64'(dut_alamouti.energy);
      if($test$plusargs("INJECT_AL_ENERGY"))observed++;
      if(observed!==al_energy_expected)$fatal(1,"[ENERGY] Alamouti coefficient energy differs");
      al_energy_checks++;al_energy_pending=0;
    end
    if(a_cfg_valid&&a_cfg_ready)begin
      longint re,im;
      if(al_cfg_inputs>=acfg_total)$fatal(1,"[ENERGY] extra Alamouti coefficient");
      re=acfg_re[al_cfg_inputs];im=acfg_im[al_cfg_inputs];
      if(a_cfg_re!==18'(re)||a_cfg_im!==18'(im)||a_cfg_last!==1'(al_cfg_inputs==acfg_total-1))
        $fatal(1,"[ENERGY] Alamouti coefficient differs from original file");
      al_energy_expected+=64'(re*re+im*im);al_cfg_inputs++;al_energy_pending=1;
      if(a_cfg_last)al_last_cfg=cycle;
    end
    if(dut_alamouti.norm_done)begin
      logic [127:0] numerator,quotient,remainder;
      int bits,observed_shift,observed_r;
      bits=0;
      for(int b=0;b<63;b++)if((al_energy_expected>>b)!=0)bits=b+1;
      numerator=128'd1<<(22+bits);quotient=numerator/128'(al_energy_expected);remainder=numerator%128'(al_energy_expected);
      if(2*remainder>128'(al_energy_expected)||(2*remainder==128'(al_energy_expected)&&quotient[0]))quotient++;
      al_expected_r=int'(quotient);al_expected_shift=7+bits;
      observed_shift=int'(dut_alamouti.shift);observed_r=int'(dut_alamouti.r);
      if($test$plusargs("INJECT_AL_NORMALIZATION"))observed_shift++;
      if($test$plusargs("INJECT_AL_RECIPROCAL"))observed_r++;
      if(observed_shift!=al_expected_shift)$fatal(1,"[NORMALIZATION] Alamouti reciprocal shift differs");
      if(observed_r!=al_expected_r||dut_alamouti.norm_zero!==1'b0)$fatal(1,"[RECIPROCAL] Alamouti reciprocal differs");
      al_reciprocal_checks++;al_configuration_cycles=cycle-al_last_cfg;
    end
    if(dut_alamouti.take)begin
      if(al_data_inputs>=ai_total)$fatal(1,"[PRODUCT] extra Alamouti sample");
      if(as_re!==18'(ai_re[al_data_inputs])||as_im!==18'(ai_im[al_data_inputs])||as_last!==1'(ai_last[al_data_inputs]))
        $fatal(1,"[PRODUCT] Alamouti sample differs from original pin file");
      al_data_inputs++;
      if(al_first_take<0)al_first_take=cycle;
    end
    if(dut_alamouti.pop)al_last_pop=cycle;
    if(dut_alamouti.p_valid)begin
      if(al_product_pairs>=ai_total/2)$fatal(1,"[PRODUCT] extra Alamouti product pair");
      for(int k=0;k<16;k++)begin
        longint observed;
        observed=64'(dut_alamouti.p[k]);
        if($test$plusargs("INJECT_AL_PRODUCT")&&k==0)observed++;
        if(observed!==al_product(al_product_pairs,k))$fatal(1,"[PRODUCT] Alamouti raw product differs");
      end
      al_product_pairs++;
    end
    if(dut_alamouti.s_valid_q)begin
      longint observed[0:3];
      if(al_sum_pairs>=ai_total/2)$fatal(1,"[SUM] extra Alamouti sum pair");
      observed[0]=64'(dut_alamouti.y0r);observed[1]=64'(dut_alamouti.y0i);
      observed[2]=64'(dut_alamouti.y1r);observed[3]=64'(dut_alamouti.y1i);
      if($test$plusargs("INJECT_AL_SUM"))observed[0]++;
      for(int k=0;k<4;k++)begin
        longint expected;
        expected=al_raw(al_sum_pairs,k);
        if(observed[k]!==expected)$fatal(1,"[SUM] Alamouti raw sum differs");
        if(expected>al_sum_max)al_sum_max=expected;
        if(expected<al_sum_min)al_sum_min=expected;
      end
      al_sum_pairs++;
    end
    if(dut_alamouti.q_valid)begin
      logic signed [127:0] observed[0:3];
      if(al_scale_pairs>=ai_total/2)$fatal(1,"[SCALE] extra Alamouti scaled pair");
      observed[0]=128'(dut_alamouti.q0r);observed[1]=128'(dut_alamouti.q0i);
      observed[2]=128'(dut_alamouti.q1r);observed[3]=128'(dut_alamouti.q1i);
      if($test$plusargs("INJECT_AL_SCALE"))observed[0]++;
      for(int k=0;k<4;k++)begin
        logic signed [127:0] expected;
        longint magnitude;
        expected=128'(al_raw(al_scale_pairs,k))*128'(al_expected_r);
        if(observed[k]!==expected)$fatal(1,"[SCALE] Alamouti raw scaled product differs");
        magnitude=64'(expected<0?-expected:expected);
        if(magnitude>al_scale_peak)al_scale_peak=magnitude;
      end
      al_scale_pairs++;
    end
  end
end
task automatic check_alamouti_widths();
  if(acfg_total!=2||al_cfg_inputs!=2||al_energy_checks!=2||al_reciprocal_checks!=1||al_data_inputs!=ai_total
      ||al_product_pairs!=ai_total/2||al_sum_pairs!=ai_total/2||al_scale_pairs!=ai_total/2
      ||al_first_take<0||al_last_pop<al_first_take||al_configuration_cycles<=0)
    $fatal(1,"[WIDTH] incomplete Alamouti raw observations");
  $display("PASS ALAMOUTI WIDTHS: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
    al_energy_checks,al_reciprocal_checks,16*al_product_pairs,4*al_sum_pairs,4*al_scale_pairs,
    al_energy_expected,al_sum_max,al_sum_min,al_scale_peak,al_last_pop-al_first_take+1,al_configuration_cycles);
endtask
