function results = run_demo()
%RUN_DEMO Пять исходных рисунков: диаграммы решётки и усиление по шуму.
here = fileparts(mfilename('fullpath'));
oldpath = path;
pathCleanup = onCleanup(@() path(oldpath)); %#ok<NASGU>
addpath(here);
results.pattern = run_figure('Fig7_4.m');
results.white_noise_gain = run_figure('Fig7_2.m');
fprintf('Beamforming: 4 polar patterns (1, 2, 4, 8 kHz), 1 white-noise gain plot.\n');
drawnow;
end

function result = run_figure(filename)
% Изолируем переменные скрипта; убираем только очистку окон и workspace.
code = fileread(fullfile(fileparts(mfilename('fullpath')), filename));
code = strrep(code, 'close all; clc; clear all;', '');
existing = findall(0, 'Type', 'figure');
eval(code);
if strcmp(filename, 'Fig7_4.m')
    figs = setdiff(findall(0, 'Type', 'figure'), existing);
    % Порядок создания хранится в обратном порядке в списке Children.
    allfigs = get(0, 'Children');
    figs = flipud(allfigs(ismember(allfigs, figs))); 
    for k = 1:4
        set(figs(k), 'Name', sprintf('Fig7.4: 8 microphones, %g kHz', f_vec(k)/1000), ...
            'NumberTitle', 'off');
    end
    assert(all(isfinite(Ba)));
    result.frequencies_hz = f_vec;
    result.last_pattern = Ba;
else
    set(gcf, 'Name', 'Fig7.2: delay-and-sum white-noise gain', 'NumberTitle', 'off');
    xlabel('Frequency (kHz)'); ylabel('White-noise gain (dB)');
    legend('M = 2', 'M = 4', 'M = 6', 'M = 8', 'Location', 'best');
    assert(all(isfinite(W_dB_values(:))));
    result.sensor_counts = M_values;
    result.gain_db = W_dB_values;
end
end
