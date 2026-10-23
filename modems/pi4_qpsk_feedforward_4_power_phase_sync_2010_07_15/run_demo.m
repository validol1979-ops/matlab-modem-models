function run_demo(stop_time)
% Открывает модель pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 32768;
end
here = fileparts(mfilename('fullpath'));
model = 'pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
