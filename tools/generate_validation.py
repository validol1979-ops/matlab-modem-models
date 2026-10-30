#!/usr/bin/env python3
"""Генерируем одинаковый контракт входов для трёх независимых DSP-реализаций."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NAMES=['fir','dft','pfb','lms','nlms','rls','ldpc','stft','istft','omlsa','beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','costas','timing','notch','kalman','wola','wsinc','alamouti','gf2_encode']
COUNTS=[0,1,2,3,3,3,6,2,2,4,1,2,2,2,4,4,2,5,2,3,2,2,0,2]
# Выражения задаются отдельно для синтаксиса каждого языка.
RULES=[]
def rule(ops,py,mat,sv):RULES.append((ops.split(),py,mat,sv))
def positive(ops,indices):
 for i in indices:rule(ops,f'p[{i}] >= 1 and p[{i}] <= 2147483647 and p[{i}] == np.floor(p[{i}])',f'p({i+1})>=1 && p({i+1})<=2147483647 && p({i+1})==fix(p({i+1}))',f'p[{i}]>=1 && p[{i}]<=2147483647 && p[{i}]==$floor(p[{i}])')
positive('pfb wola',[0,1]);positive('lms nlms rls',[0]);positive('ldpc',[0,1,2]);positive('stft istft omlsa',[0,1]);positive('omlsa',[2]);positive('beamform mimo ofdm_tx ofdm_rx fsk_tx fsk_rx wsinc',[0]);positive('fsk_tx fsk_rx',[3]);positive('timing gf2_encode',[0,1])
rule('fir pfb wola','len(a)>0','~isempty(a)','a.size()>0')
rule('dft','p[0] in (0,1)','any(p(1)==[0 1])','p[0]==0 || p[0]==1')
rule('lms nlms rls','len(a)==len(x) and p[1]>0 and p[2]>0','numel(a)==numel(x) && p(2)>0 && p(3)>0','a.size()==x.size() && p[1]>0 && p[2]>0')
rule('ldpc','p[3] in (0,1,2,3) and len(x)==p[1] and len(a)==p[0]*p[1] and p[4]>0 and p[5]>=0','any(p(4)==0:3) && numel(x)==p(2) && numel(a)==p(1)*p(2) && p(5)>0 && p(6)>=0','p[3]==$floor(p[3]) && p[3]>=0 && p[3]<=3 && x.size()==p[1] && a.size()==p[0]*p[1] && p[4]>0 && p[5]>=0')
rule('ldpc gf2_encode','np.all(a.imag==0) and np.all((a.real==0)|(a.real==1))','all(imag(a)==0) && all(real(a)==0 | real(a)==1)','binary_values(a)')
rule('ldpc','np.all(x.imag==0) and np.all(a.real.reshape(int(p[0]),int(p[1])).sum(axis=1)>=2)','all(imag(x)==0) && all(sum(reshape(real(a),p(2),p(1)),1)>=2)','ldpc_rows_valid(p,x,a)')
rule('stft istft omlsa','p[1]<=p[0]','p(2)<=p(1)','p[1]<=p[0]')
rule('stft','len(x)>=p[0]','numel(x)>=p(1)','x.size()>=p[0]')
rule('istft','len(x)%int(p[0])==0','mod(numel(x),p(1))==0','x.size()%$rtoi(p[0])==0')
rule('omlsa','len(x)>p[0] and p[2]<=1+(len(x)+p[0])//p[1] and 0<=p[3]<1','numel(x)>p(1) && p(3)<=1+floor((numel(x)+p(1))/p(2)) && p(4)>=0 && p(4)<1','x.size()>p[0] && p[2]<=1+$floor((x.size()+p[0])/p[1]) && p[3]>=0 && p[3]<1')
rule('beamform','len(a)==p[0] and len(x)%int(p[0])==0 and 1e-24<=np.vdot(a,a).real<=1e300','numel(a)==p(1) && mod(numel(x),p(1))==0 && sum(abs(a).^2)>=1e-24 && sum(abs(a).^2)<=1e300','a.size()==p[0] && x.size()%$rtoi(p[0])==0 && array_energy(a)>=1e-24 && array_energy(a)<=1e300')
rule('mimo','len(a)==p[0]**2 and len(x)%int(p[0])==0 and p[1]>=0','numel(a)==p(1)^2 && mod(numel(x),p(1))==0 && p(2)>=0','a.size()==p[0]*p[0] && x.size()%$rtoi(p[0])==0 && p[1]>=0')
rule('mimo','mimo_valid(p,a)','mimo_valid(p,a)','mimo_valid(p,a)')
rule('ofdm_tx ofdm_rx','0<=p[1]<=p[0] and p[1]==np.floor(p[1])','p(2)>=0 && p(2)<=p(1) && p(2)==fix(p(2))','p[1]>=0 && p[1]<=p[0] && p[1]==$floor(p[1])')
rule('ofdm_tx','len(x)%int(p[0])==0','mod(numel(x),p(1))==0','x.size()%$rtoi(p[0])==0')
rule('ofdm_rx','p[0]+p[1]<=2147483647','p(1)+p(2)<=2147483647','p[0]+p[1]<=2147483647')
rule('ofdm_rx','len(x)%int(p[0]+p[1])==0','mod(numel(x),p(1)+p(2))==0','x.size()%$rtoi(p[0]+p[1])==0')
rule('fsk_tx','np.all(x.imag==0) and np.all(x.real==np.floor(x.real)) and np.all((x.real>=0)&(x.real<p[3]))','all(imag(x)==0) && all(real(x)==fix(real(x))) && all(real(x)>=0 & real(x)<p(4))','labels_valid(x,p[3])')
rule('fsk_rx','len(x)%int(p[0])==0','mod(numel(x),p(1))==0','x.size()%$rtoi(p[0])==0')
rule('costas','np.all(p>=0)','all(p>=0)','p[0]>=0 && p[1]>=0')
rule('timing','p[0]>=2 and np.all(p[2:]>=0)','p(1)>=2 && all(p(3:end)>=0)','p[0]>=2 && p[2]>=0 && p[3]>=0 && p[4]>=0')
rule('notch','0<=p[0]<=.5 and 0<=p[1]<1','p(1)>=0 && p(1)<=.5 && p(2)>=0 && p(2)<1','p[0]>=0 && p[0]<=0.5 && p[1]>=0 && p[1]<1')
rule('kalman','p[0]>=0 and p[1]>0 and p[2]>=0','p(1)>=0 && p(2)>0 && p(3)>=0','p[0]>=0 && p[1]>0 && p[2]>=0')
rule('wsinc','p[0]>=2 and 0<p[1]<.5','p(1)>=2 && p(2)>0 && p(2)<.5','p[0]>=2 && p[1]>0 && p[1]<0.5')
rule('alamouti','len(a)==2 and len(x)%2==0 and 1e-24<=np.vdot(a,a).real<=1e300','numel(a)==2 && mod(numel(x),2)==0 && sum(abs(a).^2)>=1e-24 && sum(abs(a).^2)<=1e300','a.size()==2 && x.size()%2==0 && array_energy(a)>=1e-24 && array_energy(a)<=1e300')
rule('gf2_encode','len(x)==p[1] and len(a)==p[0]*p[1] and np.all(x.imag==0) and np.all((x.real==0)|(x.real==1))','numel(x)==p(2) && numel(a)==p(1)*p(2) && all(imag(x)==0) && all(real(x)==0 | real(x)==1)','x.size()==p[1] && a.size()==p[0]*p[1] && binary_values(x)')

MIMO_PY = """

