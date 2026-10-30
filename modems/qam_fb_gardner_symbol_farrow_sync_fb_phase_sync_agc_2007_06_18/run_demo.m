function run_demo(stop_time)
% Открывает модель qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 16384;
end
here = fileparts(mfilename('fullpath'));
model = 'qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18';
model_file = fullfile(here, 'matlab', [model '.mdl']);
if exist(model_file, 'file') ~= 2
    error('own:HistoricalModelMissing', ...
          'историческая модель не входит в публичный репозиторий, см. THIRD_PARTY.md');
end
open_system(model_file);
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
