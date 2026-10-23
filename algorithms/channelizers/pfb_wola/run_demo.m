function results = run_demo()
%RUN_DEMO Исходные chirp-демо PFB и WOLA при D=M и D<M.
here = fileparts(mfilename('fullpath'));
oldpath = path;
pathCleanup = onCleanup(@() path(oldpath)); %#ok<NASGU>
addpath(here, fullfile(here, '..', '..', 'filters', 'windowed_sinc'));
assert(exist('wsinc', 'file') == 2, 'The sibling windowed_sinc folder is required.');
results = struct([]);
for k = 1:2
    D = [8 6];
    [yp, bp] = pfb_channelizer_demo(8, D(k), 8000, 1000, 0.35, 'hamming', 40);
    set(gcf, 'Name', sprintf('PFB: M=8, D=%d', D(k)), 'NumberTitle', 'off');
    set(gcf, 'IntegerHandle', 'off'); % Освобождаем номер 101 для следующего демо.
    [yw, bw] = wola_channelizer_demo(8, D(k), 8000, 1000, 0.35, 'hamming', 40);
    set(gcf, 'Name', sprintf('WOLA: M=8, D=%d', D(k)), 'NumberTitle', 'off');
    set(gcf, 'IntegerHandle', 'off');
    assert(isequal(bp, bw) && isequal(size(yp), size(yw)));
    difference = max(abs(yp(:)-yw(:)));
    assert(all(isfinite(yp(:))) && all(isfinite(yw(:))));
    assert(difference < 1e-10, 'PFB/WOLA outputs disagree.');
    fprintf('D=%d, fsout=%g Hz, max |PFB-WOLA| = %.3g\n', D(k), 8000/D(k), difference);
    results(k).decimation = D(k);
    results(k).max_difference = difference;
    results(k).output_size = size(yp);
end
drawnow;
end
