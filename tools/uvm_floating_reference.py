"""Independent float receiver on the exact quantized UVM pin waveform.

Decisions come only from the raw Q15 pin rows, the public training labels and,
for SIMO, the Q15 gain tuple with its relative variances. Payload truth is read
after decoding, only for scoring; no fixed-point receiver or combiner is used.
"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'common/python'))
from bpsk_cases import CONFIGS as PSK_CONFIGS
from types import SimpleNamespace
import modem_core as real
import psk_fixed as profiles

TRAINING=192
FILES=('float_decisions.txt','float_expected.txt','float_reference.json')
PACKET_CONFIGS=dict(oqpsk='modems/oqpsk_2_sps_timing_recovery_2019_12_05/config.json',
                    msk='modems/msk_modulator_2008_06_22/config.json',
                    gmsk='modems/gmsk_coherent_demodulation_2010_10_03/config.json')
CONFIGS={**PSK_CONFIGS,**PACKET_CONFIGS}


def rows(path,width):
    lines=Path(path).read_text().splitlines()
    if not lines or len(lines)-1!=int(lines[0]):raise ValueError('Reference header/count')
    values=np.array([list(map(int,line.split())) for line in lines[1:]],dtype=np.int64)
    if values.ndim!=2 or values.shape[1]!=width:raise ValueError('Reference column geometry')
    return values


def _profile(name):
    if name in PACKET_CONFIGS:return SimpleNamespace(alphabet=4 if name=='oqpsk' else 2)
    return next(p for p in profiles.PROFILES if p.name==name)


def _frames(folder,profile_name):
    """Input geometry: raw pin rows split by input TLAST, symbol count from trace rows."""
    cfg=real.load_config(ROOT/CONFIGS[profile_name]);simo=cfg['diversity_branches']==2
    raw=rows(folder/'rx_wave.txt',5 if simo else 3)
    if not np.all((raw[:,:-1]>=-131072)&(raw[:,:-1]<=131071)) or not np.isin(raw[:,-1],[0,1]).all():raise ValueError('Waveform ports')
    starts=[0]+(np.flatnonzero(raw[:,-1])+1).tolist()
    ntrace=int((folder/'rx_trace.txt').read_text().split('\n',1)[0])
    if starts[-1]!=len(raw) or len(starts)<2 or ntrace%(len(starts)-1):raise ValueError('Frame geometry')
    count=ntrace//(len(starts)-1)
    if not TRAINING<=count<=4095:raise ValueError('Frame symbol count')
    return cfg,simo,raw,list(zip(starts,starts[1:])),count


def floating_decisions(folder,profile_name):
    """Per-frame float decisions; reads no truth column."""
    folder=Path(folder);profile=_profile(profile_name);cfg,simo,raw,spans,count=_frames(folder,profile_name)
    training=rows(folder/'preamble.txt',1)[:,0]
    if len(training)!=TRAINING or not np.all((training>=0)&(training<profile.alphabet)):raise ValueError('Training labels')
    if simo:
        gains=rows(folder/'gains.txt',6)
        if len(gains)!=1 or not np.all((gains[0,4:]>=1)&(gains[0,4:]<=65535)):raise ValueError('MRC gain configuration')
        if not np.all((gains[0,:4]>=-131072)&(gains[0,:4]<=131071)):raise ValueError('Q15 gains')
        gain=[complex(*gains[0,i:i+2])/32768 for i in (0,2)]
    result=[]
    for a,b in spans:
        wave=(raw[a:b,0]+1j*raw[a:b,1])/32768
        if simo:wave=real.maximal_ratio_combine([wave,(raw[a:b,2]+1j*raw[a:b,3])/32768],gain,gains[0,4:])
        if profile_name=='gmsk':
            # The public portable GMSK modem uses a discriminator. Its coherent
            # RTL is compared with an independent floating Laurent receiver.
            from cpm_precision import floating_coherent
            decoded=np.asarray(floating_coherent(cfg,wave,training,count)['data'])
        else:decoded=np.asarray(real.receive(cfg,wave,training,count)['data'])
        if decoded.shape!=(count,) or decoded.dtype.kind not in 'iu' or not np.all((decoded>=0)&(decoded<profile.alphabet)):raise ValueError('Floating decision geometry')
        result.append(decoded.astype(np.int64))
    return np.array(result)


def original_truth(folder,profile_name,frames):
    trace=rows(Path(folder)/'rx_trace.txt',10);truth=trace[:,9].reshape(frames,-1)
    training=rows(Path(folder)/'preamble.txt',1)[:,0]
    if not np.all((truth>=0)&(truth<_profile(profile_name).alphabet)) or not np.all(truth[:,:TRAINING]==training):raise ValueError('Scoring labels')
    return truth


def score(decisions,truth):
    if decisions.shape!=truth.shape:raise ValueError('Decision/truth geometry')
    errors=decisions[:,TRAINING:]!=truth[:,TRAINING:];symbols=decisions.shape[1]-TRAINING
    return [dict(frame=f,symbols=symbols,errors=int(np.count_nonzero(e)),ser=float(np.mean(e)) if symbols else None,defined=symbols>0) for f,e in enumerate(errors)]


def floating_payload_scores(folder,profile_name):
    decisions=floating_decisions(folder,profile_name)
    result=score(decisions,original_truth(folder,profile_name,len(decisions)))
    for item,row in zip(result,decisions):item['decisions']=row.tolist()
    return result


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _inputs(folder,profile_name):
    simo=real.load_config(ROOT/CONFIGS[profile_name])['diversity_branches']==2
    names=['preamble.txt','rx_wave.txt']+(['gains.txt'] if simo else [])
    return {name:_sha(Path(folder)/name) for name in names}


def _truth_digest(truth):return hashlib.sha256(' '.join(map(str,truth.ravel().tolist())).encode()).hexdigest()


def write_float_reference(folder,profile_name):
    """Immutable float decisions, original truth digest, error counts and denominators.

    Must run on the original vectors before any negative mutation is copied."""
    folder=Path(folder);decisions=floating_decisions(folder,profile_name)
    truth=original_truth(folder,profile_name,len(decisions));scores=score(decisions,truth)
    (folder/'float_decisions.txt').write_text(f'{decisions.size}\n'+''.join(f'{v}\n' for v in decisions.ravel()))
    (folder/'float_expected.txt').write_text(f'{len(scores)}\n'+''.join(f"{s['errors']} {s['symbols']}\n" for s in scores))
    meta=dict(profile=profile_name,config=CONFIGS[profile_name],frames=len(scores),symbols_per_frame=int(decisions.shape[1]),
              training=TRAINING,inputs=_inputs(folder,profile_name),original_truth_sha256=_truth_digest(truth),
              float_decisions_sha256=_sha(folder/'float_decisions.txt'),float_expected_sha256=_sha(folder/'float_expected.txt'),
              float_payload_errors=[s['errors'] for s in scores],float_payload_symbols=[s['symbols'] for s in scores],
              method=('cpm_precision.floating_coherent: independent float acquisition and Laurent C0 receive loop on raw Q15 pin rows/32768; truth only for scoring' if profile_name=='gmsk' else
                      'modem_core.receive (float) on raw Q15 pin rows/32768; SIMO via modem_core.maximal_ratio_combine with Q15 gains and relative variances; truth only for scoring'))
    (folder/'float_reference.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta


def validate_float_reference(folder,profile_name):
    """Independent rerun: provenance, decisions, counts and denominators must match exactly."""
    folder=Path(folder);meta=json.loads((folder/'float_reference.json').read_text())
    if meta.get('profile')!=profile_name or meta.get('training')!=TRAINING:raise ValueError('Float reference profile')
    if meta.get('inputs')!=_inputs(folder,profile_name):raise ValueError('Float reference input provenance')
    if _sha(folder/'float_decisions.txt')!=meta.get('float_decisions_sha256') or _sha(folder/'float_expected.txt')!=meta.get('float_expected_sha256'):
        raise ValueError('Float reference file digest')
    decisions=floating_decisions(folder,profile_name)
    stored=rows(folder/'float_decisions.txt',1)[:,0]
    if stored.shape!=(decisions.size,) or not np.array_equal(stored,decisions.ravel()):raise ValueError('Float decisions differ from independent rerun')
    truth=original_truth(folder,profile_name,len(decisions))
    if _truth_digest(truth)!=meta.get('original_truth_sha256'):raise ValueError('Scoring truth differs from original')
    scores=score(decisions,truth);expected=rows(folder/'float_expected.txt',2)
    if expected.tolist()!=[[s['errors'],s['symbols']] for s in scores]:raise ValueError('Float error counts/denominators differ')
    if meta.get('float_payload_errors')!=[s['errors'] for s in scores] or meta.get('float_payload_symbols')!=[s['symbols'] for s in scores]:
        raise ValueError('Float metadata counts differ')
    return meta


def mutate_float_metadata(source,target,kind,*,alphabet):
    """Negative controls: one immutable float field changed, all other inputs byte-identical."""
    import shutil
    shutil.copytree(source,target,dirs_exist_ok=True)
    if kind=='decision':
        lines=(target/'float_decisions.txt').read_text().splitlines();index=1+200
        lines[index]=str((int(lines[index])+1)%alphabet);(target/'float_decisions.txt').write_text('\n'.join(lines)+'\n')
        changed='float_decisions.txt'
    elif kind in ('errorcount','denominator'):
        lines=(target/'float_expected.txt').read_text().splitlines();errors,symbols=map(int,lines[1].split())
        lines[1]=f'{errors+1} {symbols}' if kind=='errorcount' else f'{errors} {symbols-1}'
        (target/'float_expected.txt').write_text('\n'.join(lines)+'\n');changed='float_expected.txt'
    else:raise ValueError('Unknown float metadata mutation')
    for file in Path(source).iterdir():
        if file.is_file() and (_sha(file)==_sha(target/file.name))==(file.name==changed):raise RuntimeError('Float negative must change exactly one metadata file')
    return changed
