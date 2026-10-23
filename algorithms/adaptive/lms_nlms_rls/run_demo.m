function results = run_demo(N)
%RUN_DEMO Сравнение исходных LMS/NLMS/RLS и пример компенсации шума.
if nargin < 1, N = 16000; end
validateattributes(N, {'numeric'}, {'scalar', 'integer', '>=', 1000, 'finite'});
here = fileparts(mfilename('fullpath'));
oldpath = path;
pathCleanup = onCleanup(@() path(oldpath)); %#ok<NASGU>
addpath(here);
state = rng;
rngCleanup = onCleanup(@() rng(state)); %#ok<NASGU>
rng(7, 'twister');
fs = 8000;
t = (0:N-1)'/fs;
M = 20;
% Сигнал и наборы параметров из demo3.m; wgn(-20 dBW) = 0.1*randn.
d = cos(2*pi*723*t) + sin(2*pi*456*t);
x = d + 0.1*randn(N,1);
steps = {[0.0005 0.001 0.005 0.01], [0.005 0.01 0.05 0.1], [1 0.9999 0.999 0.99]};
names = {'LMS', 'NLMS', 'RLS'};
for method = 1:3
    figure('Name', [names{method} ': parameters from demo3'], 'NumberTitle', 'off');
    labels = cell(1,4);
    for k = 1:4
        value = steps{method}(k);
        [e, ~, w] = original_filter(method, d, x, value, M);
        assert(all(isfinite(e)) && all(isfinite(w(:))));
        labels{k} = sprintf('%g', value);
        subplot(2,1,1); plot(t, w(M,:)); hold on;
        subplot(2,1,2); plot(t, filter(ones(200,1)/200, 1, e.^2)); hold on;
    end
    subplot(2,1,1); grid on; xlabel('Time (s)'); ylabel('Last tap');
    title([names{method} ': last stored coefficient']); legend(labels, 'Location', 'best');
    subplot(2,1,2); grid on; xlabel('Time (s)'); ylabel('Mean squared error (200 samples)');
    legend(labels, 'Location', 'best');
end
figure('Name', 'Adaptive filters: demo3 comparison', 'NumberTitle', 'off', ...
    'Position', [80 80 1100 800]);
parameters = [0.001 0.01 0.9999];
for method = 1:3
    [e,y,w] = original_filter(method, d, x, parameters(method), M);
    subplot(3,2,2*method-1);
    tail = max(1,N-399):N;
    plot(t(tail), [d(tail), x(tail), y(tail)]); grid on;
    title(names{method}); xlabel('Time (s)'); ylabel('Amplitude');
    legend('Desired d', 'Noisy input x', 'Output y', 'Location', 'best');
    subplot(3,2,2*method);
    plot(t, filter(ones(200,1)/200,1,e.^2)); grid on;
    xlabel('Time (s)'); ylabel('Mean squared error (200 samples)');
    results.(names{method}).tail_mse = mean(e(floor(N/2):end).^2);
    results.(names{method}).final_weights = w(:,end);
    fprintf('%s: second-half MSE = %.6g\n', names{method}, results.(names{method}).tail_mse);
end
% Синтетический ANC-сценарий 2 из demo2.m, без аудиоустройства.
signal = cos(2*pi*20*t);
noise = 0.1*randn(N,1);
d = signal + noise;
x = sin(1./(1+exp(-noise)));
parameters = [0.1 0.8 0.9999];
figure('Name', 'ANC: synthetic scenario from demo2', 'NumberTitle', 'off');
for method = 1:3
    [e,~,~] = original_filter(method,d,x,parameters(method),M);
    assert(all(isfinite(e)));
    subplot(3,1,method); plot(t(tail), [signal(tail), d(tail), e(tail)]); grid on;
    title(names{method}); xlabel('Time (s)'); ylabel('Amplitude');
    legend('Clean signal', 'Signal + noise', 'ANC residual e', 'Location', 'best');
    results.(names{method}).anc_tail_mse = mean((e(floor(N/2):end)-signal(floor(N/2):end)).^2);
end
drawnow;
end

function [e,y,w] = original_filter(method,d,x,value,M)
switch method
    case 1, [e,y,w] = myLMS(d,x,value,M);
    case 2, [e,y,w] = myNLMS(d,x,value,M,0.01);
    case 3, [e,y,w] = myRLS(d,x,value,M);
end
end
