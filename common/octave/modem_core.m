function varargout = modem_core(operation, varargin)
  % Общая точка входа; внутренние функции не требуют пакетов Octave.
  if ~isempty(varargin) && isstruct(varargin{1}), validate_config(varargin{1}); end
  switch operation
    case 'encode', [varargout{1:nargout}] = encode(varargin{:});
    case 'decode', varargout{1} = decode(varargin{:});
    case 'transmit', varargout{1} = transmit(varargin{:});
    case 'receive', varargout{1} = receive(varargin{:});
    case 'symbols', varargout{1} = symbol_receiver(varargin{:});
    case 'rrc', varargout{1} = rrc(varargin{:});
    case 'gaussian', varargout{1} = gaussian(varargin{:});
    case 'cubic', varargout{1} = cubic(varargin{:});
    case 'combine', varargout{1} = combine(varargin{:});
    otherwise, error('Unknown modem operation');
  end
end

function data = checked(cfg, data)
  if ~isvector(data) || isempty(data) || any(~isfinite(data(:))) || ...
     any(data(:) ~= floor(data(:))) || any(data(:) < 0) || any(data(:) >= cfg.order)
    error('Invalid symbol data');
  end
  data = double(data(:).');
end

function table = constellation(cfg)
  table = cfg.constellation(:,1).' + 1i * cfg.constellation(:,2).';
end

function out = gray_inverse(value)
  out = value;
  value = floor(value / 2);
  while value > 0
    out = bitxor(out, value);
    value = floor(value / 2);
  end
end

function [ids, symbols] = encode(cfg, data)
  data = checked(cfg, data);
  state = 0;
  ids = zeros(size(data));
  for k = 1:numel(data)
    v = data(k);
    switch cfg.differential
      case 'psk'
        state = mod(state + bitxor(v, floor(v/2)), cfg.order);
        index = state;
      case 'quadrant'
        group = cfg.order / 4;
        q = floor(v / group);
        state = mod(state + bitxor(q, floor(q/2)), 4);
        index = group * state + mod(v, group);
      case 'pi4'
        state = mod(state + 2 * bitxor(v, floor(v/2)) + 1, 8);
        index = state;
      otherwise
        index = v;
    end
    ids(k) = index;
  end
  table = constellation(cfg);
  symbols = table(ids + 1);
end

function data = decode(cfg, ids)
  state = 0;
  data = zeros(size(ids));
  for k = 1:numel(ids)
    index = ids(k);
    switch cfg.differential
      case 'psk'
        v = gray_inverse(mod(index - state, cfg.order));
        state = index;
      case 'quadrant'
        group = cfg.order / 4;
        q = floor(index / group);
        v = group * gray_inverse(mod(q - state, 4)) + mod(index, group);
        state = q;
      case 'pi4'
        v = gray_inverse(floor(mod(mod(index - state, 8) - 1, 8) / 2));
        state = index;
      otherwise
        v = index;
    end
    data(k) = v;
  end
end

function h = rrc(sps, order, beta)
  if order <= 0 || mod(order,2) || beta < 0 || beta > 1 || sps < 2
    error('Invalid root raised cosine filter parameters');
  end
  t = (-order/2:order/2) / sps;
  h = zeros(size(t));
  for k = 1:numel(t)
    x = t(k);
    if abs(x) < 1e-12
      h(k) = 1 + beta * (4/pi - 1);
    elseif beta && abs(abs(4*beta*x) - 1) < 1e-10
      h(k) = beta/sqrt(2) * ((1+2/pi)*sin(pi/(4*beta)) + (1-2/pi)*cos(pi/(4*beta)));
    else
      h(k) = (sin(pi*x*(1-beta)) + 4*beta*x*cos(pi*x*(1+beta))) / (pi*x*(1-(4*beta*x)^2));
    end
  end
  h = h / norm(h);
end

function h = gaussian(sps, bt)
  if sps < 2 || bt <= 0, error('Invalid Gaussian filter parameters'); end
  t = (-2*sps:2*sps) / sps;
  h = exp(-2 * (pi * bt * t).^2 / log(2));
  h = h / sum(h);
end

function y = cubic(x, positions)
  % Индексы времени отсчитываются от нуля во всех трёх языках.
  x = x(:).';
  base = floor(positions);
  mu = positions - base;
  weights = {-mu.*(mu-1).*(mu-2)/6, (mu+1).*(mu-1).*(mu-2)/2, ...
             -(mu+1).*mu.*(mu-2)/2, (mu+1).*mu.*(mu-1)/6};
  y = complex(zeros(size(positions)));
  for k = 1:4
    ids = base + k - 2;
    valid = ids >= 0 & ids < numel(x);
    values = x(min(max(ids,0),numel(x)-1)+1);
    values(~valid) = 0;
    y = y + weights{k} .* values;
  end
end

function result = transmit(cfg, data)
  data = checked(cfg, data);
  [ids, symbols] = encode(cfg, data);
  sps = cfg.sps;
  if any(strcmp(cfg.family, {'msk','gmsk'}))
    frequency = repelem(2*data-1, sps);
    if strcmp(cfg.family,'gmsk'), frequency = conv(frequency, gaussian(sps,cfg.gaussian_bt)); end
    waveform = exp(1i * cumsum(frequency) * pi / (2*sps));
  else
    upsampled = complex(zeros(1,numel(data)*sps));
    upsampled(1:sps:end) = symbols;
    if strcmp(cfg.family, 'oqpsk')
      % Восстанавливаем смещение квадратурной ветви на половину символа.
      half = sps/2;
      upsampled = [real(upsampled) zeros(1,half)] + 1i*[zeros(1,half) imag(upsampled)];
    end
    waveform = conv(upsampled, rrc(sps,cfg.rrc_order,cfg.rolloff));
  end
  result = struct('data',data,'indices',ids,'symbols',symbols,'waveform',waveform);
end

function [slope, gain, error_value] = fit_carrier(samples, reference)
  assert(numel(samples)==numel(reference) && numel(reference)>=2 && all(isfinite([samples reference])) && all(abs(reference)>=1e-12), 'Invalid carrier reference');
  n = 0:numel(reference)-1;
  phase = unwrap(angle(samples ./ reference));
  centered = n - mean(n);
  slope = sum(centered .* (phase-mean(phase))) / sum(centered.^2);
  gain = sum(conj(reference).*samples.*exp(-1i*slope*n)) / sum(abs(reference).^2);
  assert(isfinite(gain) && abs(gain)>=1e-12, 'Invalid carrier gain');
  corrected = samples .* exp(-1i*slope*n) / gain;
  error_value = mean(abs(corrected-reference).^2);
end

function result = symbol_receiver(cfg, samples, training)
  table = constellation(cfg);
  out = complex(zeros(size(samples)));
  ids = zeros(size(samples));
  phase = 0; frequency = 0; gain = 1;
  taps = [1 zeros(1,6)]; feedback = zeros(1,3);
  history = zeros(1,7); past = zeros(1,3);
  for k = 1:numel(samples)
    corrected = samples(k) * exp(-1i*phase) * gain;
    history = [corrected history(1:end-1)];
    value = corrected;
    if ~strcmp(cfg.equalizer,'none'), value = sum(taps.*history); end
    if strcmp(cfg.equalizer,'dfe'), value = value + sum(feedback.*past); end
    [~, index] = min(abs(table-value).^2);
    if k <= numel(training), target = training(k); else, target = table(index); end
    error_value = target - value;
    if ~strcmp(cfg.equalizer,'none')
      power = sum(abs(history).^2) + 1e-9;
      if strcmp(cfg.equalizer,'dfe'), power = power + sum(abs(past).^2); end
      if k <= numel(training), step = 0.3; else, step = 0.02; end
      taps = taps + step * error_value * conj(history) / power;
      if strcmp(cfg.equalizer,'dfe'), feedback = feedback + step*error_value*conj(past)/power; end
    end
    past = [target past(1:end-1)];
    pe = min(max(imag(value*conj(target))/max(abs(target)^2,1e-12),-0.5),0.5);
    if strcmp(cfg.carrier,'costas') && cfg.order == 2
      pe = min(max(imag(value/table(1))*sign(real(value/table(1))),-0.5),0.5);
    end
    if strcmp(cfg.carrier,'feedforward')
      phase = phase + 0.03*pe;
    else
      frequency = frequency + 0.0002*pe;
      phase = phase + frequency + 0.04*pe;
    end
    gain = gain * (1 + 0.002 * min(max(real(error_value*conj(value))/max(abs(target)^2,1e-12),-0.5),0.5));
    out(k) = value; ids(k) = index-1;
  end
  result = struct('symbols',out,'indices',ids,'data',decode(cfg,ids));
end

function result = receive(cfg, wave, preamble, count)
  preamble = checked(cfg,preamble);
  if numel(preamble) < 32 || count < numel(preamble), error('Invalid training or frame length'); end
  if ~isvector(wave) || numel(wave) < count*cfg.sps || any(~isfinite(wave))
    error('Invalid or truncated receive waveform');
  end
  wave = wave(:).';
  if strcmp(cfg.family,'oqpsk')
    result = receive_oqpsk(cfg,wave,preamble,count); return;
  end
  if any(strcmp(cfg.family,{'msk','gmsk'}))
    result = receive_cpm(cfg,wave,preamble,count); return;
  end
  filtered = conv(wave,rrc(cfg.sps,cfg.rrc_order,cfg.rolloff));
  [~, train] = encode(cfg,preamble);
  train = train(1:end-4);
  n = 0:numel(train)-1;
  best = Inf;
  for delay = 0:0.25:2*cfg.sps
    y = cubic(filtered,cfg.rrc_order+delay+cfg.sps*n);
    [slope, gain, error_value] = fit_carrier(y,train);
    if error_value < best
      best = error_value; best_delay = delay; best_slope = slope; best_gain = gain;
    end
  end
  positions = cfg.rrc_order+best_delay+cfg.sps*(0:count-1);
  if strcmp(cfg.timing,'gardner')
    correction = 0;
    for k = 1:count
      p = positions(k)+correction;
      values = cubic(filtered,[p-cfg.sps/2 p p+cfg.sps/2]);
      error_value = real((values(3)-values(1))*conj(values(2))) / max(abs(best_gain)^2*mean(abs(train).^2),1e-9);
      positions(k) = p;
      correction = correction + 0.015*min(max(error_value,-1),1);
    end
  end
  y = cubic(filtered,positions).*exp(-1i*best_slope*(0:count-1))/best_gain;
  result = symbol_receiver(cfg,y,train);
  result.delay = best_delay;
  result.frequency = best_slope / (2*pi*cfg.sps);
  result.gain = abs(best_gain);
  result.synchronized = y;
end

function result = receive_oqpsk(cfg, wave, preamble, count)
  % Несущую оцениваем до совмещения квадратурных ветвей.
  start = cfg.rrc_order;
  tx = transmit(cfg,preamble);
  reference = tx.waveform(start+1:(numel(preamble)-4)*cfg.sps);
  n = (0:numel(reference)-1)+start;
  best = Inf;
  for delay = 0:0.25:2*cfg.sps
    [slope,gain,error_value] = fit_carrier(cubic(wave,n+delay),reference);
    if error_value < best
      best = error_value; best_delay = delay; best_slope = slope; best_gain = gain;
    end
  end
  n = 0:numel(wave)-1;
  aligned = cubic(wave,n+best_delay).*exp(-1i*best_slope*(n-start))/best_gain;
  filtered = conv(aligned,rrc(cfg.sps,cfg.rrc_order,cfg.rolloff));
  positions = cfg.rrc_order+cfg.sps*(0:count-1);
  symbols = real(cubic(filtered,positions))+1i*imag(cubic(filtered,positions+cfg.sps/2));
  [~,train] = encode(cfg,preamble);
  result = symbol_receiver(cfg,symbols,train(1:end-4));
  result.delay = best_delay; result.frequency = best_slope/(2*pi);
  result.gain = abs(best_gain); result.synchronized = symbols;
end

function result = receive_cpm(cfg, wave, preamble, count)
  sps = cfg.sps;
  tx = transmit(cfg,preamble);
  used = (numel(preamble)-4)*sps;
  reference = tx.waveform(1:used);
  best = Inf;
  for delay = 0:0.25:2*sps
    y = cubic(wave,(0:used-1)+delay);
    [slope,gain,error_value] = fit_carrier(y,reference);
    if error_value < best
      best = error_value; best_delay = delay; best_slope = slope; best_gain = gain;
    end
  end
  gdelay = 0;
  if strcmp(cfg.family,'gmsk'), gdelay = 2*sps; end
  n = 0:count*sps+gdelay-1;
  aligned = cubic(wave,n+best_delay).*exp(-1i*best_slope*n)/best_gain;
  increments = angle(aligned.*conj([1 aligned(1:end-1)]));
  values = sum(reshape(increments(gdelay+1:gdelay+count*sps),sps,count),1);
  data = double(values >= 0);
  result = struct('data',data,'indices',data,'symbols',values,'synchronized',values, ...
                  'delay',best_delay,'frequency',best_slope/(2*pi),'gain',abs(best_gain));
end

function y = combine(branches, gains, variances)
  gains = gains(:);
  if nargin < 3, variances = ones(size(gains)); else, variances = variances(:); end
  if size(branches,1) ~= numel(gains) || numel(variances) ~= numel(gains) || ...
     any(variances <= 0) || ~any(abs(gains)>0)
    error('Invalid diversity configuration');
  end
  y = (conj(gains)./variances).' * branches / sum(abs(gains).^2./variances);
end

function validate_config(cfg)
  valid=any(cfg.order==[2 4 8 16 64]) && cfg.sps>=2 && cfg.sps==fix(cfg.sps) ...
    && any(strcmp(cfg.family,{'psk','qam','pi4','msk','gmsk','oqpsk'})) ...
    && any(strcmp(cfg.differential,{'none','psk','quadrant','pi4'})) ...
    && any(strcmp(cfg.carrier,{'feedforward','feedback','costas'})) ...
    && any(strcmp(cfg.timing,{'feedforward','gardner'})) ...
    && any(strcmp(cfg.equalizer,{'none','linear','dfe'}));
  if strcmp(cfg.differential,'quadrant'),valid=valid && mod(cfg.order,4)==0;end
  if strcmp(cfg.differential,'pi4'),valid=valid && cfg.order==4;end
  if any(strcmp(cfg.family,{'msk','gmsk'})),valid=valid && cfg.order==2;end
  if strcmp(cfg.family,'oqpsk'),valid=valid && cfg.order==4 && mod(cfg.sps,2)==0;end
  size_expected=cfg.order;if strcmp(cfg.differential,'pi4'),size_expected=8;end
  valid=valid && isequal(size(cfg.constellation),[size_expected 2]) && all(isfinite(cfg.constellation(:)));
  if ~any(strcmp(cfg.family,{'msk','gmsk'}))
    valid=valid && cfg.rrc_order>0 && mod(cfg.rrc_order,2)==0 && cfg.rrc_order==fix(cfg.rrc_order) ...
      && isfinite(cfg.rolloff) && cfg.rolloff>=0 && cfg.rolloff<=1;
  end
  if strcmp(cfg.family,'gmsk'),valid=valid && isfinite(cfg.gaussian_bt) && cfg.gaussian_bt>0;end
  if ~valid,error('Invalid modem configuration');end
end
