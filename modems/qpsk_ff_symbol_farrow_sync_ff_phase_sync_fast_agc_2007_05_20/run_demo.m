function run_demo(stop_time)
% Открывает модель qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 16384;
end
here = fileparts(mfilename('fullpath'));
model = 'qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
