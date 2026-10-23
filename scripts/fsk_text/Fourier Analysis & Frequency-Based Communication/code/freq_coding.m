function tx_signal = freq_coding(message, bit_rate)
% Exercise 2.2: Frequency-based encoder
% message  : input string
% bit_rate : bits per second (1 to 5)

fs = 100;                 % Sampling frequency (Hz)
Ts = 1/fs;
t_sym = 0:Ts:1-Ts;        % 1 second per symbol

% Allowed characters and mapping
chars = ['a':'z', ' ', '.', ',', '!', ';', '"'];
codes = dec2bin(0:31, 5);

% Convert message to bitstream
bitstream = '';
for k = 1:length(message)
    idx = find(chars == message(k));
    bitstream = [bitstream codes(idx,:)];
end

% Truncate bitstream to fit bit_rate
num_symbols = floor(length(bitstream)/bit_rate);
bitstream = bitstream(1:num_symbols*bit_rate);

% Frequency selection (well separated, positive only)
num_freqs = 2^bit_rate;
freqs = round(linspace(5, 49, num_freqs));

tx_signal = [];

% Encode symbols
for i = 1:num_symbols
    bits = bitstream((i-1)*bit_rate+1 : i*bit_rate);
    idx = bin2dec(bits) + 1;   % 1-based index
    f = freqs(idx);
    tx_signal = [tx_signal sin(2*pi*f*t_sym)];
end
