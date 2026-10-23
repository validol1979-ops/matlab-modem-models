clc; clear; close all;

%% Exercise 2.1

chars = ['a':'z', ' ', '.', ',', '!', ';', '"'];

codes = dec2bin(0:31, 5);

Mapset = cell(32, 2);
for i = 1:32
    Mapset{i,1} = chars(i);
    Mapset{i,2} = codes(i,:);
end


%% Exercise 2.3

message = 'signal';

% ---- Bit rate = 1 bps ----
tx_1bps = freq_coding(message, 1);

t1 = (0:length(tx_1bps)-1)/100;
figure;
plot(t1, tx_1bps);
grid on;
xlabel('Time (s)');
ylabel('Amplitude');
title('Frequency Coding of "signal" (1 bit/sec)');
saveas(gcf, 'fig_ex2_3_signal_1bps.png');

% ---- Bit rate = 5 bps ----
tx_5bps = freq_coding(message, 5);

t5 = (0:length(tx_5bps)-1)/100;
figure;
plot(t5, tx_5bps);
grid on;
xlabel('Time (s)');
ylabel('Amplitude');
title('Frequency Coding of "signal" (5 bits/sec)');
saveas(gcf, 'fig_ex2_3_signal_5bps.png');


%% Exercise 2.4

msg = 'signal';

% ---- 1 bit/sec ----
tx_1bps = freq_coding(msg, 1);
rx_msg_1bps = freq_decoding(tx_1bps, 1);

disp('Decoded message (1 bit/sec):');
disp(rx_msg_1bps);

% ---- 5 bits/sec ----
tx_5bps = freq_coding(msg, 5);
rx_msg_5bps = freq_decoding(tx_5bps, 5);

disp('Decoded message (5 bits/sec):');
disp(rx_msg_5bps);

%% Exercise 2.5

msg = 'signal';
noise_var = 0.0001;          
noise_std = sqrt(noise_var); 

% Case 1: 1 bit/sec
tx_1bps = freq_coding(msg, 1);

noise_1bps = noise_std * randn(size(tx_1bps));
rx_1bps = tx_1bps + noise_1bps;

decoded_1bps = freq_decoding(rx_1bps, 1);

disp('Decoded message with noise (1 bit/sec):');
disp(decoded_1bps);

% Case 2: 5 bits/sec
tx_5bps = freq_coding(msg, 5);

noise_5bps = noise_std * randn(size(tx_5bps));
rx_5bps = tx_5bps + noise_5bps;

decoded_5bps = freq_decoding(rx_5bps, 5);

disp('Decoded message with noise (5 bits/sec):');
disp(decoded_5bps);

%% Exercise 2.6
clc; clear; close all;

msg = 'signal';

% Noise variances to test (gradually increasing)
noise_vars = [0.01 0.1 0.5 1 1.5 2 3 5];

disp('--- Noise Robustness Test ---');

for nv = noise_vars
    noise_std = sqrt(nv);
    
    % 1 bit/sec
    tx_1bps = freq_coding(msg, 1);
    rx_1bps = tx_1bps + noise_std * randn(size(tx_1bps));
    dec_1bps = freq_decoding(rx_1bps, 1);
    
    % 5 bits/sec
    tx_5bps = freq_coding(msg, 5);
    rx_5bps = tx_5bps + noise_std * randn(size(tx_5bps));
    dec_5bps = freq_decoding(rx_5bps, 5);
    
    fprintf('\nNoise variance = %.4f\n', nv);
    fprintf('  1 bit/sec decoded: %s\n', dec_1bps);
    fprintf('  5 bits/sec decoded: %s\n', dec_5bps);
end
