function report = run_own(options)
% Собственная реализация модема qpsk_phase_noise_phase_sync_2009_04_12 на MATLAB (без тулбоксов).
% Параметры модема берутся из config.json, общий код - в папке common.
%   run_own                              - демонстрация с графиками
%   run_own(struct('snr_db',15))         - свой SNR, дБ
%   r = run_own(struct('plot',false))    - только числа
if nargin < 1, options = struct(); end
here = fileparts(mfilename('fullpath'));
addpath(fullfile(here, '..', '..', 'common'));
report = modem_own_demo(here, options);
end
