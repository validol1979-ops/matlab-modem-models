function research_check(vector_path,output_path)
% Общие стимулы читаются из файла, ожидаемые значения недоступны DSP-функциям.
ops={'fir','dft','pfb','lms','nlms','rls','ldpc','stft','istft','omlsa','beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','costas','timing','notch','kalman','wola','wsinc','alamouti','gf2_encode'};
f=fopen(vector_path,'r'); assert(f>=0,'Cannot read DSP vectors'); cleanup=onCleanup(@() fclose(f));
count=fscanf(f,'%d',1); result=cell(count,1); maximum=0;
for k=1:count
  header=fscanf(f,'%d',5); assert(numel(header)==5,'Truncated vector header');
  op=header(1); p=fscanf(f,'%f',header(2));x=read_complex(f,header(3));a=read_complex(f,header(4));expected=read_complex(f,header(5));
  actual=research_core(ops{op+1},p,x,a);
  assert(numel(actual)==numel(expected),'DSP output length mismatch');
  delta=max(abs(actual(:)-expected(:))); limit=1e-8*(1+abs(expected(:)));
  assert(all(isfinite(actual)) && all(abs(actual(:)-expected(:))<=limit),'DSP numeric mismatch');
  repeated=research_core(ops{op+1},p,x,a);assert(isequal(actual,repeated),'DSP restart mismatch');
  maximum=max(maximum,delta);result{k}=struct('case',k-1,'operation',ops{op+1},'status','PASS','values',numel(actual),'maximum_error',delta);
end
fout=fopen(output_path,'w');assert(fout>=0,'Cannot write DSP results');fprintf(fout,'%s\n',jsonencode(result));fclose(fout);
fprintf('PASS %d DSP cases; maximum error %.12g\n',count,maximum);
end
function x=read_complex(f,count)
a=fscanf(f,'%f',[2,count]);assert(numel(a)==2*count,'Truncated complex vector');x=complex(a(1,:),a(2,:));
end