def mimo_valid(p,a):
    n=int(p[0]); h=a.reshape(n,n)
    with np.errstate(over='ignore', invalid='ignore'):
        matrix=h.conj().T@h+p[1]*np.eye(n)
    if not np.all(np.isfinite(matrix)): return False
    for k in range(n):
        best=k+int(np.argmax(abs(matrix[k:,k])))
        matrix[[k,best]]=matrix[[best,k]]
        pivot=matrix[k,k]
        if abs(pivot)<1e-12: return False
        matrix[k,k:]/=pivot
        for i in range(k+1,n): matrix[i,k:]-=matrix[i,k]*matrix[k,k:]
    return np.all(np.isfinite(matrix))
"""
MIMO_M = """
function valid=mimo_valid(p,a)
n=p(1);h=reshape(a,n,n).';matrix=h'*h+p(2)*eye(n);valid=false;
if any(~isfinite(matrix(:))),return;end
for k=1:n
  [~,offset]=max(abs(matrix(k:end,k)));best=k+offset-1;
  matrix([k best],:)=matrix([best k],:);pivot=matrix(k,k);
  if abs(pivot)<1e-12,return;end
  matrix(k,k:end)=matrix(k,k:end)/pivot;
  for i=k+1:n,matrix(i,k:end)=matrix(i,k:end)-matrix(i,k)*matrix(k,k:end);end
