function run_demo(stop_time)
% Открывает модель psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 16384;
end
here = fileparts(mfilename('fullpath'));
model = 'psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
