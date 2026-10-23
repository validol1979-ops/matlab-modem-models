function run_demo(stop_time)
% Открывает модель oqpsk_2_sps_timing_recovery_2019_12_05 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 32768;
end
here = fileparts(mfilename('fullpath'));
model = 'oqpsk_2_sps_timing_recovery_2019_12_05';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
