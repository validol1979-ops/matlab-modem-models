%% Exercise 1.2 – Subsection (a)

fs = 100;                
Ts = 1/fs;           
t_start = 0;
t_end = 1;

t = t_start:Ts:t_end;   
x = cos(30*pi*t + pi/4);

figure;
plot(t, x, 'LineWidth', 1.5);
grid on;
xlabel('Time (s)');
ylabel('x(t)');
title('Time-Domain Signal: x(t) = cos(30\pi t + \pi/4)');
saveas(gcf, 'fig_ex1_2_time.png');



%% Exercise 1.2 – Subsection (b)

N = length(x);                          
X = fftshift(fft(x));                   
X_mag = abs(X);
X_mag = X_mag / max(X_mag);             

f = (-N/2:N/2-1) * (fs/N);             

figure;
plot(f, X_mag, 'LineWidth', 1.5);
grid on;
xlabel('Frequency (Hz)');
ylabel('|X(f)| (normalized)');
title('Magnitude Spectrum of x(t)');
xlim([-25 25]);
ylim([0 1.1]);
saveas(gcf, 'fig_ex1_2_freq_mag.png');



%% Exercise 1.2 – Subsection (c)
tol = 1e-6;
X_phase = X;
X_phase(abs(X_phase) < tol) = 0;         
theta = angle(X_phase);

figure;
plot(f, theta/pi, 'LineWidth', 1.5);
grid on;
xlabel('Frequency (Hz)');
ylabel('Phase / \pi');
title('Phase Spectrum of x(t)');
xlim([-25 25]);
saveas(gcf, 'fig_ex1_2_phase.png');
