function automatic bit mimo_valid(taps_t p,samples_t a);
  int n,best; samples_t matrix; complex_t pivot,factor,tmp;
  n=$rtoi(p[0]);matrix=new[n*n];
  for(int i=0;i<n;i++) for(int j=0;j<n;j++) begin
    matrix[i*n+j]=cx(i==j ? p[1]:0);
    for(int t=0;t<n;t++) matrix[i*n+j]=add(matrix[i*n+j],mul(conjg(a[t*n+i]),a[t*n+j]));
    if(!finite_real(matrix[i*n+j].re) || !finite_real(matrix[i*n+j].im)) return 0;
  end
  for(int k=0;k<n;k++) begin
    best=k;
    for(int i=k+1;i<n;i++) if(power(matrix[i*n+k])>power(matrix[best*n+k])) best=i;
    for(int j=0;j<n;j++) begin tmp=matrix[k*n+j];matrix[k*n+j]=matrix[best*n+j];matrix[best*n+j]=tmp;end
    pivot=matrix[k*n+k];if(power(pivot)<1e-24) return 0;
    for(int j=k;j<n;j++) matrix[k*n+j]=divide(matrix[k*n+j],pivot);
    for(int i=k+1;i<n;i++) begin
      factor=matrix[i*n+k];for(int j=k;j<n;j++) matrix[i*n+j]=sub(matrix[i*n+j],mul(factor,matrix[k*n+j]));
    end
  end
  foreach(matrix[k]) if(!finite_real(matrix[k].re) || !finite_real(matrix[k].im)) return 0;
  return 1;
endfunction
// Создано tools/generate_validation.py; правьте контракт в генераторе.
function automatic real array_energy(samples_t a); real e=0; foreach(a[k]) e+=power(a[k]); return e; endfunction
function automatic bit binary_values(samples_t a); foreach(a[k]) if(a[k].im!=0 || !(a[k].re==0 || a[k].re==1)) return 0; return 1; endfunction
function automatic bit labels_valid(samples_t x,real order); foreach(x[k]) if(x[k].im!=0 || x[k].re!=$floor(x[k].re) || x[k].re<0 || x[k].re>=order) return 0; return 1; endfunction
function automatic bit ldpc_rows_valid(taps_t p,samples_t x,a); int count,n; n=$rtoi(p[1]); foreach(x[k]) if(x[k].im!=0) return 0; for(int row=0;row<$rtoi(p[0]);row++) begin count=0; for(int j=0;j<n;j++) count+=a[row*n+j].re==1; if(count<2) return 0; end return 1; endfunction
function automatic taps_t validated_parameters(int op,taps_t p,samples_t x,a);
  int counts[24]='{0,1,2,3,3,3,6,2,2,4,1,2,2,2,4,4,2,5,2,3,2,2,0,2}; taps_t q;
  if(op<0 || op>=24 || x.size()==0) $fatal(1,"Invalid DSP transaction");
  if(op==6 && p.size()>=4 && p.size()<6) begin q=new[6](p); if(p.size()==4) q[4]=0.8; q[5]=0.15; p=q; end
  if(p.size()!=counts[op]) $fatal(1,"Invalid DSP parameter count");
  foreach(p[k]) if(!finite_real(p[k])) $fatal(1,"Invalid DSP nonfinite parameter");
  foreach(x[k]) if(!finite_real(x[k].re) || !finite_real(x[k].im)) $fatal(1,"Invalid DSP nonfinite signal");
  foreach(a[k]) if(!finite_real(a[k].re) || !finite_real(a[k].im)) $fatal(1,"Invalid DSP nonfinite auxiliary");
  if((op==2 || op==20) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==2 || op==20) && !(p[1]>=1 && p[1]<=2147483647 && p[1]==$floor(p[1]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==3 || op==4 || op==5) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6) && !(p[1]>=1 && p[1]<=2147483647 && p[1]==$floor(p[1]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6) && !(p[2]>=1 && p[2]<=2147483647 && p[2]==$floor(p[2]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==7 || op==8 || op==9) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==7 || op==8 || op==9) && !(p[1]>=1 && p[1]<=2147483647 && p[1]==$floor(p[1]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==9) && !(p[2]>=1 && p[2]<=2147483647 && p[2]==$floor(p[2]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==10 || op==11 || op==12 || op==13 || op==14 || op==15 || op==21) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==14 || op==15) && !(p[3]>=1 && p[3]<=2147483647 && p[3]==$floor(p[3]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==17 || op==23) && !(p[0]>=1 && p[0]<=2147483647 && p[0]==$floor(p[0]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==17 || op==23) && !(p[1]>=1 && p[1]<=2147483647 && p[1]==$floor(p[1]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==0 || op==2 || op==20) && !(a.size()>0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==1) && !(p[0]==0 || p[0]==1)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==3 || op==4 || op==5) && !(a.size()==x.size() && p[1]>0 && p[2]>0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6) && !(p[3]==$floor(p[3]) && p[3]>=0 && p[3]<=3 && x.size()==p[1] && a.size()==p[0]*p[1] && p[4]>0 && p[5]>=0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6 || op==23) && !(binary_values(a))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==6) && !(ldpc_rows_valid(p,x,a))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==7 || op==8 || op==9) && !(p[1]<=p[0])) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==7) && !(x.size()>=p[0])) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==8) && !(x.size()%$rtoi(p[0])==0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==9) && !(x.size()>p[0] && p[2]<=1+$floor((x.size()+p[0])/p[1]) && p[3]>=0 && p[3]<1)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==10) && !(a.size()==p[0] && x.size()%$rtoi(p[0])==0 && array_energy(a)>=1e-24 && array_energy(a)<=1e300)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==11) && !(a.size()==p[0]*p[0] && x.size()%$rtoi(p[0])==0 && p[1]>=0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==11) && !(mimo_valid(p,a))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==12 || op==13) && !(p[1]>=0 && p[1]<=p[0] && p[1]==$floor(p[1]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==12) && !(x.size()%$rtoi(p[0])==0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==13) && !(p[0]+p[1]<=2147483647)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==13) && !(x.size()%$rtoi(p[0]+p[1])==0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==14) && !(labels_valid(x,p[3]))) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==15) && !(x.size()%$rtoi(p[0])==0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==16) && !(p[0]>=0 && p[1]>=0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==17) && !(p[0]>=2 && p[2]>=0 && p[3]>=0 && p[4]>=0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==18) && !(p[0]>=0 && p[0]<=0.5 && p[1]>=0 && p[1]<1)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==19) && !(p[0]>=0 && p[1]>0 && p[2]>=0)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==21) && !(p[0]>=2 && p[1]>0 && p[1]<0.5)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==22) && !(a.size()==2 && x.size()%2==0 && array_energy(a)>=1e-24 && array_energy(a)<=1e300)) $fatal(1,"Invalid DSP dimensions or parameters");
  if((op==23) && !(x.size()==p[1] && a.size()==p[0]*p[1] && binary_values(x))) $fatal(1,"Invalid DSP dimensions or parameters");
  return p;
endfunction
