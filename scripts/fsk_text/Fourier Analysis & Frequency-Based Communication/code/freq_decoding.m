function decoded_message = freq_decoding(rx_signal, bit_rate)
% Exercise 2.4: Frequency-based decoder
% rx_signal : received time-domain signal
% bit_rate  : bits per second (1 to 5)
% output    : decoded text message

fs = 100;                 % Sampling frequency
Ts = 1/fs;
samples_per_sym = fs;     % 1 second per symbol

% Allowed characters and mapping
chars = ['a':'z', ' ', '.', ',', '!', ';', '"'];
codes = dec2bin(0:31, 5);

num_freqs = 2^bit_rate;
freqs = round(linspace(5, 49, num_freqs));

num_symbols = floor(length(rx_signal) / samples_per_sym);

bitstream = '';

for k = 1:num_symbols
    % Extract one symbol (1 second)
    segment = rx_signal((k-1)*samples_per_sym+1 : k*samples_per_sym);
    
    % FFT
    Y = fftshift(fft(segment));
    mag = abs(Y);
    
    % Frequency axis
    f = (-samples_per_sym/2 : samples_per_sym/2-1) * (fs/samples_per_sym);
    
    % Use only positive frequencies
    pos_idx = f > 0;
    f_pos = f(pos_idx);
    mag_pos = mag(pos_idx);
    
    % Find dominant frequency
    [~, idx_max] = max(mag_pos);
    detected_freq = f_pos(idx_max);
    
    % Match detected frequency to nearest reference frequency
    [~, freq_idx] = min(abs(freqs - detected_freq));
    
    % Convert index to binary
    bits = dec2bin(freq_idx-1, bit_rate);
    bitstream = [bitstream bits];
end

% Convert bitstream to characters (5 bits per character)
decoded_message = '';
num_chars = floor(length(bitstream)/5);

for i = 1:num_chars
    bits = bitstream((i-1)*5+1 : i*5);
    idx = bin2dec(bits) + 1;
    decoded_message = [decoded_message chars(idx)];
end
end
