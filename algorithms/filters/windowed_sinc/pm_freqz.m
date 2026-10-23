function H = pm_freqz(b,a,f,fs)
% Usage: H = pm_freqz(b,a,f,fs)
%
% Stripped-down freqz.
%
%  b..........1-d array, numerator transfer function coefficients
%  a..........1-d array, denominator transfer function coefficients
%  f..........1-d array of frequencies to evaluate (Hz)
%  fs.........sampling frequency (Hz)
%

    a = a(:);
    b = b(:);
    w = 2*pi*f(:)/fs;

    k = max (numel(b), numel(a));
    Ha = polyval(postpad(a,k), exp (j*w));
    Hb = polyval(postpad(b,k), exp (j*w));
    H = Hb ./ Ha;

end % function

function y = postpad(x,N)
    [xs,ns] = shiftdim(x);
    y = zeros(N,1);
    y(1:numel(xs)) = xs;
    y = shiftdim(y,-ns);
end % function
