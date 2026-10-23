function report = modem_own_demo(folder, options)
% Собственная реализация модема по параметрам config.json из папки модели.
% Строит созвездия до и после петель приёмника, сходимость ошибки,
% кривую SER(SNR) и сравнение с отключённым ключевым узлом приёмника.
%   report = modem_own_demo(folder)
%   report = modem_own_demo(folder, struct('symbols',3072,'plot',false))
if nargin < 2, options = struct(); end
opt = struct('symbols',1536,'training',192,'snr_db',28,'sweep',-10:2:24,'plot',true);
names = fieldnames(options);
for k = 1:numel(names), opt.(names{k}) = options.(names{k}); end

cfg = jsondecode(fileread(fullfile(folder,'config.json')));
cfg.constellation = reshape(cfg.constellation, [], 2);
cpm = any(strcmp(cfg.family,{'msk','gmsk'}));

saved = rng; rng(19,'twister');
data = randi([0 cfg.order-1], 1, opt.symbols);
rng(saved);
tx = modem_core('transmit', cfg, data);
payload = opt.training+1:opt.symbols;

% Канал по умолчанию: задержка, частотный сдвиг, фаза, ослабление и шум.
base = {'gain',0.65,'phase',0.38,'frequency',0.00015,'delay',2.25};
[scenario, channel_args, ablation] = choose_scenario(cfg);
args = [base channel_args {'snr_db',opt.snr_db}];
rx = receive_case(cfg, tx, data, opt.training, args, scenario);
errors = sum(rx.data(payload) ~= data(payload));

% Кривая SER(SNR) в том же сценарии канала.
ser = zeros(size(opt.sweep));
for k = 1:numel(opt.sweep)
  a = [base channel_args {'snr_db',opt.sweep(k),'seed',100+k}];
  r = receive_case(cfg, tx, data, opt.training, a, scenario);
  ser(k) = mean(r.data(payload) ~= data(payload));
end

% Сравнение с отключённым узлом приёмника, если он есть.
compare = [];
if ~isempty(ablation)
  rx_off = receive_case(ablation.cfg, tx, data, opt.training, ...
                        [base ablation.args {'snr_db',ablation.snr_db}], ablation.scenario);
  rx_on = receive_case(cfg, tx, data, opt.training, ...
                       [base ablation.args {'snr_db',ablation.snr_db}], scenario);
  compare = struct('title',ablation.title,'on',rx_on,'off',rx_off, ...
                   'errors_on',sum(rx_on.data(payload) ~= data(payload)), ...
                   'errors_off',sum(rx_off.data(payload) ~= data(payload)), ...
                   'snr_db',ablation.snr_db);
end

report = struct('modem',cfg.name,'scenario',scenario,'snr_db',opt.snr_db, ...
                'payload_symbols',numel(payload),'symbol_errors',errors, ...
                'ser',errors/numel(payload),'estimated_delay',rx.delay, ...
                'estimated_frequency',rx.frequency,'sweep_snr_db',opt.sweep,'sweep_ser',ser);
if ~isempty(compare)
  report.ablation = compare.title;
  report.errors_enabled = compare.errors_on;
  report.errors_disabled = compare.errors_off;
end
fprintf('%s: %s, SNR %g дБ, ошибок %d из %d (SER %.2g), задержка %.2f, сдвиг частоты %.2e\n', ...
        cfg.name, scenario, opt.snr_db, errors, numel(payload), errors/numel(payload), ...
        rx.delay, rx.frequency);
if ~isempty(compare)
  fprintf('  %s (SNR %g дБ): ошибок %d с узлом, %d без него\n', compare.title, compare.snr_db, compare.errors_on, compare.errors_off);
end
if opt.plot, draw(cfg, cpm, rx, payload, opt, ser, compare, scenario); end
end

function [scenario, args, ablation] = choose_scenario(cfg)
ablation = [];
if ~strcmp(cfg.equalizer,'none')
  scenario = 'многолучевой канал (эхо 0.45 через символ)';
  args = {'echo',0.45};
  off = cfg; off.equalizer = 'none';
  ablation = struct('cfg',off,'args',{{'echo',0.45}},'scenario',scenario, ...
                    'title','Эквалайзер','snr_db',28);
elseif cfg.diversity_branches > 1
  scenario = 'две ветви приёма с разным замиранием, MRC';
  args = {};
  ablation = struct('cfg',cfg,'args',{{}},'scenario','одна слабая ветвь', ...
                    'title','Объединение MRC','snr_db',4);
