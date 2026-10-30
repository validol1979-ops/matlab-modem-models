function p=research_validate(op,p,x,a)
% Создано tools/generate_validation.py; правьте контракт в генераторе.
if strcmp(op,'ldpc') && numel(p)>=4 && numel(p)<6, defaults=[.8 .15]; p=[p defaults(numel(p)-3:end)]; end
names={'fir','dft','pfb','lms','nlms','rls','ldpc','stft','istft','omlsa','beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','costas','timing','notch','kalman','wola','wsinc','alamouti','gf2_encode'};
counts=[0 1 2 3 3 3 6 2 2 4 1 2 2 2 4 4 2 5 2 3 2 2 0 2];
id=find(strcmp(names,op));
if isempty(id) || numel(p)~=counts(id) || isempty(x) || ~isreal(p) || any(~isfinite([p x a])), error('Invalid DSP transaction'); end
if any(strcmp(op,{'pfb','wola'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'pfb','wola'})) && ~(p(2)>=1 && p(2)<=2147483647 && p(2)==fix(p(2))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'lms','nlms','rls'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc'})) && ~(p(2)>=1 && p(2)<=2147483647 && p(2)==fix(p(2))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc'})) && ~(p(3)>=1 && p(3)<=2147483647 && p(3)==fix(p(3))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'stft','istft','omlsa'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'stft','istft','omlsa'})) && ~(p(2)>=1 && p(2)<=2147483647 && p(2)==fix(p(2))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'omlsa'})) && ~(p(3)>=1 && p(3)<=2147483647 && p(3)==fix(p(3))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','wsinc'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'fsk_tx','fsk_rx'})) && ~(p(4)>=1 && p(4)<=2147483647 && p(4)==fix(p(4))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'timing','gf2_encode'})) && ~(p(1)>=1 && p(1)<=2147483647 && p(1)==fix(p(1))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'timing','gf2_encode'})) && ~(p(2)>=1 && p(2)<=2147483647 && p(2)==fix(p(2))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'fir','pfb','wola'})) && ~(~isempty(a)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'dft'})) && ~(any(p(1)==[0 1])), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'lms','nlms','rls'})) && ~(numel(a)==numel(x) && p(2)>0 && p(3)>0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc'})) && ~(any(p(4)==0:3) && numel(x)==p(2) && numel(a)==p(1)*p(2) && p(5)>0 && p(6)>=0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc','gf2_encode'})) && ~(all(imag(a)==0) && all(real(a)==0 | real(a)==1)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ldpc'})) && ~(all(imag(x)==0) && all(sum(reshape(real(a),p(2),p(1)),1)>=2)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'stft','istft','omlsa'})) && ~(p(2)<=p(1)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'stft'})) && ~(numel(x)>=p(1)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'istft'})) && ~(mod(numel(x),p(1))==0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'omlsa'})) && ~(numel(x)>p(1) && p(3)<=1+floor((numel(x)+p(1))/p(2)) && p(4)>=0 && p(4)<1), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'beamform'})) && ~(numel(a)==p(1) && mod(numel(x),p(1))==0 && sum(abs(a).^2)>=1e-24 && sum(abs(a).^2)<=1e300), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'mimo'})) && ~(numel(a)==p(1)^2 && mod(numel(x),p(1))==0 && p(2)>=0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'mimo'})) && ~(mimo_valid(p,a)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ofdm_tx','ofdm_rx'})) && ~(p(2)>=0 && p(2)<=p(1) && p(2)==fix(p(2))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ofdm_tx'})) && ~(mod(numel(x),p(1))==0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ofdm_rx'})) && ~(p(1)+p(2)<=2147483647), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'ofdm_rx'})) && ~(mod(numel(x),p(1)+p(2))==0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'fsk_tx'})) && ~(all(imag(x)==0) && all(real(x)==fix(real(x))) && all(real(x)>=0 & real(x)<p(4))), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'fsk_rx'})) && ~(mod(numel(x),p(1))==0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'costas'})) && ~(all(p>=0)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'timing'})) && ~(p(1)>=2 && all(p(3:end)>=0)), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'notch'})) && ~(p(1)>=0 && p(1)<=.5 && p(2)>=0 && p(2)<1), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'kalman'})) && ~(p(1)>=0 && p(2)>0 && p(3)>=0), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'wsinc'})) && ~(p(1)>=2 && p(2)>0 && p(2)<.5), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'alamouti'})) && ~(numel(a)==2 && mod(numel(x),2)==0 && sum(abs(a).^2)>=1e-24 && sum(abs(a).^2)<=1e300), error('Invalid DSP dimensions or parameters'); end
if any(strcmp(op,{'gf2_encode'})) && ~(numel(x)==p(2) && numel(a)==p(1)*p(2) && all(imag(x)==0) && all(real(x)==0 | real(x)==1)), error('Invalid DSP dimensions or parameters'); end
end
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
