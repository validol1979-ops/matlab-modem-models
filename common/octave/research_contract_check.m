function research_contract_check(filename)
% Неправильный вход должен отказать до получения результата, правильный совпасть с эталоном.
ops={'fir','dft','pfb','lms','nlms','rls','ldpc','stft','istft','omlsa','beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','costas','timing','notch','kalman','wola','wsinc','alamouti','gf2_encode'};
f=fopen(filename,'r');assert(f>=0,'Cannot open contract cases');cleanup=onCleanup(@() fclose(f));
count=fscanf(f,'%d',1);assert(numel(count)==1 && count>0,'Invalid contract count');
for k=1:count
  h=fscanf(f,'%d',6);assert(numel(h)==6 && all(h(3:6)>=0),'Truncated contract header');p=fscanf(f,'%f',h(3));assert(numel(p)==h(3),'Truncated contract parameters');x=read_values(f,h(4));a=read_values(f,h(5));expected=read_values(f,h(6));
  if h(2)<0 || h(2)>=numel(ops),op='invalid';else,op=ops{h(2)+1};end
  rejected=false;
  try, actual=research_core(op,p,x,a);
  catch e
    assert(~isempty(strfind(e.message,'Invalid DSP')),['Unexpected rejection: ' e.message]);
    rejected=true;
  end
  if h(1)
    assert(~rejected,'Valid transaction rejected');
    assert(numel(actual)==numel(expected) && all(abs(actual-expected)<1e-8*(1+abs(expected))),'Contract output mismatch');
  else
    assert(rejected,'Invalid input accepted');
  end
end
fprintf('PASS %d boundary cases\n',count);
end
function x=read_values(f,n)
if n==0,x=[];return;end
v=fscanf(f,'%f',[2 n]);assert(numel(v)==2*n,'Truncated contract values');x=complex(v(1,:),v(2,:));
end
