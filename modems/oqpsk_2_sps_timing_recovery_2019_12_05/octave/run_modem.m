function result = run_modem()
  % Путь определяется по файлу, а не по текущему рабочему каталогу.
  here = fileparts(mfilename('fullpath'));
  root = fileparts(fileparts(fileparts(here)));
  addpath(fullfile(root, 'common', 'octave'));
  cfg = jsondecode(fileread(fullfile(fileparts(here), 'config.json')));
  result = modem_demo(cfg);
end
