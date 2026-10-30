#!/usr/bin/env python3
"""Full fixed CPM TX/channel/RX; conditioned arithmetic SQNR and independent final SER.

Floating coherent RX has its own floating acquisition and native Laurent loop.
Its state never comes from the integer receiver. Conditioned node comparisons
reuse integer timing/phase/upstream samples explicitly, and are separate evidence.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import cpm_fixed as fixed
import modem_core as real
import gmsk_coherent as coherent
import psk_fixed
from regression_evidence import begin,finish,require_unoptimized,write_json

COUNT,PREAMBLE,LABEL_SEED=512,192,19
CHANNELS={'clean':{},'nominal':dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
          'low_snr':dict(snr_db=-8)}
PROFILES=('msk_frequency','gmsk_frequency','gmsk_coherent')
NODE_LIMITS={'tx_msk':90,'tx_gmsk':55,'interpolation':55,'differential_phase':90,
             'c0_filter':75,'rotation_axis':55,'error_angle':60}


def samples(rows):
    a=np.asarray(rows)
    if a.ndim!=2 or a.shape[1]!=2 or not len(a) or not np.all(np.isfinite(a)):
        raise ValueError('Samples must be finite nonempty Nx2 pairs')
    return (a[:,0]+1j*a[:,1])/32768


def metric(actual,expected,*,angular=False):
    a=np.asarray(actual);e=np.asarray(expected)
    if a.ndim!=1 or a.shape!=e.shape or not a.size or not np.all(np.isfinite(a)) or not np.all(np.isfinite(e)):
        raise ValueError('Precision arrays must be finite nonempty equal vectors')
    error=a-e
    if angular:error=(error+np.pi)%(2*np.pi)-np.pi
    power=float(np.mean(abs(e)**2));mse=float(np.mean(abs(error)**2))
    if power<=0 or not np.isfinite(power+mse):raise ValueError('Invalid SQNR power')
    return dict(samples=len(a),signal_power=power,error_power=mse,
                sqnr_db=None if mse==0 else float(10*np.log10(power/mse)),exact_match=mse==0,
                max_abs_error=float(np.max(abs(error))),angular_error=angular)


def payload_score(decoded,truth):
    a=np.asarray(decoded);t=np.asarray(truth)
    if a.ndim!=1 or a.shape!=t.shape or len(t)<=PREAMBLE or not np.issubdtype(a.dtype,np.integer) or not np.issubdtype(t.dtype,np.integer):
        raise ValueError('Decoded and true bits must have equal integer vector shape')
    if np.any((a<0)|(a>1)) or np.any((t<0)|(t>1)):raise ValueError('Binary labels required')
    errors=int(np.count_nonzero(a[PREAMBLE:]!=t[PREAMBLE:]));count=len(t)-PREAMBLE
    return dict(payload_symbols=count,errors=errors,ser=errors/count)


def floating_acquire(cfg,wave,preamble):
    """Floating discriminator peak and block-phase LS; no integer acquisition API."""
    bits=np.asarray(preamble,int)
    if bits.shape!=(PREAMBLE,) or np.any((bits<0)|(bits>1)):raise ValueError('192 preamble bits required')
    corr_count,lags,blocks=1024,18,8
    reference=real.transmit(cfg,bits)['waveform']
    frequency=np.repeat(2*bits-1,8)
    if cfg['family']=='gmsk':frequency=np.convolve(frequency,real.gaussian_taps(8,cfg['gaussian_bt']))
    increments=np.r_[0.,np.angle(wave[1:]*np.conj(wave[:-1]))]
    weight=frequency[1:corr_count+1] if cfg['family']=='gmsk' else np.where(frequency[1:corr_count+1]>=0,1.,-1.)
    correlation=np.array([np.dot(increments[j:j+corr_count],weight) for j in range(lags)])
    j=int(np.argmax(correlation));fraction=0.
    if 0<j<lags-1:
        denominator=(2*(2*correlation[j]-correlation[j-1]-correlation[j+1]) if cfg['family']=='gmsk'
                     else 2*(correlation[j]-min(correlation[j-1],correlation[j+1])))
        if denominator>0:fraction=float(np.clip((correlation[j+1]-correlation[j-1])/denominator,-.5,.5))
    delay=max(0.,j-1+fraction);n=np.arange(corr_count);size=corr_count//blocks
    terms=real.cubic(wave,n+delay)*np.conj(reference[:corr_count])
    phases=np.unwrap(np.angle(terms.reshape(blocks,size).sum(axis=1)))
    centres=size*np.arange(blocks)+(size-1)/2;centred=centres-centres.mean()
    slope=float(np.dot(centred,phases-phases.mean())/np.dot(centred,centred))
    phase=float(phases.mean()-slope*centres.mean())
    # The fixed contract's half-sample correction is a constant sampling convention.
    corrected_delay=delay-.5;used=(PREAMBLE-4)*8;n=np.arange(used)
    aligned=real.cubic(wave,n+corrected_delay)*np.exp(-1j*(slope*n+phase))
    amplitude=float(abs(np.vdot(reference[:used],aligned))/np.vdot(reference[:used],reference[:used]).real)
    if amplitude<=0 or not np.isfinite(amplitude+slope+phase):raise ValueError('Floating acquisition failed')
    return corrected_delay,slope,amplitude*np.exp(1j*phase)


def floating_coherent(cfg,wave,preamble,count):
    """Native floating Laurent filter and undelayed floating decision loop."""
    delay,slope,gain=floating_acquire(cfg,wave,preamble)
    z=coherent.matched(cfg,wave,count,delay,slope,gain)
    known=np.cumprod(2*np.asarray(preamble)-1);phase=frequency=0.;previous=1;data=[]
    for k in range(count):
        rotated=z[k]*coherent.axis(k)*np.exp(-1j*phase)
        beta=1 if rotated.real>=0 else -1
        target=known[k] if k<PREAMBLE-4 else beta
        error=float(np.clip(np.angle(rotated*target),-.5,.5))
        frequency+=.0002*error;phase+=frequency+.04*error
        data.append(int(beta*previous>0));previous=beta
    return dict(data=np.asarray(data,int),delay=delay,frequency=slope/(2*np.pi))


def node_metrics(profile,rows,result,tx,tx_reference,preamble):
    wave=samples(rows);acquisition=result['acquisition'];gmsk=profile!='msk_frequency'
    metrics={'tx_gmsk' if gmsk else 'tx_msk':metric(tx,tx_reference)}
    if profile!='gmsk_coherent':
        nodes=result['nodes'];x=samples([node[0] for node in nodes])
        positions=np.arange(len(x))+acquisition['delay']/65536+.5
        expected=real.cubic(wave,positions)
        phase=np.angle(x[1:]*np.conj(x[:-1]))-acquisition['frequency']*2*np.pi/2**32
        ideal=np.r_[0.,np.angle(np.exp(1j*phase))]
        actual=np.array([node[1] for node in nodes])*2*np.pi/2**32
        metrics.update(interpolation=metric(x,expected),differential_phase=metric(actual,ideal,angular=True))
    else:
        # Coherent trace exposes z/theta/r/error, so interpolation is replayed at
        # its actual acquisition delay using the same integer interpolation API.
        positions_q16=(np.arange(COUNT*8+len(fixed.C0_TAPS),dtype=np.int64)<<16)+acquisition['delay']+fixed.COHERENT_OFFSET
        interpolated=samples([fixed.interp(rows,int(position)) for position in positions_q16])
        ideal=np.array([np.dot(interpolated[k*8:k*8+len(coherent.C0)],coherent.C0)/32 for k in range(COUNT)])
        nodes=result['nodes'];z=samples([node['z'] for node in nodes]);rotated=samples([node['r'] for node in nodes])
        theta=np.array([node['theta'] for node in nodes])*2*np.pi/2**32
        rotation=z*np.exp(-1j*theta)*np.array([coherent.axis(k) for k in range(COUNT)])
        known=np.cumprod(2*np.asarray(preamble)-1)
        targets=np.where(np.arange(COUNT)<PREAMBLE-4,np.r_[known,np.ones(COUNT-PREAMBLE)],np.where(rotated.real>=0,1,-1))
        error=np.angle(rotated*targets);actual=np.array([node['error'] for node in nodes])*2*np.pi/2**32
        metrics.update(interpolation=metric(interpolated,real.cubic(wave,positions_q16/65536)),
                       c0_filter=metric(z,ideal),rotation_axis=metric(rotated,rotation),error_angle=metric(actual,error,angular=True))
    return metrics


def report():
    records=[]
    for profile in PROFILES:
        gmsk=profile!='msk_frequency'
        name='gmsk_coherent_demodulation_2010_10_03' if gmsk else 'msk_modulator_2008_06_22'
        cfg=real.load_config(ROOT/'modems'/name/'config.json')
        bits=np.random.default_rng(LABEL_SEED).integers(0,2,COUNT);preamble=bits[:PREAMBLE].copy()
        tx=samples(fixed.transmit(bits,gmsk));tx_reference=real.transmit(cfg,bits)['waveform']
        for case,parameters in CHANNELS.items():
            seed=101 if case=='low_snr' else 7
            channel=real.channel(cfg,tx,seed=seed,**parameters)
            raw=np.rint(np.c_[channel.real,channel.imag]*32768)
            clips=int(np.count_nonzero((raw<-131072)|(raw>131071)))
            rows=psk_fixed.quantize(channel);wave=samples(rows)
            record=dict(profile=profile,config=name,case=case,channel_parameters=dict(parameters,seed=seed),
                        input_sha256=hashlib.sha256(np.asarray(rows,dtype='<i8').tobytes()).hexdigest(),
                        input_rail_excursions=clips,nodes={},fixed={'status':'not_run'},floating={'status':'not_run'})
            try:
                result=(fixed.receive_coherent(rows,preamble,COUNT,observe=True) if profile=='gmsk_coherent'
                        else fixed.receive(rows,preamble,COUNT,gmsk,observe=True))
                record['fixed']=dict(status='decoded',**payload_score(result['data'],bits))
                record['nodes']=node_metrics(profile,rows,result,tx,tx_reference,preamble)
            except (ValueError,RuntimeError) as exc:record['fixed']=dict(status='failed',error=str(exc))
            try:
                result=(floating_coherent(cfg,wave,preamble,COUNT) if profile=='gmsk_coherent'
                        else real.receive_cpm(cfg,wave,preamble,COUNT))
                record['floating']=dict(status='decoded',**payload_score(result['data'],bits))
            except (ValueError,RuntimeError) as exc:record['floating']=dict(status='failed',error=str(exc))
            records.append(record)
    return dict(records=records,checks=check_records(records))


def check_records(records):
    keys=[(r['profile'],r['case']) for r in records];required={(p,c) for p in PROFILES for c in CHANNELS}
    checks={'complete_cases':len(keys)==len(required) and set(keys)==required}
    for record in records:
        prefix=record['profile']+'/'+record['case']
        for mode in ('fixed','floating'):
            r=record[mode];decoded=r['status']=='decoded'
            checks[prefix+'/'+mode+'_decoded']=decoded
            checks[prefix+'/'+mode+'_ser']=decoded and (r['errors']>20 if record['case']=='low_snr' else r['errors']==0)
        if record['case']!='low_snr':
            checks[prefix+'/input_no_clips']=record['input_rail_excursions']==0
            required_nodes={'tx_msk' if record['profile']=='msk_frequency' else 'tx_gmsk','interpolation'}
            required_nodes|=({'c0_filter','rotation_axis','error_angle'} if record['profile']=='gmsk_coherent' else {'differential_phase'})
            checks[prefix+'/nodes_complete']=set(record['nodes'])==required_nodes
            for name,node in record['nodes'].items():
                checks[prefix+'/'+name+'_sqnr']=bool(node['exact_match'] or node['sqnr_db']>NODE_LIMITS[name])
    return checks


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/cpm_precision/results.json')
    args=parser.parse_args(argv);evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'))
    try:
        require_unoptimized();data=report();status='PASS' if all(data['checks'].values()) else 'FAIL'
        result=dict(finish(evidence),status=status,**data,
                    parameters=dict(count=COUNT,preamble=PREAMBLE,label_seed=LABEL_SEED,channels=CHANNELS,node_limits_db=NODE_LIMITS),
                    rtl_verified=False,
                    tx_convention='Phase accumulator starts at zero and advances before the first sample, matching modem_core.transmit; no phase fit.',
                    channel_scope='Fixed TX -> modem_core channel -> one Q3.15 quantization; both receivers see identical dequantized samples. SNR is sample-average channel power before quantization.',
                    node_scope='Conditioned arithmetic only: fixed timing/upstream/phase; coherent interpolation is replayed at fixed acquisition timing, C0 ideal taps scale 1/32, rotation includes axis, angle is before clipping. No independent loop claim from these nodes.',
                    ser_scope='Independent full floating frequency grid acquisition or floating coherent discriminator/block-LS acquisition and native undelayed Laurent loop. Fixed coherent updates are delayed10symbols. Only192preamble bits passed to RX; payload truth only scores original labels.')
        write_json(args.output,result)
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    if status!='PASS':raise RuntimeError('CPM precision failed: '+', '.join(key for key,ok in data['checks'].items() if not ok))
    print('PASS CPM precision: 3 profiles x 3 channels');return result


if __name__=='__main__':main()
