package modem_dsp_pkg;
  timeunit 1ns; timeprecision 1ps;
  parameter real PI = 3.14159265358979323846;
  typedef struct {real re; real im;} complex_t;
  typedef complex_t samples_t[];
  typedef int labels_t[];
  typedef real taps_t[];

  function automatic complex_t cx(real re, real im=0.0);
    complex_t z; z.re=re; z.im=im; return z;
  endfunction
  function automatic complex_t add(complex_t a, complex_t b);
    return cx(a.re+b.re,a.im+b.im);
  endfunction
  function automatic complex_t sub(complex_t a, complex_t b);
    return cx(a.re-b.re,a.im-b.im);
  endfunction
  function automatic complex_t mul(complex_t a, complex_t b);
    return cx(a.re*b.re-a.im*b.im,a.re*b.im+a.im*b.re);
  endfunction
  function automatic complex_t scale(complex_t a, real b);
    return cx(a.re*b,a.im*b);
  endfunction
  function automatic complex_t conjg(complex_t a);
    return cx(a.re,-a.im);
  endfunction
  function automatic real power(complex_t a);
    return a.re*a.re+a.im*a.im;
  endfunction
  function automatic complex_t divide(complex_t a, complex_t b);
    return scale(mul(a,conjg(b)),1.0/power(b));
  endfunction
  function automatic complex_t rotation(real angle);
    return cx($cos(angle),$sin(angle));
  endfunction
  function automatic real clip(real a, real lo, real hi);
    return a<lo ? lo : (a>hi ? hi : a);
  endfunction
  function automatic real maximum(real a, real b);
    return a>b ? a:b;
  endfunction
  function automatic real absolute(real a);
    return a<0 ? -a:a;
  endfunction
  function automatic int modulo(int a,int b);
    return ((a%b)+b)%b;
  endfunction
  function automatic int gray_inverse(int value);
    int result;
    result=value;
    for (value=value>>1; value!=0; value=value>>1) result ^= value;
    return result;
  endfunction

  function automatic bit finite_real(real value);
    bit [63:0] bits; bits=$realtobits(value);
    return bits[62:52]!=11'h7ff;
  endfunction

  class modem_dsp;
    int family, order, differential, sps, filter_order, carrier, timing, equalizer;
    real beta, bt;
    samples_t lut;
    taps_t h;

    function new(string filename);
      int fd, fields, size;
      fd=$fopen(filename,"r");
      if (!fd) $fatal(1,"Cannot open modem configuration: %s",filename);
      fields=$fscanf(fd,"%d %d %d %d %d %d %d %d %f %f %d\n",
                     family,order,differential,sps,filter_order,carrier,timing,equalizer,beta,bt,size);
      if (fields!=11 || size<2 || size>64 || sps<2) $fatal(1,"Invalid modem configuration");
      if(!(order inside {2,4,8,16,64}) || !(family inside {[0:5]}) ||
          !(differential inside {[0:3]}) || !(carrier inside {[0:2]}) || !(timing inside {[0:1]}) ||
          !(equalizer inside {[0:2]}) || (family==5 && sps%2!=0) || ((family!=3 && family!=4) && (filter_order<=0 || filter_order%2!=0)) ||
          ((family!=3 && family!=4) && (!finite_real(beta) || beta<0 || beta>1)) ||
          (family==4 && (!finite_real(bt) || bt<=0)) ||
          (differential==2 && order%4!=0) || (differential==3 && order!=4) ||
          ((family==3 || family==4) && order!=2) || (family==5 && order!=4) ||
          size!=(differential==3 ? 8:order)) $fatal(1,"Invalid modem configuration");
      lut=new[size];
      foreach(lut[k]) begin
        if ($fscanf(fd,"%f %f\n",lut[k].re,lut[k].im)!=2) $fatal(1,"Truncated constellation");
      end
      $fclose(fd);
      foreach(lut[k]) if(!finite_real(lut[k].re) || !finite_real(lut[k].im)) $fatal(1,"Nonfinite constellation");
      if(family!=3 && family!=4) make_rrc();
    endfunction

    function void make_rrc();
      real x,norm;
      h=new[filter_order+1]; norm=0;
      foreach(h[k]) begin
        x=(real'(k)-filter_order/2.0)/sps;
        if (absolute(x)<1e-12) h[k]=1+beta*(4/PI-1);
        else if (beta>0 && absolute(absolute(4*beta*x)-1)<1e-10)
          h[k]=beta/$sqrt(2.0)*((1+2/PI)*$sin(PI/(4*beta))+(1-2/PI)*$cos(PI/(4*beta)));
        else h[k]=($sin(PI*x*(1-beta))+4*beta*x*$cos(PI*x*(1+beta)))/(PI*x*(1-(4*beta*x)**2));
        norm+=h[k]*h[k];
      end
      foreach(h[k]) h[k]/=$sqrt(norm);
    endfunction

    function void encode(input labels_t data, output labels_t ids, output samples_t symbols);
      int state, v, q, group, idx;
      state=0; ids=new[data.size()]; symbols=new[data.size()];
      foreach(data[k]) begin
        v=data[k];
        if (v<0 || v>=order) $fatal(1,"Invalid symbol index");
        case(differential)
          1: begin state=(state+(v^(v>>1)))%order; idx=state; end
          2: begin
            group=order/4; q=v/group; state=(state+(q^(q>>1)))%4;
            idx=group*state+v%group;
          end
          3: begin state=(state+2*(v^(v>>1))+1)%8; idx=state; end
          default: idx=v;
        endcase
        ids[k]=idx; symbols[k]=lut[idx];
      end
    endfunction

    function void decode(input labels_t ids, output labels_t data);
      int state,idx,group,q;
      state=0; data=new[ids.size()];
      foreach(ids[k]) begin
        idx=ids[k];
        case(differential)
          1: begin data[k]=gray_inverse(modulo(idx-state,order)); state=idx; end
          2: begin
            group=order/4; q=idx/group;
            data[k]=group*gray_inverse(modulo(q-state,4))+idx%group; state=q;
          end
          3: begin data[k]=gray_inverse(modulo(modulo(idx-state,8)-1,8)/2); state=idx; end
          default: data[k]=idx;
        endcase
      end
    endfunction

    function void transmit(input labels_t data, output samples_t wave);
      labels_t ids;
      samples_t symbols;
      taps_t pulse,freq;
      real norm,x,phase;
      if(data.size()==0) $fatal(1,"Empty transmit frame");
      encode(data,ids,symbols);
      if (family==3 || family==4) begin
        if (family==4) begin
          pulse=new[4*sps+1]; norm=0;
          foreach(pulse[k]) begin
            x=(real'(k)-2*sps)/sps;
            pulse[k]=$exp(-2*(PI*bt*x)**2/$ln(2.0)); norm+=pulse[k];
          end
          foreach(pulse[k]) pulse[k]/=norm;
        end else begin pulse=new[1]; pulse[0]=1; end
        freq=new[data.size()*sps+pulse.size()-1];
        for(int k=0;k<data.size()*sps;k++)
          foreach(pulse[j]) freq[k+j]+=(2*data[k/sps]-1)*pulse[j];
        wave=new[freq.size()]; phase=0;
        foreach(freq[k]) begin phase+=freq[k]; wave[k]=rotation(phase*PI/(2*sps)); end
      end else begin
        wave=new[data.size()*sps+h.size()-1+(family==5 ? sps/2:0)];
        foreach(symbols[k]) foreach(h[j]) begin
          if(family==5) begin
            wave[k*sps+j].re+=symbols[k].re*h[j];
            wave[k*sps+j+sps/2].im+=symbols[k].im*h[j];
          end else wave[k*sps+j]=add(wave[k*sps+j],scale(symbols[k],h[j]));
        end
      end
    endfunction

    function complex_t interpolate(const ref samples_t wave, input real position);
      int base,idx;
      real mu,w[4];
      complex_t result;
      base=int'($floor(position)); mu=position-base; result=cx(0);
      w[0]=-mu*(mu-1)*(mu-2)/6;
      w[1]=(mu+1)*(mu-1)*(mu-2)/2;
      w[2]=-(mu+1)*mu*(mu-2)/2;
      w[3]=(mu+1)*mu*(mu-1)/6;
      for(int j=0;j<4;j++) begin
        idx=base+j-1;
        if(idx>=0 && idx<wave.size()) result=add(result,scale(wave[idx],w[j]));
      end
      return result;
    endfunction

    function void fit_carrier(input samples_t wave, reference,
                              output real slope, output complex_t gain, output real mse);
      taps_t phases;
      real angle,prev,offset,mean_phase,center,covariance,variance,energy;
      complex_t ratio,value;
      if(wave.size()!=reference.size() || reference.size()<2) $fatal(1,"Invalid carrier reference");
      foreach(reference[k]) if(!finite_real(reference[k].re) || !finite_real(reference[k].im) || power(reference[k])<1e-24 || !finite_real(wave[k].re) || !finite_real(wave[k].im)) $fatal(1,"Invalid carrier reference");
      phases=new[reference.size()]; prev=0; offset=0; mean_phase=0;
      foreach(phases[k]) begin
        ratio=divide(wave[k],reference[k]); angle=$atan2(ratio.im,ratio.re);
        if(k>0) begin
          if(angle-prev>PI) offset-=2*PI;
          else if(angle-prev < -PI) offset+=2*PI;
        end
        phases[k]=angle+offset; mean_phase+=phases[k]; prev=angle;
      end
      mean_phase/=phases.size(); covariance=0; variance=0;
      foreach(phases[k]) begin
        center=k-(phases.size()-1)/2.0;
        covariance+=center*(phases[k]-mean_phase); variance+=center*center;
      end
      slope=covariance/variance; gain=cx(0); energy=0;
      foreach(reference[k]) begin
        gain=add(gain,mul(conjg(reference[k]),mul(wave[k],rotation(-slope*k))));
        energy+=power(reference[k]);
      end
      gain=scale(gain,1.0/energy); mse=0;
      if(!finite_real(gain.re) || !finite_real(gain.im) || power(gain)<1e-24) $fatal(1,"Invalid carrier gain");
      foreach(reference[k]) begin
        value=divide(mul(wave[k],rotation(-slope*k)),gain);
        mse+=power(sub(value,reference[k]));
      end
      mse/=reference.size();
    endfunction

    function int nearest(complex_t value);
      int result; real best,distance;
      result=0; best=1e300;
      foreach(lut[k]) begin
        distance=power(sub(value,lut[k]));
        if(distance<best) begin best=distance; result=k; end
      end
      return result;
    endfunction

    function void symbol_receiver(input samples_t samples, training,
                                  output labels_t data, output samples_t decoded);
      complex_t taps[7],history[7],feedback[3],past[3];
      complex_t value,target,err,corrected,tmp;
      real phase,freq,gain,energy,step,pe,sign_re;
      labels_t ids;
      int idx;
      phase=0; freq=0; gain=1;
      foreach(taps[j]) begin taps[j]=cx(j==0 ? 1:0); history[j]=cx(0); end
      foreach(past[j]) begin past[j]=cx(0); feedback[j]=cx(0); end
      ids=new[samples.size()]; decoded=new[samples.size()];
      foreach(samples[k]) begin
        corrected=scale(mul(samples[k],rotation(-phase)),gain);
        for(int j=6;j>0;j--) history[j]=history[j-1]; history[0]=corrected;
        value=corrected;
        if(equalizer!=0) begin
          value=cx(0); foreach(taps[j]) value=add(value,mul(taps[j],history[j]));
        end
        if(equalizer==2) foreach(feedback[j]) value=add(value,mul(feedback[j],past[j]));
        idx=nearest(value); target=k<training.size() ? training[k] : lut[idx]; err=sub(target,value);
        if(equalizer!=0) begin
          energy=1e-9; foreach(history[j]) energy+=power(history[j]);
          if(equalizer==2) foreach(past[j]) energy+=power(past[j]);
          step=k<training.size() ? 0.3:0.02;
          foreach(taps[j]) taps[j]=add(taps[j],scale(mul(err,conjg(history[j])),step/energy));
          if(equalizer==2) foreach(feedback[j]) feedback[j]=add(feedback[j],scale(mul(err,conjg(past[j])),step/energy));
        end
        for(int j=2;j>0;j--) past[j]=past[j-1]; past[0]=target;
        tmp=mul(value,conjg(target)); pe=clip(tmp.im/maximum(power(target),1e-12),-0.5,0.5);
        if(carrier==2 && order==2) begin
          tmp=divide(value,lut[0]); sign_re=tmp.re>0 ? 1:(tmp.re<0 ? -1:0);
          pe=clip(tmp.im*sign_re,-0.5,0.5);
        end
        if(carrier==0) phase+=0.03*pe;
        else begin freq+=0.0002*pe; phase+=freq+0.04*pe; end
        tmp=mul(err,conjg(value));
        gain*=1+0.002*clip(tmp.re/maximum(power(target),1e-12),-0.5,0.5);
        decoded[k]=value; ids[k]=idx;
      end
      decode(ids,data);
    endfunction

    function void receive(input samples_t wave, input labels_t preamble, input int count,
                          output labels_t data, output samples_t decoded,
                          output real delay, output real frequency);
      samples_t filtered,train,all_train,candidate,synchronized,reference;
      labels_t ids;
      complex_t gain,best_gain,early,mid,late,tmp,prev,current;
      real best,mse,slope,best_slope,trial,position,correction,err,train_power,total;
      int used,gdelay;
      if(preamble.size()<32 || count<preamble.size() || wave.size()<count*sps)
        $fatal(1,"Invalid receive frame");
      foreach(wave[k]) if(!finite_real(wave[k].re) || !finite_real(wave[k].im)) $fatal(1,"Nonfinite receive frame");
      foreach(preamble[k]) if(preamble[k]<0 || preamble[k]>=order) $fatal(1,"Invalid preamble label");
      if(family==5) begin
        // Сначала оцениваем канал по преамбуле, затем совмещаем ветви OQPSK.
        transmit(preamble,reference); used=(preamble.size()-4)*sps-filter_order;
        train=new[used]; candidate=new[used];
        foreach(train[k]) train[k]=reference[k+filter_order];
        best=1e300; delay=0; best_slope=0; best_gain=cx(1);
        for(int t=0;t<=8*sps;t++) begin
          foreach(candidate[k]) candidate[k]=interpolate(wave,k+filter_order+t*0.25);
          fit_carrier(candidate,train,slope,gain,mse);
          if(mse<best) begin best=mse; delay=t*0.25; best_slope=slope; best_gain=gain; end
        end
        candidate=new[wave.size()];
        foreach(candidate[k]) candidate[k]=divide(mul(interpolate(wave,k+delay),rotation(-best_slope*(k-filter_order))),best_gain);
        filtered=new[candidate.size()+h.size()-1];
        foreach(candidate[k]) foreach(h[j]) filtered[k+j]=add(filtered[k+j],scale(candidate[k],h[j]));
        synchronized=new[count];
        foreach(synchronized[k]) begin
          early=interpolate(filtered,filter_order+sps*k);
          late=interpolate(filtered,filter_order+sps*k+sps/2.0);
          synchronized[k]=cx(early.re,late.im);
        end
        encode(preamble,ids,all_train); train=new[preamble.size()-4];
        foreach(train[k]) train[k]=all_train[k];
        symbol_receiver(synchronized,train,data,decoded);
        frequency=best_slope/(2*PI); return;
      end
      if(family==3 || family==4) begin
        transmit(preamble,reference); used=(preamble.size()-4)*sps;
        train=new[used]; foreach(train[k]) train[k]=reference[k]; filtered=wave;
      end else begin
        filtered=new[wave.size()+h.size()-1];
        foreach(wave[k]) foreach(h[j]) filtered[k+j]=add(filtered[k+j],scale(wave[k],h[j]));
        encode(preamble,ids,all_train); used=all_train.size()-4;
        train=new[used]; foreach(train[k]) train[k]=all_train[k];
      end
      candidate=new[used]; best=1e300; delay=0; best_slope=0; best_gain=cx(1);
      for(int trial_index=0;trial_index<=8*sps;trial_index++) begin
        trial=trial_index*0.25;
        foreach(candidate[k]) candidate[k]=interpolate(filtered,(family>=3 ? real'(k):filter_order+real'(k)*sps)+trial);
        fit_carrier(candidate,train,slope,gain,mse);
        if(mse<best) begin best=mse; delay=trial; best_slope=slope; best_gain=gain; end
      end
      if(family>=3) begin
        gdelay=family==4 ? 2*sps:0; data=new[count]; decoded=new[count];
        prev=cx(1); total=0;
        for(int k=0;k<count*sps+gdelay;k++) begin
          current=divide(mul(interpolate(wave,k+delay),rotation(-best_slope*k)),best_gain);
          tmp=mul(current,conjg(prev)); prev=current;
          if(k>=gdelay) begin
            total+=$atan2(tmp.im,tmp.re);
            if((k-gdelay)%sps==sps-1) begin
              data[(k-gdelay)/sps]=total>=0 ? 1:0;
              decoded[(k-gdelay)/sps]=cx(total); total=0;
            end
          end
        end
        frequency=best_slope/(2*PI);
      end else begin
        synchronized=new[count]; correction=0; train_power=0;
        foreach(train[k]) train_power+=power(train[k]); train_power/=train.size();
        foreach(synchronized[k]) begin
          position=filter_order+delay+sps*k+correction;
          if(timing==1) begin
            early=interpolate(filtered,position-sps/2.0);
            mid=interpolate(filtered,position); late=interpolate(filtered,position+sps/2.0);
            tmp=mul(sub(late,early),conjg(mid));
            err=tmp.re/maximum(power(best_gain)*train_power,1e-9);
            correction+=0.015*clip(err,-1,1);
          end
          synchronized[k]=divide(mul(interpolate(filtered,position),rotation(-best_slope*k)),best_gain);
        end
        symbol_receiver(synchronized,train,data,decoded);
        frequency=best_slope/(2*PI*sps);
      end
    endfunction

    function void combine(input samples_t branch_a,branch_b, input complex_t gain_a,gain_b,
                          input real variance_a,variance_b, output samples_t combined);
      real denominator;
      complex_t value;
      if(branch_a.size()!=branch_b.size() || variance_a<=0 || variance_b<=0)
        $fatal(1,"Invalid diversity inputs");
      denominator=power(gain_a)/variance_a+power(gain_b)/variance_b;
      if(denominator<=0) $fatal(1,"Zero diversity gain");
      combined=new[branch_a.size()];
      foreach(combined[k]) begin
        value=add(scale(mul(conjg(gain_a),branch_a[k]),1/variance_a),
                  scale(mul(conjg(gain_b),branch_b[k]),1/variance_b));
        combined[k]=scale(value,1/denominator);
      end
    endfunction
  endclass
endpackage
