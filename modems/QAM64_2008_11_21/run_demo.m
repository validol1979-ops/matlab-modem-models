function run_demo(stop_time)
% Открывает модель QAM64_2008_11_21 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 16384;
end
here = fileparts(mfilename('fullpath'));
model = 'QAM64_2008_11_21';
open_system(fullfile(here, [model '.mdl']));
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
