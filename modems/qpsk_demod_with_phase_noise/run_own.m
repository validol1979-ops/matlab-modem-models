function report = run_own(options)
% Собственная реализация модема qpsk_demod_with_phase_noise на MATLAB (без тулбоксов).
% Параметры модема берутся из config.json, общий код - в папке common/own.
%   run_own                              - демонстрация с графиками
%   run_own(struct('snr_db',15))         - свой SNR, дБ
%   r = run_own(struct('plot',false))    - только числа
if nargin < 1, options = struct(); end
here = fileparts(mfilename('fullpath'));
addpath(fullfile(here, '..', '..', 'common', 'own'));
report = own_demo(here, options);
end
