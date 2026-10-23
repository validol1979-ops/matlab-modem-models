function run_demo()
%RUN_DEMO Три исходных упражнения по фильтрации и спектральному анализу.
root = fileparts(mfilename('fullpath'));
oldPath = path;
oldRng = rng;
oldPause = pause('query');
cleanup = onCleanup(@() restore_state(oldPath, oldRng, oldPause)); %#ok<NASGU>
addpath(root);
% Unsorted не добавляем: там лежат старые freqz/freqs/zplane.
% Выбранные скрипты используют только базовые функции MATLAB.
pause('off');
rng(7, 'twister');
examples = {'ex2_3.m', 'ex3_1.m', 'ex3_5.m'};
labels = {'Pulse smoothing: 8-sample moving average', ...
    'Direct DFT: a tone at bin 5 of 32', ...
    'Two tones in noise: FFT bins 20 and 50 of 512'};
for example = 1:numel(examples)
    fprintf('Harger: %s (%s); pauses are disabled during the demo.\n', ...
        examples{example}, labels{example});
    figure('Name', labels{example}, 'NumberTitle', 'off');
    run_example(fullfile(root, 'Unsorted', examples{example}));
end
drawnow;
end

function run_example(source)
% Отдельная область переменных; исходный текст исполняется без изменений.
eval(fileread(source));
end

function restore_state(oldPath, oldRng, oldPause)
path(oldPath);
rng(oldRng);
pause(oldPause);
end
