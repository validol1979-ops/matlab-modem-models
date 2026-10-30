function y = research_core(op,p,x,a)
% Плоские массивы имеют одинаковый порядок элементов во всех реализациях.
if nargin<4, a=[]; end
x=x(:).'; a=a(:).'; p=p(:).';
p=research_validate(op,p,x,a);
if isempty(x) || any(~isfinite([x a p])), error('Invalid DSP transaction'); end
switch op
case 'fir', y=conv(x,a);
case 'dft'
  if p(1), y=ifft(x); else, y=fft(x); end
case {'pfb','wola'}
  M=p(1); D=p(2); y=[];
  for last=0:D:numel(x)-1
    v=zeros(1,M);
    for j=0:min(last,numel(a)-1), v(mod(j,M)+1)=v(mod(j,M)+1)+a(j+1)*x(last-j+1); end
    y=[y fft(v).*exp(2i*pi*(0:M-1)*last/M)];
  end
case {'lms','nlms','rls'}
  M=p(1); mu=p(2); w=zeros(M,1); P=eye(M)/p(3); u=zeros(M,1); z=zeros(size(x)); e=z;
  for k=1:numel(x)
    u=[x(k);u(1:end-1)]; z(k)=w'*u; e(k)=a(k)-z(k);
    if strcmp(op,'rls')
      g=P*u/(mu+u'*P*u); w=w+g*conj(e(k)); P=(P-g*u'*P)/mu;
    else
      step=mu;
      if strcmp(op,'nlms'), step=mu/(p(3)+real(u'*u)); end
      w=w+step*u*conj(e(k));
    end
  end
  y=[z e w.'];
case 'ldpc'
  m=p(1); n=p(2); H=reshape(real(a),n,m).'; messages=zeros(m,n); post=real(x);
  for iteration=1:p(3)
    variable=repmat(post,m,1)-messages;
    for j=1:m
      ids=find(H(j,:));
      for col=ids
        v=variable(j,ids(ids~=col));
        if p(4)==0
          product=prod(tanh(v/2)); messages(j,col)=2*atanh(min(max(product,-1+1e-12),1-1e-12));
        else
          magnitude=min(abs(v));
          if p(4)==2, magnitude=magnitude*p(5); end
          if p(4)==3, magnitude=max(0,magnitude-p(6)); end
          messages(j,col)=prod(sign(v))*magnitude;
        end
      end
    end
    post=real(x)+sum(messages,1); bits=double(post<0);
    if ~any(mod(H*bits.',2)), break; end
  end
  y=[bits post];
case 'stft'
  [s,~]=analysis_frames(x,p(1),p(2)); y=reshape(s.',1,[]);
case 'istft'
  n=p(1); h=p(2); w=sqrt(.5-.5*cos(2*pi*((0:n-1)+.5)/n));
  y=synthesize(reshape(x,n,[]).',w,h);
case 'omlsa'
  n=p(1); h=p(2);
  % Отражённые края обеспечивают полноценное перекрытие крайних окон.
  extended=[x(n+1:-1:2) x x(end-1:-1:end-n)];
  [s,w]=analysis_frames(extended,n,h);
  noise=max(mean(abs(s(1:p(3),:)).^2,1),1e-9); prev=ones(1,n); out=zeros(size(s));
  for k=1:size(s,1)
    gamma=abs(s(k,:)).^2./noise; xi=max(p(4)*prev+(1-p(4))*max(gamma-1,0),1e-5);
    v=gamma.*xi./(1+xi); exponential=arrayfun(@expint_one,v);
    gain=min(max(xi./(1+xi).*exp(.5*exponential),.05),1);
    presence=1./(1+.25*(1+xi).*exp(-v)); gain=gain.^presence.*.05.^(1-presence);
    out(k,:)=s(k,:).*gain; prev=abs(out(k,:)).^2./noise;
  end
  y=synthesize(out,w,h); y=y(n+(1:numel(x)));
case 'beamform'
  M=p(1); matrix=reshape(x,M,[]).'; y=(matrix*a'/(a*a')).';
case 'mimo'
  M=p(1); H=reshape(a,M,M).'; r=reshape(x,M,[]);
  y=reshape((H'*H+p(2)*eye(M))\(H'*r),1,[]);
case 'ofdm_tx'
  n=p(1); cp=p(2); s=reshape(x,n,[]); z=ifft(s)*sqrt(n);
  y=reshape([z(n-cp+1:n,:);z],1,[]);
case 'ofdm_rx'
  n=p(1); cp=p(2); z=reshape(x,n+cp,[]); y=reshape(fft(z(cp+1:end,:))/sqrt(n),1,[]);
case 'fsk_tx'
  n=p(1); y=reshape(exp(2i*pi*(0:n-1).'*(p(2)+real(x)*p(3))/n),1,[]);
case 'fsk_rx'
  n=p(1); order=p(4); basis=exp(2i*pi*(p(2)+(0:order-1).'*p(3))*(0:n-1)/n);
  score=abs(conj(basis)*reshape(x,n,[])); [~,y]=max(score,[],1); y=y-1;
case 'costas'
  phase=0; freq=0; z=zeros(size(x)); history=z;
  for k=1:numel(x)
    z(k)=x(k)*exp(-1i*phase); err=sign(real(z(k)))*imag(z(k))-sign(imag(z(k)))*real(z(k));
    history(k)=phase; freq=freq+p(2)*err; phase=phase+freq+p(1)*err;
  end
  y=[z history];
case 'timing'
  sps=p(1); count=p(2); pos=p(3); rate=0; z=zeros(1,count); history=z;
  for k=1:count
    v=modem_core('cubic',x,[pos-sps/2 pos pos+sps/2]);
    err=min(max(real((v(3)-v(1))*conj(v(2))),-1),1);
    z(k)=v(2); history(k)=pos; rate=rate+p(5)*err; pos=pos+sps+rate+p(4)*err;
  end
  y=[z history];
case 'notch'
  c=cos(2*pi*p(1)); r=p(2); y=filter([1 -2*c 1],[1 -2*r*c r*r],x);
case 'kalman'
  value=0; covariance=p(3); y=zeros(size(x));
  for k=1:numel(x)
    covariance=covariance+p(1); gain=covariance/(covariance+p(2)); value=value+gain*(x(k)-value);
    covariance=covariance*(1-gain); y(k)=value;
  end
case 'wsinc'
  n=p(1); t=(0:n-1)-(n-1)/2; s=ones(size(t)); nz=t~=0;
  s(nz)=sin(2*pi*p(2)*t(nz))./(2*pi*p(2)*t(nz));
  y=2*p(2)*s.*(.54-.46*cos(2*pi*(0:n-1)/(n-1))); y=y/sum(y);
case 'alamouti'
  h0=a(1); h1=a(2); r=reshape(x,2,[]); energy=abs(h0)^2+abs(h1)^2;
  y=reshape([conj(h0)*r(1,:)+h1*conj(r(2,:));conj(h1)*r(1,:)-h0*conj(r(2,:))]/energy,1,[]);
case 'gf2_encode'
  m=p(1); k=p(2); A=reshape(real(a),k,m).'; y=[mod(A*real(x).',2).' real(x)];
otherwise, error('Unknown DSP operation');
end
  y=y(:).';
end

function [s,w]=analysis_frames(x,n,h)
% Ненулевые края окна исключают потерю первого и последнего отсчёта.
w=sqrt(.5-.5*cos(2*pi*((0:n-1)+.5)/n)); count=1+floor((numel(x)-n)/h); s=zeros(count,n);
for k=0:count-1, s(k+1,:)=fft(x(k*h+(1:n)).*w); end
end

function y=synthesize(s,w,h)
n=numel(w); count=size(s,1); y=zeros(1,(count-1)*h+n); norm=y;
for k=0:count-1
  ids=k*h+(1:n); y(ids)=y(ids)+ifft(s(k+1,:)).*w; norm(ids)=norm(ids)+w.^2;
end
  y=y./max(norm,1e-15);
end

function y=expint_one(x)
x=max(real(x),1e-12);
if x<=1
  term=1; series=0;
  for k=1:80, term=term*(-x/k); series=series+term/k; end
  y=-0.5772156649015328606-log(x)-series;
else
  b=x+1; c=1e30; d=1/b; h=d;
  for k=1:100, a=-k*k; b=b+2; d=1/(a*d+b); c=b+a/c; h=h*c*d; end
  y=h*exp(-x);
end
end
