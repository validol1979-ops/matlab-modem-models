%% Exercise 1.1 – Subsection (a)


fs = 50;               
Ts = 1/fs;              
t_start = -1;
t_end = 1;

t = t_start:Ts:t_end;    
x = cos(10*pi*t);        

figure;
plot(t, x, 'LineWidth', 1.5);
grid on;
xlabel('Time (s)');
ylabel('x(t)');
title('Time-Domain Signal: x(t) = cos(10\pi t)');



%% Exercise 1.1 – Subsection (b)

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
xlim([-15 15]);
ylim([0 1.1]);
