function results = run_demo(N)
%RUN_DEMO 4-QAM: исходная ZCTED-петля с включёнными статическими графиками.
if nargin < 1
    N = 4000;
end
validateattributes(N, {'numeric'}, {'scalar', 'integer', '>=', 1000, 'finite'});
root = fileparts(mfilename('fullpath'));
oldPath = path;
oldRng = rng;
cleanup = onCleanup(@() restore_state(oldPath, oldRng)); %#ok<NASGU>
addpath(root);
rng(7, 'twister');
L = 32;
rollOff = 0.2;
rcDelay = 10;
timeOffset = 25;
EsN0 = 20;
Ksym = 1/sqrt(2);
const = Ksym * [-1-1i, -1+1i, 1-1i, 1+1i];
symbols = const(randi(4, N, 1));
symbols = symbols(:);
% Тот же RRC-импульс единичной энергии, что в передающем/приёмном
% фильтрах main.m. Явная формула позволяет запускать демо и в Octave.
h = root_raised_cosine(rollOff, rcDelay, L);
up = zeros(N*L, 1);
up(1:L:end) = symbols;
tx = filter(h, 1, up);
delayed = [zeros(timeOffset, 1); tx(1:end-timeOffset)];
% Es=1; после согласованного фильтра дисперсия комплексного шума N0.
noiseVariance = 10^(-EsN0/10);
rx = delayed + sqrt(noiseVariance/2) * ...
    (randn(size(delayed)) + 1i*randn(size(delayed)));
mfOut = filter(h, 1, rx);
% Наклон аналитической S-кривой ZCTED, как в calcSCurve/calcTedKp:
% g(tau)=p(1/2-tau)-p(-1/2-tau), шаг tau=1/1000.
dt = 1/1000;
tau = [-dt dt];
g = raised_cosine(0.5-tau, rollOff) - raised_cosine(-0.5-tau, rollOff);
Kp = (g(2)-g(1))/(2*dt);
[K1, K2] = piLoopConstants(Kp, -1, 1, 0.01, L);
debug_tl_static = 1;
debug_tl_runtime = 0;
synced = symbolTimingSync('ZCTED', 2, L, rx, mfOut, K1, K2, ...
    const, Ksym, rollOff, rcDelay, debug_tl_static, debug_tl_runtime);
noSync = mfOut(1:L:end);
ideal = mfOut(1+timeOffset:L:end);
skip = floor(0.2*N);
sequences = {noSync(skip:end), ideal(skip:end), synced(skip:end)};
labels = {'No timing correction', 'Known delay', 'ZCTED + quadratic'};
mer = zeros(1,3);
figure('Name', '4-QAM: timing recovery', 'NumberTitle', 'off', ...
    'Position', [100 100 1200 380]);
for panel = 1:3
    z = sequences{panel};
    assert(all(isfinite(z)), 'Non-finite timing recovery output.');
    distances = abs(bsxfun(@minus, z(:), const)).^2;
    mer(panel) = 10*log10(1/mean(min(distances, [], 2)));
    subplot(1,3,panel);
    plot(real(z), imag(z), '.', 'MarkerSize', 3);
    hold on; plot(real(const), imag(const), 'rx', 'MarkerSize', 10);
    axis equal; axis([-1.6 1.6 -1.6 1.6]); grid on;
    xlabel('I'); ylabel('Q');
    title(sprintf('%s (MER %.1f dB)', labels{panel}, mer(panel)), 'FontSize', 10);
end
fprintf('ZCTED: %d symbols, L=%d, Kp=%.5g, K1=%.5g, K2=%.5g\n', N, L, Kp, K1, K2);
fprintf('Nearest-constellation MER (dB): no sync %.2f, known delay %.2f, ZCTED %.2f\n', mer);
results = struct('MERdB', mer, 'receivedSymbols', synced, 'symbols', N, ...
    'samplesPerSymbol', L, 'Kp', Kp, 'K1', K1, 'K2', K2);
drawnow;
end

function h = root_raised_cosine(beta, span, L)
t = (-span*L/2:span*L/2).'/L;
h = zeros(size(t));
atZero = abs(t) < 1e-12;
atPole = abs(abs(t)-1/(4*beta)) < 1e-12;
regular = ~(atZero | atPole);
x = t(regular);
h(regular) = (sin(pi*x*(1-beta)) + 4*beta*x.*cos(pi*x*(1+beta))) ...
    ./ (pi*x.*(1-(4*beta*x).^2));
h(atZero) = 1 + beta*(4/pi-1);
h(atPole) = beta/sqrt(2) * ((1+2/pi)*sin(pi/(4*beta)) ...
    + (1-2/pi)*cos(pi/(4*beta)));
h = h/sqrt(sum(h.^2));
end

function p = raised_cosine(t, beta)
p = ones(size(t));
nz = abs(t) > 1e-12;
p(nz) = sin(pi*t(nz))./(pi*t(nz));
p = p.*cos(pi*beta*t)./(1-(2*beta*t).^2);
end

function restore_state(oldPath, oldRng)
path(oldPath);
rng(oldRng);
end
