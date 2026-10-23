% synch.m  a function m-filecomputing the synch function
% w is a vector of coordinates between 0 and 2pi 
% sensibly, the integer M < length(w)
%
function s=synch(w,M)
L=length(w);
for n=1:L
	if w(n)==0 | w(n)==2*pi
		s(n)=1;
	else
		s(n)=sin((M+1)*w(n)/2)/((M+1)*sin(w(n)/2));
	end
end