end
valid=all(isfinite(matrix(:)));
end
"""
MIMO_SV = """
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
"""

def main():
 py=['# Создано tools/generate_validation.py; правьте контракт в генераторе.','import numpy as np','', 'def validate(op,p,x,a):',"    if op=='ldpc' and 4<=len(p)<6: p=np.r_[p, [.8,.15][len(p)-4:]]",f'    counts=dict(zip({NAMES!r},{COUNTS!r}))',"    if op not in counts or len(p)!=counts[op] or not len(x) or not np.all(np.isfinite(np.r_[p,x,a])): raise ValueError('Invalid DSP transaction')"]
 mat=['function p=research_validate(op,p,x,a)','% Создано tools/generate_validation.py; правьте контракт в генераторе.',"if strcmp(op,'ldpc') && numel(p)>=4 && numel(p)<6, defaults=[.8 .15]; p=[p defaults(numel(p)-3:end)]; end",'names={'+','.join("'"+n+"'" for n in NAMES)+'};','counts=['+' '.join(map(str,COUNTS))+'];',"id=find(strcmp(names,op));", "if isempty(id) || numel(p)~=counts(id) || isempty(x) || ~isreal(p) || any(~isfinite([p x a])), error('Invalid DSP transaction'); end"]
 sv=['// Создано tools/generate_validation.py; правьте контракт в генераторе.', 'function automatic real array_energy(samples_t a); real e=0; foreach(a[k]) e+=power(a[k]); return e; endfunction','function automatic bit binary_values(samples_t a); foreach(a[k]) if(a[k].im!=0 || !(a[k].re==0 || a[k].re==1)) return 0; return 1; endfunction','function automatic bit labels_valid(samples_t x,real order); foreach(x[k]) if(x[k].im!=0 || x[k].re!=$floor(x[k].re) || x[k].re<0 || x[k].re>=order) return 0; return 1; endfunction','function automatic bit ldpc_rows_valid(taps_t p,samples_t x,a); int count,n; n=$rtoi(p[1]); foreach(x[k]) if(x[k].im!=0) return 0; for(int row=0;row<$rtoi(p[0]);row++) begin count=0; for(int j=0;j<n;j++) count+=a[row*n+j].re==1; if(count<2) return 0; end return 1; endfunction','function automatic taps_t validated_parameters(int op,taps_t p,samples_t x,a);',"  int counts[24]='{"+','.join(map(str,COUNTS))+'}; taps_t q;', '  if(op<0 || op>=24 || x.size()==0) $fatal(1,"Invalid DSP transaction");', '  if(op==6 && p.size()>=4 && p.size()<6) begin q=new[6](p); if(p.size()==4) q[4]=0.8; q[5]=0.15; p=q; end', '  if(p.size()!=counts[op]) $fatal(1,"Invalid DSP parameter count");','  foreach(p[k]) if(!finite_real(p[k])) $fatal(1,"Invalid DSP nonfinite parameter");','  foreach(x[k]) if(!finite_real(x[k].re) || !finite_real(x[k].im)) $fatal(1,"Invalid DSP nonfinite signal");','  foreach(a[k]) if(!finite_real(a[k].re) || !finite_real(a[k].im)) $fatal(1,"Invalid DSP nonfinite auxiliary");']
 for ops,p,m,s in RULES:
  py.append(f"    if op in {ops!r} and not ({p}): raise ValueError('Invalid DSP dimensions or parameters')")
  mat.append("if any(strcmp(op,{"+','.join("'"+o+"'" for o in ops)+"})) && ~("+m+"), error('Invalid DSP dimensions or parameters'); end")
  sv.append('  if(('+ ' || '.join(f'op=={NAMES.index(o)}' for o in ops)+') && !('+s+')) $fatal(1,"Invalid DSP dimensions or parameters");')
 py.append('    return p');mat.append('end');sv+=['  return p;','endfunction']
 py += MIMO_PY.strip().splitlines()
 mat += MIMO_M.strip().splitlines()
 sv = MIMO_SV.strip().splitlines() + sv

 for name,lines in [('common/python/research_validate.py',py),('common/octave/research_validate.m',mat),('common/sv/research_validate.svh',sv)]: (ROOT/name).write_text('\n'.join(lines)+'\n')
 print('Generated three DSP input validators')
if __name__=='__main__':main()
