function test_modem()
  % Проверяем перенос независимо от рабочего каталога.
  here = fileparts(mfilename('fullpath'));
  addpath(fullfile(fileparts(fileparts(fileparts(here))), 'common', 'octave'));
  cfg = jsondecode(fileread(fullfile(fileparts(here), 'config.json')));
  modem_test(cfg);
end
