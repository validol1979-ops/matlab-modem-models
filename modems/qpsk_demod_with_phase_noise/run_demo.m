function run_demo(stop_time)
% Открывает модель qpsk_demod_with_phase_noise и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 0.0014563555555555556;
end
here = fileparts(mfilename('fullpath'));
model = 'costas_loop_qpsk_complex_realization';
model_file = fullfile(here, 'matlab', [model '.mdl']);
if exist(model_file, 'file') ~= 2
    error('own:HistoricalModelMissing', ...
          'историческая модель не входит в публичный репозиторий, см. THIRD_PARTY.md');
end
open_system(model_file);
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
