function run_demo(stop_time)
% Открывает модель msk_modulator_2008_06_22 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 4096;
end
here = fileparts(mfilename('fullpath'));
model = 'msk_modulator_2008_06_22';
model_file = fullfile(here, 'matlab', [model '.mdl']);
if exist(model_file, 'file') ~= 2
    error('own:HistoricalModelMissing', ...
          'историческая модель не входит в публичный репозиторий, см. THIRD_PARTY.md');
end
open_system(model_file);
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
