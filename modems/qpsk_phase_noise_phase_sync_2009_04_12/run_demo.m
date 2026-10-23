function run_demo(stop_time)
% Открывает модель qpsk_phase_noise_phase_sync_2009_04_12 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 131072;
end
here = fileparts(mfilename('fullpath'));
model = 'qpsk_phase_noise_phase_sync_2009_04_12';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
