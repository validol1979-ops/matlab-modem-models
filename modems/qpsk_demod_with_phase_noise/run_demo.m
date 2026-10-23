function run_demo(stop_time)
% Открывает модель qpsk_demod_with_phase_noise и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 0.0014563555555555556;
end
here = fileparts(mfilename('fullpath'));
model = 'qpsk_demod_with_phase_noise';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
