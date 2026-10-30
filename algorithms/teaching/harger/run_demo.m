function run_demo()
%RUN_DEMO Три исходных упражнения по фильтрации и спектральному анализу.
root = fileparts(mfilename('fullpath'));
original = fullfile(root, 'original');
if exist(original, 'dir') ~= 7
    error('modems:MissingOriginal', ...
        'исходные скрипты не входят в публичный репозиторий, см. THIRD_PARTY.md');
end
% Проверяем комплект до добавления путей и запуска вычислений.
sourceFiles = {
    'Unsorted/ex2_3.m';
    'Unsorted/ex3_1.m';
    'Unsorted/ex3_5.m';
};
for sourceIndex = 1:numel(sourceFiles)
    if exist(fullfile(original, sourceFiles{sourceIndex}), 'file') ~= 2
        error('modems:MissingSource', 'Missing original file: %s', sourceFiles{sourceIndex});
    end
end
oldPath = path;
oldRng = rng;
oldPause = pause('query');
cleanup = onCleanup(@() restore_state(oldPath, oldRng, oldPause)); %#ok<NASGU>
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
    run_example(fullfile(original, 'Unsorted', examples{example}));
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
