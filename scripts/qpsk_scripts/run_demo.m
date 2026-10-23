function results = run_demo(N)
%RUN_DEMO Алгоритмы исходных QPSK-демо в double, с состоянием FIR.
% N — число бит в опытах с частотным сдвигом, должно быть чётным.
if nargin < 1, N = 240; end
validateattributes(N, {'numeric'}, {'scalar', 'integer', '>=', 40, 'finite'});
assert(mod(N,2) == 0, 'N must be even (two bits per QPSK symbol).');
here = fileparts(mfilename('fullpath'));
oldpath = path;
pathCleanup = onCleanup(@() path(oldpath)); %#ok<NASGU>
addpath(here);
state = rng;
rngCleanup = onCleanup(@() rng(state)); %#ok<NASGU>
rng(7, 'twister');
[shape, lowpass] = demo_fir_coefficients();
fixedbits = [1 1 0 0 1 1 0 0 0 0 0 1 0 1 1 1 0 0 0 1 1 0 0 0 0 0 0 1 1 0 0 1 0 0 0 1 0 1 0 0];
results.basic = simulate_case(fixedbits, 50000, false, shape, lowpass);
bits = randi([0 1],1,N);
% Одни и те же данные и шум для сравнения с/без обратной связи.
noise = 0.1*randn(1,N*100);
results.open = simulate_case(bits, 50100, false, shape, lowpass, noise);
results.costas = simulate_case(bits, 50100, true, shape, lowpass, noise);
cases = {results.basic, results.open, results.costas};
names = {'Basic: synchronized carrier', '100 Hz offset: no feedback', '100 Hz offset: Costas feedback'};
figure('Name', 'QPSK: decisions and sampled I/Q', 'NumberTitle', 'off', ...
    'Position', [80 80 1100 800]);
for k = 1:3
    s = cases{k};
    subplot(3,2,2*k-1);
    stairs(0:numel(s.bits)-1,s.bits); hold on;
    stairs(0:numel(s.bits)-1,double(s.decisions), '--'); grid on; ylim([-0.2 1.2]);
    title(names{k}); xlabel('Bit index'); ylabel('Bit'); legend('TX','RX', 'Location', 'best');
    subplot(3,2,2*k);
    plot(s.sample_i,s.sample_q,'.'); grid on; axis equal;
    xlabel('I'); ylabel('Q'); title('I/Q at symbol centers');
    fprintf('%s: %d / %d raw bit errors (startup included)\n', names{k}, ...
        sum(s.bits ~= s.decisions), numel(s.bits));
end
s = results.costas;
figure('Name', 'QPSK: Costas phase detector and loop filter', 'NumberTitle', 'off');
subplot(3,1,1); plot(s.time,s.detector); grid on;
xlabel('Time (s)'); ylabel('Detector output');
subplot(3,1,2); plot(s.time,[s.control; 2*pi*100*s.time].'); grid on;
xlabel('Time (s)'); ylabel('Phase (rad)'); legend('Loop control','100 Hz phase ramp', 'Location','best');
subplot(3,1,3);
plot(s.time, mod(2*pi*100*s.time-s.control+pi/4,pi/2)-pi/4); grid on;
xlabel('Time (s)'); ylabel('Residual phase mod pi/2');
figure('Name', 'QPSK: waveform and receiver I/Q', 'NumberTitle', 'off');
subplot(2,1,1); idx=1:min(2000,numel(s.time));
plot(s.time(idx),[s.tx(idx);s.rx(idx)].'); grid on;
xlabel('Time (s)'); ylabel('Passband amplitude'); legend('TX','TX + noise');
subplot(2,1,2); plot(s.time,[s.i;s.q].'); grid on;
xlabel('Time (s)'); ylabel('Filtered amplitude'); legend('I','Q');
drawnow;
end

function s = simulate_case(bits, flocal, feedback, shape, lowpass, noise)
% Параметры, знак квадратур, детектор и PI-разность из оригинальных скриптов.
L=100; Fs=1e6; fc=50e3;
n=numel(bits)*L;
t=(0:n-1)/Fs;
wave=2*bits-1;
i=reshape(repmat(wave(1:2:end),2*L,1),1,[]);
q=reshape(repmat(wave(2:2:end),2*L,1),1,[]);
i=filter(shape,1,i); q=filter(shape,1,q);
tx=i.*cos(2*pi*fc*t)+q.*sin(2*pi*fc*t);
if nargin < 6
    noise=0.1*randn(size(tx)); % awgn(tx,20): мощность отсчёта сигнала по умолчанию 0 dBW.
end
rx=tx+noise;
control=zeros(1,n); detector=zeros(1,n);
if feedback
    C1=2^(-4); C2=C1*2^(-3);
    zi=zeros(numel(lowpass)-1,1); zq=zi;
    for k=1:n
        angle=2*pi*flocal*t(k)-control(k);
        % Одно обновление состояния вместо фильтрации всего буфера заново.
        [i(k),zi]=filter(lowpass,1,rx(k)*cos(angle),zi);
        [q(k),zq]=filter(lowpass,1,rx(k)*sin(angle),zq);
        detector(k)=(2*(i(k)>=0)-1)*q(k)-(2*(q(k)>=0)-1)*i(k);
        if k < n
            if k==1
                control(k+1)=C1*detector(k);
            else
                control(k+1)=control(k)+C1*detector(k)+(C2-C1)*detector(k-1);
            end
        end
    end
else
    i=filter(lowpass,1,rx.*cos(2*pi*flocal*t));
    q=filter(lowpass,1,rx.*sin(2*pi*flocal*t));
    detector=(2*(i>=0)-1).*q-(2*(q>=0)-1).*i;
    % Фильтр детектора basic не подключён к генератору несущей.
    C1=0.00090625; C2=C1*0.1;
    control=filter([C1 C2-C1],[1 -1],detector);
end
sample=L:2*L:n;
decisions=reshape([i(sample)>0;q(sample)>0],1,[]);
assert(all(isfinite([i q control detector])));
s=struct('bits',bits,'decisions',decisions,'sample_i',i(sample),'sample_q',q(sample), ...
    'time',t,'tx',tx,'rx',rx,'i',i,'q',q,'control',control,'detector',detector);
end
