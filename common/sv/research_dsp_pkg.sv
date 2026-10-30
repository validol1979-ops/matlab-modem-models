package research_dsp_pkg;
  import modem_dsp_pkg::*;
  `include "research_validate.svh"
  function automatic real signum(real x); return x>0 ? 1:(x<0 ? -1:0); endfunction
  function automatic samples_t transform(input samples_t x,input bit inverse=0);
    samples_t y; real angle; y=new[x.size()];
    foreach(y[k]) foreach(x[j]) begin
      angle=(inverse ? 2:-2)*PI*k*j/x.size();
      y[k]=add(y[k],scale(mul(x[j],rotation(angle)),inverse ? 1.0/x.size():1.0));
    end
    return y;
  endfunction
  function automatic samples_t fir(input samples_t x,h);
    samples_t y; y=new[x.size()+h.size()-1];
    foreach(x[k]) foreach(h[j]) y[k+j]=add(y[k+j],mul(x[k],h[j])); return y;
  endfunction
  function automatic real window_at(int k,n); return $sqrt(0.5-0.5*$cos(2*PI*(k+0.5)/n)); endfunction
  function automatic samples_t analysis_frames(input samples_t x,input int n,hop);
    samples_t y,v,z; int count; count=1+(x.size()-n)/hop; y=new[count*n];
    for(int k=0;k<count;k++) begin
      v=new[n]; foreach(v[j]) v[j]=scale(x[k*hop+j],window_at(j,n)); z=transform(v);
      foreach(z[j]) y[k*n+j]=z[j];
    end
    return y;
  endfunction
  function automatic samples_t synthesis(input samples_t x,input int n,hop);
    samples_t y,v,z; taps_t norm; int count; count=x.size()/n;
    y=new[(count-1)*hop+n]; norm=new[y.size()];
    for(int k=0;k<count;k++) begin
      v=new[n]; foreach(v[j]) v[j]=x[k*n+j]; z=transform(v,1);
      foreach(z[j]) begin
        y[k*hop+j]=add(y[k*hop+j],scale(z[j],window_at(j,n)));
        norm[k*hop+j]+=window_at(j,n)**2;
      end
    end
    foreach(y[k]) y[k]=scale(y[k],1/maximum(norm[k],1e-15)); return y;
  endfunction
  function automatic real e1(real x);
    real term,series,b,c,d,h,aa; x=maximum(x,1e-12);
    if(x<=1) begin
      term=1; series=0;
      for(int k=1;k<=80;k++) begin term*=-x/k; series+=term/k; end
      return -0.5772156649015328606-$ln(x)-series;
    end
    b=x+1; c=1e30; d=1/b; h=d;
    for(int k=1;k<=100;k++) begin aa=-k*k; b+=2; d=1/(aa*d+b); c=b+aa/c; h*=c*d; end
    return h*$exp(-x);
  endfunction
  function automatic complex_t interp(input samples_t x,input real pos);
    int base,idx; real mu,w[4]; complex_t value;
    base=int'($floor(pos));mu=pos-base;value=cx(0);
    w[0]=-mu*(mu-1)*(mu-2)/6;w[1]=(mu+1)*(mu-1)*(mu-2)/2;
    w[2]=-(mu+1)*mu*(mu-2)/2;w[3]=(mu+1)*mu*(mu-1)/6;
    for(int j=0;j<4;j++) begin idx=base+j-1; if(idx>=0 && idx<x.size()) value=add(value,scale(x[idx],w[j])); end
    return value;
  endfunction
  function automatic samples_t solve_linear(input samples_t matrix,rhs,input int n);
    samples_t z,y; complex_t pivot,factor,tmp; int best;
    z=new[n*(n+1)]; y=new[n];
    for(int i=0;i<n;i++) begin
      for(int j=0;j<n;j++) z[i*(n+1)+j]=matrix[i*n+j]; z[i*(n+1)+n]=rhs[i];
    end
    for(int k=0;k<n;k++) begin
      best=k;
      for(int i=k+1;i<n;i++) if(power(z[i*(n+1)+k])>power(z[best*(n+1)+k])) best=i;
      for(int j=0;j<=n;j++) begin tmp=z[k*(n+1)+j];z[k*(n+1)+j]=z[best*(n+1)+j];z[best*(n+1)+j]=tmp;end
      pivot=z[k*(n+1)+k]; if(power(pivot)<1e-24) $fatal(1,"Singular matrix");
      for(int j=k;j<=n;j++) z[k*(n+1)+j]=divide(z[k*(n+1)+j],pivot);
      for(int i=0;i<n;i++) if(i!=k) begin
        factor=z[i*(n+1)+k];for(int j=k;j<=n;j++) z[i*(n+1)+j]=sub(z[i*(n+1)+j],mul(factor,z[k*(n+1)+j]));
      end
    end
    foreach(y[i]) y[i]=z[i*(n+1)+n]; return y;
  endfunction

  function automatic samples_t execute(input int op,input taps_t p,input samples_t x,a);
    samples_t y,v,z,w,u,cov,gain,ph,newcov,matrix,rhs,spectra,cleaned;
    taps_t messages,variable,post,noise,previous;
    complex_t value,error_value,denom,tmp,early,mid,late;
    real step,energy,phase,freq,pe,pos,rate,r,c,total,mag,prod,gamma,xi,vv,gg,presence,cv,kg;
    int n,m,hop,count,mode,col,idx,bitvalue; bit valid;
    p=validated_parameters(op,p,x,a);
    case(op)
    0: y=fir(x,a);
    1: y=transform(x,p[0]!=0);
    2,20: begin
      m=$rtoi(p[0]);hop=$rtoi(p[1]);count=(x.size()+hop-1)/hop;y=new[count*m];
      for(int t=0;t<count;t++) begin
        v=new[m];
        for(int j=0;j<a.size() && j<=t*hop;j++) v[j%m]=add(v[j%m],mul(a[j],x[t*hop-j]));
        z=transform(v);
        foreach(z[k]) y[t*m+k]=mul(z[k],rotation(2*PI*k*t*hop/m));
      end
    end
    3,4,5: begin
      m=$rtoi(p[0]);n=x.size();w=new[m];u=new[m];cov=new[m*m];y=new[2*n+m];
      for(int i=0;i<m;i++) cov[i*m+i]=cx(1/p[2]);
      foreach(x[k]) begin
        for(int j=m-1;j>0;j--) u[j]=u[j-1];u[0]=x[k];value=cx(0);energy=0;
        foreach(u[j]) begin value=add(value,mul(conjg(w[j]),u[j]));energy+=power(u[j]);end
        error_value=sub(a[k],value);y[k]=value;y[n+k]=error_value;
        if(op==5) begin
          ph=new[m];foreach(ph[i]) foreach(u[j]) ph[i]=add(ph[i],mul(cov[i*m+j],u[j]));
          denom=cx(p[1]);foreach(u[j]) denom=add(denom,mul(conjg(u[j]),ph[j]));
          gain=new[m];foreach(gain[j]) begin gain[j]=divide(ph[j],denom);w[j]=add(w[j],mul(gain[j],conjg(error_value)));end
          newcov=new[m*m];
          for(int i=0;i<m;i++) for(int j=0;j<m;j++) begin
            tmp=cx(0);for(int k2=0;k2<m;k2++) tmp=add(tmp,mul(conjg(u[k2]),cov[k2*m+j]));
            newcov[i*m+j]=scale(sub(cov[i*m+j],mul(gain[i],tmp)),1/p[1]);
          end
          cov=newcov;
        end else begin
          step=op==4 ? p[1]/(p[2]+energy):p[1];
          foreach(w[j]) w[j]=add(w[j],scale(mul(u[j],conjg(error_value)),step));
        end
      end
      foreach(w[j]) y[2*n+j]=w[j];
    end
    6: begin
      m=$rtoi(p[0]);n=$rtoi(p[1]);mode=$rtoi(p[3]);messages=new[m*n];post=new[n];y=new[2*n];
      foreach(post[j]) post[j]=x[j].re;
      for(int it=0;it<$rtoi(p[2]);it++) begin
        variable=new[m*n];for(int i=0;i<m;i++) for(int j=0;j<n;j++) variable[i*n+j]=post[j]-messages[i*n+j];
        for(int i=0;i<m;i++) for(int j=0;j<n;j++) if(a[i*n+j].re!=0) begin
          prod=1;mag=1e300;
          for(int k=0;k<n;k++) if(k!=j && a[i*n+k].re!=0) begin
            vv=variable[i*n+k];
            if(mode==0) begin r=$exp(-absolute(vv));prod*=signum(vv)*(1-r)/(1+r);end
            else begin prod*=signum(vv);if(absolute(vv)<mag) mag=absolute(vv);end
          end
          if(mode==0) begin prod=clip(prod,-1+1e-12,1-1e-12);messages[i*n+j]=$ln((1+prod)/(1-prod));end
          else begin
            if(mode==2) mag*=p[4];if(mode==3) mag=maximum(0,mag-p[5]);messages[i*n+j]=prod*mag;
          end
        end
        for(int j=0;j<n;j++) begin post[j]=x[j].re;for(int i=0;i<m;i++) post[j]+=messages[i*n+j];y[j]=cx(post[j]<0 ? 1:0);end
        valid=1;
        for(int i=0;i<m;i++) begin bitvalue=0;for(int j=0;j<n;j++) if(a[i*n+j].re!=0) bitvalue^=int'(y[j].re);if(bitvalue!=0) valid=0;end
        if(valid) break;
      end
      foreach(post[j]) y[n+j]=cx(post[j]);
    end
    7: y=analysis_frames(x,$rtoi(p[0]),$rtoi(p[1]));
    8: y=synthesis(x,$rtoi(p[0]),$rtoi(p[1]));
    9: begin
      n=$rtoi(p[0]);hop=$rtoi(p[1]);v=new[x.size()+2*n];
      // Отражаем края перед оконной обработкой и удаляем добавленные отсчёты после неё.
      foreach(v[k]) begin
        if(k<n) v[k]=x[n-k];
        else if(k<n+x.size()) v[k]=x[k-n];
        else v[k]=x[2*x.size()+n-k-2];
      end
      spectra=analysis_frames(v,n,hop);count=spectra.size()/n;
      noise=new[n];previous=new[n];cleaned=new[spectra.size()];
      for(int j=0;j<n;j++) begin
        for(int k=0;k<$rtoi(p[2]);k++) noise[j]+=power(spectra[k*n+j])/p[2];
        noise[j]=maximum(noise[j],1e-9);previous[j]=1;
      end
      for(int k=0;k<count;k++) for(int j=0;j<n;j++) begin
        gamma=power(spectra[k*n+j])/noise[j];xi=maximum(p[3]*previous[j]+(1-p[3])*maximum(gamma-1,0),1e-5);
        vv=gamma*xi/(1+xi);gg=clip(xi/(1+xi)*$exp(0.5*e1(vv)),0.05,1);
        presence=1/(1+0.25*(1+xi)*$exp(-vv));gg=$exp(presence*$ln(gg)+(1-presence)*$ln(0.05));
        cleaned[k*n+j]=scale(spectra[k*n+j],gg);previous[j]=power(cleaned[k*n+j])/noise[j];
      end
      z=synthesis(cleaned,n,hop);y=new[x.size()];foreach(y[k]) y[k]=z[n+k];
    end
    10: begin
      m=$rtoi(p[0]);y=new[x.size()/m];energy=0;foreach(a[j]) energy+=power(a[j]);
      foreach(y[k]) begin for(int j=0;j<m;j++) y[k]=add(y[k],mul(x[k*m+j],conjg(a[j])));y[k]=scale(y[k],1/energy);end
    end
    11: begin
      m=$rtoi(p[0]);matrix=new[m*m];y=new[x.size()];
      for(int i=0;i<m;i++) for(int j=0;j<m;j++) begin
        for(int k=0;k<m;k++) matrix[i*m+j]=add(matrix[i*m+j],mul(conjg(a[k*m+i]),a[k*m+j]));
        if(i==j) matrix[i*m+j]=add(matrix[i*m+j],cx(p[1]));
      end
      for(int t=0;t<x.size()/m;t++) begin
        rhs=new[m];for(int i=0;i<m;i++) for(int j=0;j<m;j++) rhs[i]=add(rhs[i],mul(conjg(a[j*m+i]),x[t*m+j]));
        v=solve_linear(matrix,rhs,m);foreach(v[j]) y[t*m+j]=v[j];
      end
    end
    12: begin
      n=$rtoi(p[0]);m=$rtoi(p[1]);count=x.size()/n;y=new[count*(n+m)];
      for(int k=0;k<count;k++) begin
        v=new[n];foreach(v[j]) v[j]=x[k*n+j];z=transform(v,1);
        for(int j=0;j<n+m;j++) y[k*(n+m)+j]=scale(z[modulo(j-m,n)],$sqrt(real'(n)));
      end
    end
    13: begin
      n=$rtoi(p[0]);m=$rtoi(p[1]);count=x.size()/(n+m);y=new[count*n];
      for(int k=0;k<count;k++) begin
        v=new[n];foreach(v[j]) v[j]=x[k*(n+m)+m+j];z=transform(v);
        foreach(z[j]) y[k*n+j]=scale(z[j],1/$sqrt(real'(n)));
      end
    end
    14: begin
      n=$rtoi(p[0]);y=new[x.size()*n];foreach(x[k]) for(int j=0;j<n;j++) y[k*n+j]=rotation(2*PI*(p[1]+x[k].re*p[2])*j/n);
    end
    15: begin
      n=$rtoi(p[0]);m=$rtoi(p[3]);y=new[x.size()/n];
      foreach(y[k]) begin
        energy=-1;idx=0;
        for(int s=0;s<m;s++) begin
          value=cx(0);for(int j=0;j<n;j++) value=add(value,mul(x[k*n+j],rotation(-2*PI*(p[1]+s*p[2])*j/n)));
          if(power(value)>energy) begin energy=power(value);idx=s;end
        end
        y[k]=cx(idx);
      end
    end
    16: begin
      n=x.size();y=new[2*n];phase=0;freq=0;
      foreach(x[k]) begin
        value=mul(x[k],rotation(-phase));pe=signum(value.re)*value.im-signum(value.im)*value.re;
        y[k]=value;y[n+k]=cx(phase);freq+=p[1]*pe;phase+=freq+p[0]*pe;
      end
    end
    17: begin
      n=$rtoi(p[1]);y=new[2*n];pos=p[2];rate=0;
      for(int k=0;k<n;k++) begin
        early=interp(x,pos-p[0]/2);mid=interp(x,pos);late=interp(x,pos+p[0]/2);
        tmp=mul(sub(late,early),conjg(mid));pe=clip(tmp.re,-1,1);y[k]=mid;y[n+k]=cx(pos);
        rate+=p[4]*pe;pos+=p[0]+rate+p[3]*pe;
      end
    end
    18: begin
      c=$cos(2*PI*p[0]);r=p[1];y=new[x.size()];
      foreach(x[k]) begin
        y[k]=x[k];if(k>0) y[k]=add(y[k],add(scale(x[k-1],-2*c),scale(y[k-1],2*r*c)));
        if(k>1) y[k]=add(y[k],sub(x[k-2],scale(y[k-2],r*r)));
      end
    end
    19: begin
      value=cx(0);cv=p[2];y=new[x.size()];
      foreach(x[k]) begin cv+=p[0];kg=cv/(cv+p[1]);value=add(value,scale(sub(x[k],value),kg));cv*=1-kg;y[k]=value;end
    end
    21: begin
      n=$rtoi(p[0]);y=new[n];total=0;
      foreach(y[k]) begin
        vv=k-(n-1)/2.0;r=absolute(vv)<1e-12 ? 1:$sin(2*PI*p[1]*vv)/(2*PI*p[1]*vv);
        y[k]=cx(2*p[1]*r*(0.54-0.46*$cos(2*PI*k/(n-1))));total+=y[k].re;
      end
      foreach(y[k]) y[k]=scale(y[k],1/total);
    end
    22: begin
      y=new[x.size()];energy=power(a[0])+power(a[1]);
      for(int k=0;k<x.size()/2;k++) begin
        y[2*k]=scale(add(mul(conjg(a[0]),x[2*k]),mul(a[1],conjg(x[2*k+1]))),1/energy);
        y[2*k+1]=scale(sub(mul(conjg(a[1]),x[2*k]),mul(a[0],conjg(x[2*k+1]))),1/energy);
      end
    end
    23: begin
      m=$rtoi(p[0]);n=$rtoi(p[1]);y=new[m+n];
      for(int i=0;i<m;i++) begin bitvalue=0;for(int j=0;j<n;j++) bitvalue^=(int'(a[i*n+j].re)&int'(x[j].re));y[i]=cx(bitvalue);end
      foreach(x[j]) y[m+j]=x[j];
    end
    default: $fatal(1,"Unknown DSP operation %0d",op);
    endcase
    return y;
  endfunction
endpackage
