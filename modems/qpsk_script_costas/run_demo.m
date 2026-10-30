function run_demo()
%RUN_DEMO Запуск исходного QPSK-скрипта; TXT остаются во временной папке.
here = fileparts(mfilename('fullpath'));
original = fullfile(here, 'original');
if exist(original, 'dir') ~= 7
    error('modems:MissingOriginal', ...
        'исходные скрипты не входят в публичный репозиторий, см. THIRD_PARTY.md');
end
% Проверяем комплект до добавления путей и запуска вычислений.
sourceFiles = {
    'qpsk_modem_costas.m';
    'rcosfilter.m';
    'demo_lowpass.m';
};
for sourceIndex = 1:numel(sourceFiles)
    if exist(fullfile(original, sourceFiles{sourceIndex}), 'file') ~= 2
        error('modems:MissingSource', 'Missing original file: %s', sourceFiles{sourceIndex});
    end
end
oldPath = path;
oldDir = pwd;
oldRng = rng;
workDir = tempname;
mkdir(workDir);
cleanup = onCleanup(@() restore_state(oldPath, oldDir, oldRng, workDir)); %#ok<NASGU>
addpath(original);
cd(workDir);
rng(7, 'twister');
run_original(fullfile(original, 'qpsk_modem_costas.m'));
drawnow;
end

function run_original(source)
% Отдельная область переменных защищает cleanup от исходного clear all.
% run(source) меняет папку на original; eval оставляет экспорт TXT в workDir.
eval(fileread(source));
end

function restore_state(oldPath, oldDir, oldRng, workDir)
cd(oldDir);
path(oldPath);
rng(oldRng);
rmdir(workDir, 's');
end
