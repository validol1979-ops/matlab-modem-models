function ok = own_cross_check(folder)
% Перекрёстная проверка: MATLAB/Octave-реализация против Python.
% Сначала сформируйте векторы:  python common/own/python/own_cross_vectors.py
% Затем в MATLAB или Octave:    own_cross_check   (или own_cross_check('папка'))
here = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(here));
if nargin < 1, folder = fullfile(root, 'build', 'own_cross_vectors'); end
addpath(here);
files = dir(fullfile(folder, '*.json'));
if isempty(files)
  error('Нет векторов в %s. Запустите python common/own/python/own_cross_vectors.py', folder);
end
ok = true;
for f = 1:numel(files)
  v = jsondecode(fileread(fullfile(folder, files(f).name)));
  cfg = jsondecode(fileread(fullfile(root, 'modems', v.name, 'config.json')));
  cfg.constellation = reshape(cfg.constellation, [], 2);
  cases = v.cases; if ~iscell(cases), cases = num2cell(cases); end
  max_tx = 0; max_rx = 0; passed = true; message = '';
  for c = 1:numel(cases)
    item = cases{c};
    data = item.data(:).';
    wave = unpack(item.wave);
    if isfield(item, 'branch_b')
      wave = own_core('combine', [wave; unpack(item.branch_b)], unpack(item.gains));
    end
    tx = own_core('transmit', cfg, data);
    rx = own_core('receive', cfg, wave, data(1:item.training), numel(data));
    tx_error = max(abs(tx.waveform - unpack(item.tx)));
    rx_error = max(abs(rx.symbols - unpack(item.rx_symbols)));
    max_tx = max(max_tx, tx_error); max_rx = max(max_rx, rx_error);
    checks = {tx_error < 1e-7, 'передатчик'; rx_error < 1e-7, 'символы приёмника';
              isequal(rx.data, item.rx_data(:).'), 'решения'; ...
              abs(rx.delay - item.delay) < 1e-8, 'оценка задержки'; ...
              abs(rx.frequency - item.frequency) < 1e-10, 'оценка частоты'};
    for k = 1:size(checks,1)
      if ~checks{k,1}, passed = false; message = sprintf('%s сигнал %d: %s', message, c, checks{k,2}); end
    end
  end
  if passed, status = 'PASS'; else, status = 'FAIL'; ok = false; end
  fprintf('%s %-64s TX %.1e RX %.1e%s\n', status, v.name, max_tx, max_rx, message);
end
if ok
  fprintf('Совпадают с Python: %d из %d модемов\n', numel(files), numel(files));
else
  error('Есть расхождения с Python');
end
end

function z = unpack(s)
z = s.re(:).' + 1i * s.im(:).';
end
