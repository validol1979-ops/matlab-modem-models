function matlab_research_references()
% Исполняем выбранные оригинальные функции отдельно от переносимых аналогов.
root=fileparts(fileparts(mfilename('fullpath')));dest=fullfile(root,'build','typed','originals');
if ~isfolder(dest),mkdir(dest);end
oldpath=path;oldpwd=pwd;cleanup=onCleanup(@() restore(oldpath,oldpwd));
addpath(fullfile(root,'common','octave'));base=fullfile(root,'research','dsp_global_20260930','sources');
results={};rng(92030,'twister');
addpath(fullfile(base,'china_adaptive'));
x=randn(1,256);desired=filter([.6 -.2 .15],1,x);names={'lms','nlms','rls'};adaptive=cell(3,1);
for k=1:3
  switch k
  case 1
    p=[3 .05 .01];[e,y,w]=myLMS(desired,x,p(2),3);weights=flipud(w(:,end));
  case 2
    p=[3 .6 .01];[e,y,w]=myNLMS(desired,x,p(2),3,p(3));weights=flipud(w(:,end));
  case 3
    p=[3 .995 100];[e,y,w]=myRLS(desired,x,p(2),3);weights=w(:,end);
  end
  expected=[y(:).' e(:).' weights(:).'];portable=research_core(names{k},p,x,desired);
  err=max(abs(expected-portable));assert(err<1e-10,'Original adaptive reference mismatch');
  adaptive{k}=struct('operation',names{k},'parameters',p,'x',x,'auxiliary',desired,'expected',expected);
  results{end+1}=struct('name',['original_' names{k}],'status','PASS','maximum_error',err);
end
save(fullfile(dest,'adaptive.mat'),'adaptive','-v7');rmpath(fullfile(base,'china_adaptive'));
addpath(fullfile(base,'channelizer'));
x=randn(256,1)+1i*randn(256,1);h=fir1(31,.2);channelizers={};
for D=[3 4]
  pfb=pfb_chanex(x,4,D,reshape(h,4,[]));wola=wola_chanex(x,4,D,h(:));
  assert(max(abs(pfb(:)-wola(:)))<1e-10,'Original PFB/WOLA disagreement');
  portable=reshape(research_core('pfb',[4 D],x,h),4,[]).';
  % Авторский порядок частотных каналов противоположен принятому в переносимом контракте.
  portable=portable(1:size(pfb,1),[1 4 3 2]);err=max(abs(pfb(:)-portable(:)));
  assert(err<1e-10,'Original channelizer reference mismatch');
  results{end+1}=struct('name',sprintf('original_channelizer_D%d',D),'status','PASS','maximum_error',err);
  channelizers{end+1}=struct('x',x,'h',h,'decimation',D,'expected',pfb);
end
save(fullfile(dest,'channelizers.mat'),'channelizers','-v7');rmpath(fullfile(base,'channelizer'));
addpath(fullfile(base,'china_ldpc','Encoder'),fullfile(base,'china_ldpc','Decoder'));
cd(fullfile(base,'china_ldpc'));[H,Hp,Hs]=HxMatrixGen();cd(oldpwd);
information=randi([0 1],1,1008);word=Encoder2(Hs,Hp,information);assert(~any(mod(H*word.',2)),'Original LDPC encoder syndrome');
llr=6*(1-2*word);llr(1101)=-.12*llr(1101);decoded=cell(4,1);
for mode=0:3
  switch mode
  case 0,decoded{mode+1}=LDPCDecoder_SP(H,llr,8);
  case 1,decoded{mode+1}=LDPCDecoder_MS(H,llr,8);
  case 2,decoded{mode+1}=LDPCDecoder_NMS(H,llr,.8,8);
  case 3,decoded{mode+1}=LDPCDecoder_OMS(H,llr,.15,8);
  end
  assert(isequal(decoded{mode+1},information),'Original LDPC payload mismatch');
  results{end+1}=struct('name',sprintf('original_ldpc_mode_%d',mode),'status','PASS','payload_bits',1008,'corrected_channel_errors',1);
end
save(fullfile(dest,'ldpc.mat'),'H','information','word','llr','decoded','-v7');
rmpath(fullfile(base,'china_ldpc','Encoder'),fullfile(base,'china_ldpc','Decoder'));
addpath(fullfile(base,'timing'));
[k1,k2]=piLoopConstants(2,-1,1,.01,8);theta=.01/8/1.25;
assert(abs(k1-4*theta/(1+2*theta+theta^2)/(-2))<1e-15 && abs(k2-4*theta^2/(1+2*theta+theta^2)/(-2))<1e-15,'PI constants mismatch');
results{end+1}=struct('name','original_pi_loop_constants','status','PASS');rmpath(fullfile(base,'timing'));
% Переносимые модемные функции дополнительно проверяем в MATLAB, а не только в Octave.
for name={'oqpsk_2_sps_timing_recovery_2019_12_05','qpsk_8_sps_fb_sync_2020_11_25','qpsk_script_basic','qpsk_script_costas'}
  cfg=jsondecode(fileread(fullfile(root,'modems',name{1},'config.json')));modem_test(cfg);
  results{end+1}=struct('name',['portable_' name{1}],'status','PASS');
end
f=fopen(fullfile(dest,'checks.json'),'w');fprintf(f,'%s\n',jsonencode(results));fclose(f);
fprintf('PASS %d original-reference and MATLAB portable-modem checks\n',numel(results));
end
function restore(oldpath,oldpwd)
path(oldpath);cd(oldpwd);
end
