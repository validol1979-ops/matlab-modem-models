function test_original()
% Отдельная проверка новых оригиналов без изменения архивных файлов.
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
addpath(fullfile(root,'tools'));
matlab_check_research(16384,'qpsk_8_sps_fb_sync_2020_11_25');
end
