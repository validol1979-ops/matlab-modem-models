function results = run_demo(N)
%RUN_DEMO Короткое сравнение исходных LDPC-декодеров; N кадров на точку.
if nargin < 1
    N = 2;
end
validateattributes(N, {'numeric'}, {'scalar', 'integer', 'positive', 'finite'});
root = fileparts(mfilename('fullpath'));
oldPath = path;
oldDir = pwd;
oldRng = rng;
cleanup = onCleanup(@() restore_state(oldPath, oldDir, oldRng)); %#ok<NASGU>
addpath(root, fullfile(root, 'Encoder'), fullfile(root, 'Decoder'));
% HxMatrixGen загружает матрицу по относительному имени.
cd(root);
rng(7, 'twister');
[H, Hp, Hs] = HxMatrixGen();
H = sparse(H);
K = 1008;
R = K / 2016;
ebn0 = [0 3];
iterMax = 5;
names = {'SP', 'MS', 'NMS', 'OMS'};
decoders = {@(llr) LDPCDecoder_SP(H, llr, iterMax), ...
    @(llr) LDPCDecoder_MS(H, llr, iterMax), ...
    @(llr) LDPCDecoder_NMS(H, llr, 0.7, iterMax), ...
    @(llr) LDPCDecoder_OMS(H, llr, 0.5, iterMax)};
bitErrors = zeros(4, numel(ebn0));
frameErrors = bitErrors;
rawErrors = zeros(size(ebn0));
timer = tic;
for snrIndex = 1:numel(ebn0)
    sigma = sqrt(1 / (2 * R * 10^(ebn0(snrIndex)/10)));
    for frame = 1:N
        s = randi([0 1], 1, K);
        x = Encoder2(Hs, Hp, s);
        assert(all(mod(H * x.', 2) == 0), 'Invalid LDPC codeword.');
        y = 1 - 2*x + sigma*randn(size(x));
        llr = 2*y / sigma^2;
        rawErrors(snrIndex) = rawErrors(snrIndex) + sum((y(K+1:end) < 0) ~= s);
        for algorithm = 1:4
            decoded = decoders{algorithm}(llr);
            errors = sum(decoded ~= s);
            bitErrors(algorithm, snrIndex) = bitErrors(algorithm, snrIndex) + errors;
            frameErrors(algorithm, snrIndex) = frameErrors(algorithm, snrIndex) + (errors > 0);
        end
        fprintf('Eb/N0 = %g dB: frame %d/%d done (%.1f s)\n', ...
            ebn0(snrIndex), frame, N, toc(timer));
    end
end
results = struct('EbN0dB', ebn0, 'BER', bitErrors/(K*N), ...
    'FER', frameErrors/N, 'rawBER', rawErrors/(K*N), ...
    'framesPerPoint', N, 'iterations', iterMax);
figure('Name', 'LDPC: short BPSK/AWGN experiment', 'NumberTitle', 'off');
subplot(2,1,1);
plot(ebn0, [results.rawBER; results.BER].', '-o', 'LineWidth', 1.2);
grid on;
xlabel('Eb/N0 (dB)'); ylabel('Information-bit BER');
legend([{'Before decoding'}, names], 'Location', 'northeast');
title(sprintf('LDPC (2016,1008): %d frame(s)/point, at most %d iterations', N, iterMax));
subplot(2,1,2);
plot(ebn0, results.FER.', '-o', 'LineWidth', 1.2);
grid on; ylim([0 1.05]);
xlabel('Eb/N0 (dB)'); ylabel('FER'); legend(names, 'Location', 'northeast');
fprintf('BER rows: SP, MS, NMS, OMS; columns: 0 and 3 dB\n');
disp(results.BER);
fprintf('Small sample: this demonstrates execution, not reliable BER/FER curves.\n');
drawnow;
end

function restore_state(oldPath, oldDir, oldRng)
cd(oldDir);
path(oldPath);
rng(oldRng);
end
