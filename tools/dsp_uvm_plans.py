"""Lossless packed physical pin plans for production DSP vectors."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_ofdm import CASES as OFDM_CASES
from run_stft import CASES as STFT_CASES
from run_fir import CASES as FIR_CASES
from ofdm_cases import vectors as ofdm_vectors
from stft_cases import vectors as stft_vectors
from fir_cases import vectors as fir_vectors

CASES={}
for direction,kind in [('tx',2),('rx',3)]:
    for log2n,cp,frames in OFDM_CASES:
        CASES[f'ofdm_{direction}_n{1<<log2n}_cp{cp}']=dict(kind=kind,family='ofdm',direction=direction,
            log2n=log2n,cp=cp,frames=frames,seed=31+log2n+cp,in_width=18,out_width=18)
for direction,kind in [('analysis',4),('synthesis',5)]:
    for log2n,log2hop,transactions in STFT_CASES:
        CASES[f'stft_{direction}_n{1<<log2n}_h{1<<log2hop}']=dict(kind=kind,family='stft',direction=direction,
            log2n=log2n,log2hop=log2hop,transactions=transactions,seed=29,
            in_width=18 if kind==4 else 24,out_width=24 if kind==4 else 18)
for index,(taps,lanes,tmax) in enumerate(FIR_CASES):
    CASES[f'fir_{taps}_l{lanes}_t{tmax}']=dict(kind=1,family='fir',taps=taps,log2lanes=lanes,
        log2tmax=tmax,transactions=4,seed=31+index,in_width=18,out_width=18)


from run_pfb import CASES as PFB_CASES
from pfb_cases import vectors as pfb_vectors
from run_oset import CASES as OSET_CASES, STRESS as OSET_STRESS
from oset_cases import vectors as oset_vectors
from run_fsk import CASES as FSK_CASES
from fsk_cases import vectors as fsk_vectors

for index,(m,lanes,tmax,d,taps) in enumerate(PFB_CASES):
    CASES[f'pfb_m{1<<m}_d{d}_t{taps}_l{lanes}']=dict(kind=6,family='pfb',log2m=m,log2n=m,
        log2lanes=lanes,log2tmax=tmax,d=d,taps=taps,transactions=3,seed=31+index,stress=index==7,
        in_width=18,out_width=24)
for direction,kind in [('notch',7),('kalman',8)]:
    for index,(notch,kalman) in enumerate([*OSET_CASES,(OSET_STRESS['notch'],OSET_STRESS['kalman'])]):
        CASES[f'{direction}_case{index}']=dict(kind=kind,family='oset',direction=direction,notch=notch,kalman=kalman,
            transactions=4,seed=31+index,raw=OSET_STRESS['raw'] if index==len(OSET_CASES) else None,
            in_width=18,out_width=18)
for direction,kind in [('tx',9),('rx',10)]:
    for index,(n,f0,df,order,m,nmax) in enumerate(FSK_CASES):
        CASES[f'fsk_{direction}_n{n}_m{order}']=dict(kind=kind,family='fsk',direction=direction,n=n,f0=f0,df=df,
            order=order,log2m=m,log2nmax=nmax,symbols=40,transactions=3,seed=71+index,
            in_width=max(1,m) if kind==9 else 18,out_width=18 if kind==9 else max(1,m))


from run_beam import CASES as BEAM_CASES
from beam_cases import vectors as beam_vectors
from run_mmse import CASES as MMSE2_CASES
from mmse_cases import vectors as mmse2_vectors
from mmse3_cases import CASES as MMSE3_CASES, vectors as mmse3_vectors

for direction,kind in [('beam',11),('alamouti',12)]:
    for index,(m,weights,log2m) in enumerate(BEAM_CASES):
        CASES[f'{direction}_m{m}_{weights}']=dict(kind=kind,family='beam',direction=direction,m=m,weights=weights,
            log2m=log2m,transactions=4,seed=31+index,in_width=18,out_width=18)
for dimension,kind,names in [(2,15,MMSE2_CASES),(3,16,MMSE3_CASES)]:
    for index,name in enumerate(names):
        CASES[f'mmse{dimension}_{name}']=dict(kind=kind,family='mmse',dimension=dimension,matrix=name,
            seed=(37 if dimension==2 else 53)+index,transactions=3 if dimension==2 else 5,in_width=18,out_width=18)


from run_sync import CASES as SYNC_CASES, transactions_for
from sync_cases import vectors as sync_vectors
from costas_acquisition import PHASES_DEG,CFOS

for direction,kind in [('costas',13),('gardner',14)]:
    for index,(costas,timing,profile) in enumerate(SYNC_CASES):
        CASES[f'{direction}_{profile}']=dict(kind=kind,family='sync',direction=direction,costas=costas,timing=timing,
            profile=profile,transactions=transactions_for(profile),seed=41+index,in_width=18,out_width=18)


from run_omlsa import CASES as OMLSA_CASES
from omlsa_cases import vectors as omlsa_vectors
for index,(n,hop,nnoise,alpha,cplx) in enumerate(OMLSA_CASES):
    CASES[f'omlsa_n{n}_h{hop}_nn{nnoise}']=dict(kind=17,family='omlsa',log2n=n.bit_length()-1,
        log2hop=hop.bit_length()-1,nnoise=nnoise,alpha=alpha,complex_input=cplx,transactions=2,seed=31+index,
        stress=index==4,in_width=18,out_width=18)


from run_ldpc import CASES as LDPC_CASES
from ldpc_cases import vectors as ldpc_vectors,code_for
for direction,kind in [('ldpc',18),('gf2',19)]:
    for index,(mode,code) in enumerate(LDPC_CASES):
        H,A,iterations=code_for(code)
        CASES[f'{direction}_{code}_mode{mode}_case{index}']=dict(kind=kind,family='coding',direction=direction,mode=mode,
            code=code,m=len(H),n=len(H[0]),k=len(A[0]),iterations=iterations,log2nmax=7,log2mmax=6,log2emax=9,log2kmax=6,
            transactions=6,seed=31+index,stress=index==6,in_width=16 if kind==18 else 1,out_width=16 if kind==18 else 1)


from run_lms import CASES as LMS_CASES
from lms_cases import vectors as lms_vectors
from run_rls import CASES as RLS_CASES,STRESS as RLS_STRESS
from rls_cases import vectors as rls_vectors,STRESS_WEIGHT_TRANSACTIONS,STRESS_P_TRANSACTIONS
for index,(mode,step,eps,taps,n) in enumerate(LMS_CASES):
    CASES[f'{mode}_t{taps}_case{index}']=dict(kind=20,family='lms',mode=mode,step=step,eps=eps,taps=taps,
        log2n=n,transactions=3,seed=37+index,stress=index==6,in_width=18,out_width=18)
for index,(lam,eps,taps,noise,n) in enumerate(RLS_CASES):
    CASES[f'rls_t{taps}_case{index}']=dict(kind=21,family='rls',lam=lam,eps=eps,taps=taps,noise=noise,
        log2n=n,transactions=3,seed=37+index,stress=RLS_STRESS.get(index),in_width=18,out_width=18)


def pair_fields(width):return [('re',width,True),('im',width,True)]


def contract(case):
    kind=case['kind'];inputs=pair_fields(case['in_width']);outputs=pair_fields(case['out_width'])
    cfg=pair_fields(18) if kind==1 else []
    if kind==6:cfg=[('tap',18,True),('decimation',case['log2m']+1,False)]
    elif kind in (11,12):cfg=pair_fields(18)
    elif kind in (15,16):cfg=[*pair_fields(18),('lambda',34,False)]
    elif kind in (20,21):
        if kind==20:cfg=[('nlms',1,False),('taps',case['log2n']+1,False),('mu',18,False),('eps',34,False)]
        else:cfg=[('taps',case['log2n']+1,False),('p0',44,False),('lambda',30,False),('invl',32,False)]
        inputs=[(key,18,True) for key in ('xre','xim','dre','dim')]
        outputs=[(key,18,True) for key in ('pre','pim','ere','eim')]
    elif kind in (18,19):
        cfg=[('bit',1,False),('m',case['log2mmax']+1,False)]
        if kind==18:
            cfg += [('n',case['log2nmax']+1,False),('iterations',8,False),('mode',2,False),('alpha',9,False),('beta',16,False)]
            inputs=[('llr',16,True)];outputs=[('bit',1,False),('posterior',16,True)]
        else:
            cfg += [('k',case['log2kmax']+1,False)];inputs=outputs=[('bit',1,False)]
    elif kind==17:cfg=[('nnoise',5,False),('alpha',17,False)]
    elif kind==13:
        cfg=[('k1',32,False),('k2',32,False)];outputs=[*pair_fields(18),('phase',32,True)]
    elif kind==14:
        cfg=[('sps',8,False),('count',16,False),('position',48,False),('k3',32,False),('k4',32,False)]
        outputs=[*pair_fields(18),('position',32,True)]
    elif kind==7:cfg=[('b1',18,True),('a1',18,True),('a2',18,True)]
    elif kind==8:cfg=[('q',32,False),('r',32,False),('p0',32,False)]
    elif kind in (9,10):
        cfg=[('step',32,False),('n',case['log2nmax']+1,False)]
        label=[('label',max(1,case['log2m']),False)]
        if kind==9:inputs=label
        else:outputs=label
    if case['family']=='ofdm':frames=case['frames']+1
    elif case['family']=='stft':frames=case['transactions']+(3 if kind==5 else 0)
    elif kind==1:frames=case['transactions']+int(case['taps']!='single')
    elif kind==6:frames=2 if case['stress'] else 4
    elif kind==7:frames=5
    elif kind==8:frames=4+int(case['kalman'][0]!=0 or case['kalman'][2]!=0)
    elif kind in (11,12,15):frames=case['transactions']+1
    elif kind==13:frames=case['transactions']+1+(4+len(PHASES_DEG)*len(CFOS) if case['profile']=='model' else 0)
    elif kind==14:frames=case['transactions']+1+int(case['profile']=='model')
    elif kind==17:frames=case['transactions']+1+int(case['stress'])
    elif kind==18:frames=case['transactions']+1+int(case['stress'])
    elif kind==20:frames=case['transactions']+1+2*int(case['stress'])
    elif kind==21:frames=(STRESS_WEIGHT_TRANSACTIONS if case['stress']=='weight34' else STRESS_P_TRANSACTIONS if case['stress']=='p44' else case['transactions']+1)
    else:frames=case['transactions']
    return dict(input_fields=inputs,output_fields=outputs,config_fields=cfg,weight_fields=pair_fields(18) if kind in (20,21) else [],weight_port=kind in (20,21),
                cfgreset_supported=bool(cfg) and kind not in (7,8,13,14,17,20,21),cfg_last_port=bool(cfg) and kind not in (7,8,13,14,17,20,21),error_port=kind not in (7,13),sideband_port=kind in (13,14,18),expected_frames=frames)


def pack_fields(values,fields):
    if len(values)!=len(fields):raise ValueError('Physical field count')
    word=0;offset=0
    for value,(_,bits,signed) in zip(values,fields):
        low=-(1<<(bits-1)) if signed else 0;high=1<<(bits-int(signed))
        if type(value) is not int or not low<=value<high:raise ValueError('Physical field width/signedness')
        word|=(value&((1<<bits)-1))<<offset;offset+=bits
    if offset>512:raise ValueError('Packed UVM bus width')
    return word


def unpack_fields(word,fields):
    total=sum(bits for _,bits,_ in fields)
    if type(word) is not int or word<0 or word>>total:raise ValueError('Unexpected packed padding/width')
    result=[]
    for _,bits,signed in fields:
        value=word&((1<<bits)-1);word>>=bits
        if signed and value&(1<<(bits-1)):value-=1<<bits
        result.append(value)
    return tuple(result)


def rows(path,width,header=True):
    lines=Path(path).read_text().splitlines()
    if header:
        if not lines or len(lines)-1!=int(lines[0]):raise ValueError('Native row count')
        lines=lines[1:]
    result=[list(map(int,line.split())) for line in lines]
    if any(len(row)!=width for row in result):raise ValueError('Native column width')
    return result


def pack_pair(re,im,width):
    if type(re) is not int or type(im) is not int or not -(1<<(width-1))<=re<1<<(width-1) or not -(1<<(width-1))<=im<1<<(width-1):
        raise ValueError('Physical signed component width')
    mask=(1<<width)-1
    return (re&mask)|((im&mask)<<width)


def unpack_pair(word,width):
    if type(word) is not int or word<0 or word>>2*width:raise ValueError('Unexpected packed padding/width')
    mask=(1<<width)-1
    def signed(value):return value-(1<<width) if value&(1<<(width-1)) else value
    return signed(word&mask),signed((word>>width)&mask)


def split_frames(values):
    frames=[];current=[]
    for row in values:
        if row[-1] not in (0,1):raise ValueError('Native TLAST')
        current.append(row)
        if row[-1]:frames.append(current);current=[]
    if current or not frames:raise ValueError('Incomplete native transaction')
    return frames


def native_vectors(native,case):
    family=case['family'];kind=case['kind'];cfg=[]
    if family=='ofdm':
        report=ofdm_vectors(native,case['log2n'],case['cp'],frames=case['frames'],seed=case['seed'])
        a,b=case['direction']+'_in.txt',case['direction']+'_out.txt'
    elif family=='stft':
        report=stft_vectors(native,case['log2n'],case['log2hop'],transactions=case['transactions'],seed=case['seed'],stress=True)
        prefix='an' if kind==4 else 'sy';a,b=prefix+'_in.txt',prefix+'_out.txt'
    elif family=='fir':
        report=fir_vectors(native,case['taps'],transactions=case['transactions'],seed=case['seed'])
        a,b='in.txt','out.txt';cfg=rows(native/'cfg.txt',2)
    elif family=='pfb':
        report=pfb_vectors(native,case['log2m'],case['d'],case['taps'],transactions=case['transactions'],seed=case['seed'],stress=case['stress'])
        a,b='in.txt','out.txt';values=list(map(int,(native/'cfg.txt').read_text().split()))
        if len(values)!=values[0]+2 or values[-1]!=case['d']:raise ValueError('Native PFB configuration')
        cfg=[[tap,values[-1]] for tap in values[1:-1]]
    elif family=='oset':
        report=oset_vectors(native,notch=case['notch'],kalman=case['kalman'],transactions=case['transactions'],seed=case['seed'],
                            notch_raw=case['raw'],label='stress' if case['raw'] is not None else 'designed')
        a,b=case['direction']+'_in.txt',case['direction']+'_out.txt'
        cfg=[list(map(int,(native/(case['direction']+'_cfg.txt')).read_text().split()))]
    elif family=='fsk':
        report=fsk_vectors(native,**{k:case[k] for k in ('n','f0','df','order','symbols','transactions','seed')})
        a,b=case['direction']+'_in.txt',case['direction']+'_out.txt'
        values=list(map(int,(native/'cfg.txt').read_text().split()))
        if len(values)!=values[0]+2 or values[-1]!=case['n'] or values[0]!=case['order']:raise ValueError('Native FSK configuration')
        cfg=[[step,values[-1]] for step in values[1:-1]]
    elif family=='beam':
        report=beam_vectors(native,case['m'],case['weights'],transactions=case['transactions'],seed=case['seed'])
        prefix='bf' if kind==11 else 'al';a,b=prefix+'_in.txt',prefix+'_out.txt'
        cfg=rows(native/(prefix+'_cfg.txt'),2)
    elif family=='mmse':
        report=(mmse2_vectors(native,case['matrix'],transactions=case['transactions'],seed=case['seed']) if kind==15 else
                mmse3_vectors(native,case['matrix'],seed=case['seed']))
        a,b='in.txt','out.txt';lines=(native/'cfg.txt').read_text().splitlines()
        if len(lines)!=case['dimension']**2+1:raise ValueError('Native MMSE configuration')
        cfg=[[*map(int,line.split()),int(lines[-1])] for line in lines[:-1]]
    elif family=='sync':
        report=sync_vectors(native,case['costas'],case['timing'],transactions=case['transactions'],seed=case['seed'])
        prefix='cl' if kind==13 else 'gt';a,b=prefix+'_in.txt',prefix+'_out.txt'
        cfg=[list(map(int,(native/(prefix+'_cfg.txt')).read_text().split()))]
    elif family=='omlsa':
        report=omlsa_vectors(native,1<<case['log2n'],1<<case['log2hop'],case['nnoise'],case['alpha'],
                            transactions=case['transactions'],complex_input=case['complex_input'],seed=case['seed'],stress=case['stress'])
        a,b='in.txt','out.txt';cfg=[list(map(int,(native/'cfg.txt').read_text().split()))]
    elif family=='coding':
        report=ldpc_vectors(native,case['mode'],transactions=case['transactions'],seed=case['seed'],code=case['code'],stress=case['stress'])
        prefix='dec' if kind==18 else 'enc';a,b=prefix+'_in.txt',prefix+'_out.txt'
        lines=(native/(prefix+'_cfg.txt')).read_text().splitlines();header=list(map(int,lines[0].split()))
        expected=[case['m'],case['n'],case['iterations'],case['mode']] if kind==18 else [case['m'],case['k']]
        if header[:len(expected)]!=expected or len(lines)-1!=header[0]*header[1]:raise ValueError('Native coding matrix geometry')
        cfg=[[int(line),*header] for line in lines[1:]]
    elif family in ('lms','rls'):
        if kind==20:report=lms_vectors(native,case['mode'],case['step'],case['eps'],case['taps'],transactions=case['transactions'],seed=case['seed'],stress=case['stress'])
        else:report=rls_vectors(native,case['lam'],case['eps'],case['taps'],transactions=case['transactions'],noise=case['noise'],seed=case['seed'],stress=case['stress'])
        a,b='in.txt','out.txt';cfg=[list(map(int,(native/'cfg.txt').read_text().split()))]
    else:raise ValueError('Unknown DSP family')
    return report,a,b,cfg


def check_geometry(case,config,inputs,outputs):
    n=1<<case.get('log2n',0);hop=1<<case.get('log2hop',0);kind=case['kind']
    for a,b in zip(inputs,outputs):
        ni,no=len(a),len(b)
        if case['family']=='ofdm':
            expected_lengths=(n,n+case['cp']) if kind==2 else (n+case['cp'],n)
            if (ni,no)!=expected_lengths:raise ValueError('Independent OFDM prefix geometry')
        elif case['family']=='stft':
            if kind==4:
                if no!=n*(1+(ni-n)//hop):raise ValueError('Independent STFT frame geometry')
            elif ni%n or no!=(ni//n-1)*hop+n:raise ValueError('Independent ISTFT overlap geometry')
        elif kind==1 and no!=ni+len(config)-1:raise ValueError('Independent FIR convolution geometry')
        elif kind==6 and no!=(1<<case['log2m'])*((ni+case['d']-1)//case['d']):raise ValueError('Independent PFB bin geometry')
        elif kind in (7,8) and no!=ni:raise ValueError('Independent causal filter geometry')
        elif kind==9 and no!=ni*case['n']:raise ValueError('Independent FSK TX geometry')
        elif kind==10 and ni!=no*case['n']:raise ValueError('Independent FSK RX geometry')
        elif kind in (20,21) and no!=ni:raise ValueError('Independent adaptive prediction/error geometry')
        elif kind==18 and (ni!=case['n'] or no!=ni):raise ValueError('Independent LDPC codeword geometry')
        elif kind==19 and (ni,no)!=(case['k'],case['m']+case['k']):raise ValueError('Independent GF2 parity/message geometry')
        elif kind==17 and (no!=ni or ni<n+1):raise ValueError('Independent OM-LSA trim geometry')
        elif kind==13 and no!=ni:raise ValueError('Independent Costas sample/phase geometry')
        elif kind==14 and no!=case['timing'][1]:raise ValueError('Independent Gardner configured count')
        elif kind==11 and ni!=no*case['m']:raise ValueError('Independent beam snapshot geometry')
        elif kind==12 and (ni%2 or no!=ni):raise ValueError('Independent Alamouti pair geometry')
        elif kind in (15,16) and (ni%case['dimension'] or no!=ni):raise ValueError('Independent MMSE vector geometry')


def prepare(folder,name):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    case=CASES[name];schema=contract(case);native=folder/'native'
    report,a,b,cfg=native_vectors(native,case)
    header=case['family']!='mmse'
    source=rows(native/a,len(schema['input_fields'])+1,header=header);expected=rows(native/b,len(schema['output_fields'])+1,header=header)
    inputs,outputs=split_frames(source),split_frames(expected)
    if len(inputs)!=len(outputs) or len(inputs)!=schema['expected_frames']:raise ValueError('Native transaction count differs')
    check_geometry(case,cfg,inputs,outputs)
    weights=split_frames(rows(native/'w.txt',3)) if schema['weight_port'] else [[] for _ in inputs]
    if len(weights)!=len(inputs) or any(len(w)!=case['taps'] for w in weights if schema['weight_port']):raise ValueError('Independent final tap-dump geometry')
    config=[(pack_fields(row,schema['config_fields']),int(k==len(cfg)-1 and schema['cfg_last_port'])) for k,row in enumerate(cfg)]
    transactions=[]
    for arows,brows,wrows in zip(inputs,outputs,weights):
        transactions.append(dict(source=[(pack_fields(row[:-1],schema['input_fields']),row[-1],2 if k%5==1 else 0) for k,row in enumerate(arows)],
                                 expected=[(pack_fields(row[:-1],schema['output_fields']),row[-1]) for row in brows],
                                 weights=[(pack_fields(row[:-1],schema['weight_fields']),row[-1]) for row in wrows]))
    lines=[f'{len(config)} {len(transactions)}']+[f'{word:0128x} {last}' for word,last in config]
    for item in transactions:
        lines.append(f'{len(item["source"])} {len(item["expected"])} {len(item["weights"])}')
        lines.extend(f'{word:0128x} {last} {gap}' for word,last,gap in item['source'])
        lines.extend(f'{word:0128x} {last}' for word,last in item['expected'])
        lines.extend(f'{word:0128x} {last}' for word,last in item['weights'])
    (folder/'plan.txt').write_text('\n'.join(lines)+'\n')
    model=dict(case=case,name=name,frames=len(transactions),config_rows=len(config),inputs=len(source),outputs=len(expected),
        lengths=[(len(a),len(b)) for a,b in zip(inputs,outputs)],warm_inputs=len(inputs[0]),warm_outputs=len(outputs[0]),
        packed_input_bits=sum(bits for _,bits,_ in schema['input_fields']),packed_output_bits=sum(bits for _,bits,_ in schema['output_fields']),
        weight_rows=sum(map(len,weights)),weight_lengths=list(map(len,weights)),warm_weights=len(weights[0]),packed_weight_bits=sum(bits for _,bits,_ in schema['weight_fields']),
        native_report=report,native_header=header,native_input=a,native_output=b,native_config=cfg,**schema,
        configuration=('NOT_APPLICABLE: no configuration ports' if not cfg else
                       'cfg_last-terminated stream; partial reset applicable' if schema['cfgreset_supported'] else 'atomic single-transfer configuration; partial reset NOT_APPLICABLE'))
    (folder/'model.json').write_text(json.dumps(model,indent=2)+'\n')
    return model
