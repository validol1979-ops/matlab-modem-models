function y = modem_channel(cfg, x, varargin)
% Модель канала для собственной реализации модемов.
%   y = modem_channel(cfg, x, 'snr_db', 25, 'delay', 2.25, ...)
% Параметры (имя, значение):
%   snr_db      - отношение сигнал/шум на отсчёт, дБ (Inf - без шума)
%   gain        - коэффициент передачи канала
%   phase       - начальный фазовый сдвиг, рад
%   frequency   - сдвиг частоты, доли частоты дискретизации
%   delay       - дробная задержка, отсчёты
%   drift       - относительный уход тактовой частоты (|drift| < 0.01)
%   phase_noise - СКО приращения фазового шума (винеровский процесс), рад
%   echo        - амплитуда эха с задержкой на один символ
%   seed        - начальное состояние генератора случайных чисел
p = struct('snr_db',Inf,'gain',1,'phase',0,'frequency',0,'delay',0, ...
           'drift',0,'phase_noise',0,'echo',0,'seed',7);
for k = 1:2:numel(varargin), p.(varargin{k}) = varargin{k+1}; end
if p.gain <= 0 || p.delay < 0 || abs(p.drift) >= 0.01
  error('Invalid channel parameters');
end
x = x(:).';
if p.echo
  taps = [1 zeros(1,cfg.sps-1) p.echo];
  x = conv(x, taps);
end
count = numel(x) + ceil(p.delay + abs(p.drift)*numel(x)) + 4;
n = 0:count-1;
saved = rng; rng(p.seed,'twister');
shifted = modem_core('cubic', x, n*(1-p.drift) - p.delay);
pn = cumsum(p.phase_noise * randn(1,count));
clean = p.gain * shifted .* exp(1i*(p.phase + 2*pi*p.frequency*n + pn));
if isinf(p.snr_db)
  y = clean;
else
  sigma = sqrt(mean(abs(clean).^2) / 10^(p.snr_db/10) / 2);
  y = clean + sigma*(randn(1,count) + 1i*randn(1,count));
end
rng(saved);
end
