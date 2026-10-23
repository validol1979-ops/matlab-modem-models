function run_demo(stop_time)
% Открывает модель msk_modulator_2008_06_22 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 4096;
end
here = fileparts(mfilename('fullpath'));
model = 'msk_modulator_2008_06_22';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
