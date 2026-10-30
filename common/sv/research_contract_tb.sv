module research_contract_tb;
  import modem_dsp_pkg::*;
  import research_dsp_pkg::*;
  // fscanf %f cannot portably read IEEE nonfinite values in Questa.
  function automatic real read_real(int fd);
    string token; real value;
    if($fscanf(fd,"%s",token)!=1) $fatal(1,"Truncated contract value");
    case(token.tolower())
      "nan": return $bitstoreal(64'h7ff8000000000000);
      "inf", "+inf": return $bitstoreal(64'h7ff0000000000000);
      "-inf": return $bitstoreal(64'hfff0000000000000);
      default: if($sscanf(token,"%f",value)!=1) $fatal(1,"Malformed contract value");
    endcase
    return value;
  endfunction
  initial begin
    string filename;int fd,count,selected,accepted,op,np,nx,na,ny,fields;
    taps_t p;samples_t x,a,expected,y;real error_value;
    if(!$value$plusargs("VECTORS=%s",filename) || !$value$plusargs("CASE=%d",selected)) $fatal(1,"Missing contract inputs");
    fd=$fopen(filename,"r");if(!fd) $fatal(1,"Cannot open contract inputs");
    fields=$fscanf(fd,"%d",count);
    if(fields!=1 || count<1 || selected<0 || selected>=count) $fatal(1,"Invalid contract count");
    for(int c=0;c<count;c++) begin
      fields=$fscanf(fd,"%d %d %d %d %d %d",accepted,op,np,nx,na,ny);
      if(fields!=6) $fatal(1,"Truncated contract header");
      if(np<0 || nx<0 || na<0 || ny<0) $fatal(1,"Invalid contract dimensions");
      p=new[np];x=new[nx];a=new[na];expected=new[ny];
      foreach(p[k]) p[k]=read_real(fd);
      foreach(x[k]) begin x[k].re=read_real(fd);x[k].im=read_real(fd);end
      foreach(a[k]) begin a[k].re=read_real(fd);a[k].im=read_real(fd);end
      foreach(expected[k]) begin expected[k].re=read_real(fd);expected[k].im=read_real(fd);end
      if(c==selected) begin
        y=execute(op,p,x,a);
        if(!accepted) $fatal(1,"INVALID_ACCEPTED");
        if(y.size()!=expected.size()) $fatal(1,"Contract output size mismatch");
        foreach(y[k]) begin
          error_value=$sqrt(power(sub(y[k],expected[k])));
          if(!(error_value<=1e-8*(1+$sqrt(power(expected[k]))))) $fatal(1,"Contract numeric mismatch");
        end
        $display("CONTRACT_ACCEPTED");$finish;
      end
    end
    $fatal(1,"Contract case not found");
  end
endmodule