elseif cfg.variable_delay
  scenario = 'уход тактовой частоты 6e-4';
  args = {'drift',0.0006};
  off = cfg; off.timing = 'feedforward';
  ablation = struct('cfg',off,'args',{{'drift',0.0006}},'scenario',scenario, ...
                    'title','Петля Gardner','snr_db',28);
elseif cfg.phase_noise
  scenario = 'фазовый шум 3e-3 рад/отсчёт';
  args = {'phase_noise',0.003};
else
  scenario = 'AWGN, задержка и сдвиг частоты';
  args = {};
end
end

function rx = receive_case(cfg, tx, data, training, args, scenario)
if cfg.diversity_branches > 1
  % Две ветви с разными комплексными коэффициентами и независимым шумом.
  snr = Inf; seed = 7; keep = {};
  for k = 1:2:numel(args)
    switch args{k}
      case 'snr_db', snr = args{k+1};
      case 'seed', seed = args{k+1};
      otherwise, keep = [keep args(k:k+1)]; %#ok<AGROW>
    end
  end
  gains = [0.2+0.3i; 1-0.4i];
  clean = modem_channel(cfg, tx.waveform, keep{:});
  sigma = 0;
  if ~isinf(snr), sigma = sqrt(mean(abs(clean).^2) / 10^(snr/10) / 2); end
  saved = rng; rng(seed,'twister');
  branches = gains * clean + sigma*(randn(2,numel(clean)) + 1i*randn(2,numel(clean)));
  rng(saved);
  if strcmp(scenario,'одна слабая ветвь')
    wave = branches(1,:) / gains(1);
  else
    wave = modem_core('combine', branches, gains);
  end
else
  wave = modem_channel(cfg, tx.waveform, args{:});
end
rx = modem_core('receive', cfg, wave, data(1:training), numel(data));
end

function draw(cfg, cpm, rx, payload, opt, ser, compare, scenario)
figure('Name', [cfg.name ' - собственная реализация'], 'Color', 'w', 'Position', [100 100 900 720]);
subplot(2,2,1);
show_points(cpm, rx.synchronized(payload));
title({'Вход петель:','после оценки задержки и частоты'});
subplot(2,2,2);
show_points(cpm, rx.symbols(payload));
title({'Выход приёмника:','после петель и АРУ'});
subplot(2,2,3);
err = residual(cfg, cpm, rx.symbols);
plot(err, 'Color', [0.2 0.4 0.8]); hold on;
plot(movmean(err, 32), 'k', 'LineWidth', 1.5);
yl = ylim; plot([opt.training opt.training], yl, 'r--');
xlabel('Номер символа'); ylabel('|ошибка|^2');
title({'Квадрат ошибки решения','(пунктир - конец преамбулы)'}); grid on;
subplot(2,2,4);
floor_ser = 0.5 / numel(payload);
semilogy(opt.sweep, max(ser, floor_ser), 'o-', 'LineWidth', 1.5); grid on;
xlabel('SNR на отсчёт, дБ'); ylabel('SER');
title({'Вероятность ошибки на символ','(нижняя граница - ошибок нет)'});
if exist('sgtitle','file')
  sgtitle(sprintf('Канал: %s', scenario));
end
if ~isempty(compare)
  figure('Name', [cfg.name ' - сравнение'], 'Color', 'w', 'Position', [150 150 900 420]);
  subplot(1,2,1); show_points(cpm, compare.on.symbols(payload));
  title({sprintf('%s включён', compare.title), sprintf('%d ошибок, SNR %g дБ', compare.errors_on, compare.snr_db)});
  subplot(1,2,2); show_points(cpm, compare.off.symbols(payload));
  title({sprintf('%s выключен', compare.title), sprintf('%d ошибок, SNR %g дБ', compare.errors_off, compare.snr_db)});
end
drawnow;
end

function show_points(cpm, values)
if cpm
  hist(real(values), 60); xlabel('Набег фазы за символ, рад'); grid on;
else
  plot(real(values), imag(values), '.', 'MarkerSize', 6);
  axis equal; grid on; xlabel('I'); ylabel('Q');
  r = max(abs(values)) * 1.1; if r > 0, axis([-r r -r r]); end
end
end

function err = residual(cfg, cpm, values)
if cpm
  ideal = sign(real(values)) * pi/2;
else
  table = cfg.constellation(:,1).' + 1i*cfg.constellation(:,2).';
  [~, index] = min(abs(values(:) - table).^2, [], 2);
  ideal = reshape(table(index), size(values));
end
err = abs(values - ideal).^2;
end
