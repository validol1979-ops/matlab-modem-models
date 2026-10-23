function run_demo(stop_time)
% Открывает модель simo_maximal_ratio_combining_2010_08_27 и запускает симуляцию с осциллографами.
%   run_demo          - стандартная длительность
%   run_demo(1e4)     - своя длительность (в единицах модельного времени)
if nargin < 1
    stop_time = 32768;
end
here = fileparts(mfilename('fullpath'));
model = 'simo_maximal_ratio_combining_2010_08_27';
open_system(fullfile(here, [model '.mdl']));
% Совместимость с R2020b: явные размерности портов интерполятора Фарроу.
set_param([model '/cubic_farrow_interpolator/in'], 'PortDimensions', '2');
set_param([model '/cubic_farrow_interpolator/mu'], 'PortDimensions', '1');
set_param(model, 'StopTime', num2str(stop_time, 17));
sim(model);
end
