#!/usr/bin/env python3
"""Exact ISTFT product and overlap-add widths, before saturation and scaling."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import istft_widths as widths
import stft_fixed as fixed
import fft_fixed as fft
from sat_diag import SatTrace,write_expected,save_json
from stft_cases import vectors,save
from run_stft import CASES as NATIVE_CASES,files
from spectral_evidence import check_observers
CASES=tuple((f'native_n{1<<n}_h{1<<h}',n,h,t,False) for n,h,t in NATIVE_CASES)+(
    ('signed_window_r1',2,2,2,True),('signed_window_r2',3,2,2,True),('signed_window_r4',4,2,2,True))
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
           'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']}


def read_rows(path):return [tuple(map(int,line.split())) for line in path.read_text().splitlines()[1:]]


def impulses(n,hop):
    ratio=n//hop;c=fixed.SPECTRUM_LIMIT;roots=((1,0),(0,1),(-1,0),(0,-1));rows=[]
    for sign in (1,-1):
        frames=3*ratio+1
        for frame in range(frames):
            target=(ratio-1-frame%ratio)*hop
            for k in range(n):
                re_,im=roots[((-k*target)%n)*4//n]
                rows.append((sign*c*(re_-im),sign*c*(re_+im),int(frame==frames-1 and k==n-1)))
    return rows


def raw_reference(rows,n,hop,window):
    writes=[];reads=[];outputs=[];transaction=[];stats=SatTrace();max_overlap=0
    for re_,im,last in rows:
        transaction.append((re_,im))
        if not last:continue
        if len(transaction)%n:raise RuntimeError('Incomplete spectrum frame')
        frames=len(transaction)//n;size=(frames-1)*hop+n
        acc=[[0,0] for _ in range(size)];counts=[0]*size
        for frame in range(frames):
            spectra=[tuple(stats.record('stft.spectrum.'+axis,v,fixed.SPECTRUM_LIMIT,'sym') for axis,v in zip(('re','im'),pair))
                     for pair in transaction[frame*n:(frame+1)*n]]
            u=fft.inverse(spectra,23,24)
            for k,(xr,xi) in enumerate(u):
                if max(abs(xr),abs(xi))>(1<<23)-1:raise RuntimeError('FFT symmetric rail violated')
                t=frame*hop+k;old=acc[t][:];product_=[xr*window[k],xi*window[k]]
                acc[t]=[old[a]+product_[a] for a in (0,1)];counts[t]+=1;max_overlap=max(max_overlap,counts[t])
                writes.append((t%n,*old,*product_,*acc[t],counts[t]))
        table=fixed.reciprocals(n,hop);shift=17+4+fixed.recip_frac(n,hop)
        for t,pair in enumerate(acc):
            reads.append(tuple(pair));mask=sum(1<<m for m in range(n//hop) if 0<=t//hop-m<frames)
            value=[stats.record('stft.output.'+axis,fft.rnd(v*table[t%hop][mask],shift),fixed.LIMIT,'asym') for axis,v in zip(('re','im'),pair)]
            outputs.append((*value,int(t==size-1)))
        transaction=[]
    if transaction:raise RuntimeError('Missing TLAST')
    return writes,reads,outputs,stats,max_overlap


def fixture(spec,folder):
    name,n_,h_,transactions,custom=spec;n=1<<n_;hop=1<<h_
    vectors(folder,n_,h_,transactions=transactions,seed=31+n_+h_,stress=True)
    window=[-131072]*n if custom else fixed.window(n)
    # Analysis keeps its standard window. Only synthesis uses the custom signed ROM.
    (folder/'window.mem').write_text('\n'.join(f'{v&((1<<18)-1):018b}' for v in window)+'\n')
    # The special geometries need reciprocal tables absent from the production catalog.
    # Keep all smoke/sweep tables local, in the binary format consumed by sync_rom.
    (folder/'recip.mem').write_text(''.join(f'{v:024b}\n' for row in fixed.reciprocals(n,hop) for v in row))
    if custom:save(folder/'sy_in.txt',impulses(n,hop))
    rows=read_rows(folder/'sy_in.txt');writes,reads,out,stats,overlap=raw_reference(rows,n,hop,window)
    if not custom and out!=read_rows(folder/'sy_out.txt'):raise RuntimeError('Independent overlap reference differs from production synthesis')
    if custom:
        save(folder/'sy_out.txt',out)
        for node in ('spectrum','output'):
            write_expected(folder/f'stft_{node}_expected.txt',stats,[f'stft.{node}.re',f'stft.{node}.im'])
        save_json(folder/'saturation.json',stats)
    save(folder/'istft_writes.txt',writes);save(folder/'istft_reads.txt',reads)
    layout=widths.layout(n_,h_);peaks=[v for row in writes for v in row[3:5]];sums=[v for row in writes for v in row[5:7]]
    observed_products=[min(peaks),max(peaks)];observed_sums=[min(sums),max(sums)]
    if custom and (observed_products!=layout['product_bounds'] or observed_sums!=layout['accumulator_bounds']):
        raise RuntimeError('Signed window fixtures did not attain both exact product/accumulator limits')
    if overlap!=layout['overlap']:raise RuntimeError('Maximum live overlap not exercised')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()}
    return dict(case=name,log2n=n_,log2hop=h_,custom_window=custom,layout=layout,
                spectra=len(read_rows(folder/'an_out.txt')),samples=len(out),raw_writes=len(writes),raw_reads=len(reads),
                max_overlap=overlap,observed_products=observed_products,observed_sums=observed_sums,vector_hashes=hashes)


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='Exact signed18 window / symmetric24 inverse-FFT products and all live overlap-add states; physical synthesis paused',
                records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_negative=[])


def check_acceptance(result):
    if result['records']!=report()['records']:raise RuntimeError('Changed or incomplete ISTFT width measurements')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_negative')):raise RuntimeError('Unverified RTL records')
        return
    expected={(r['case'],aw,pw,a,s) for r in result['records'] for aw in {r['layout']['accumulator_width'],44}
              for pw in (41,42) for a in (1,0) for s in SCENARIOS}
    records=result['rtl_equivalence']
    if len(records)!=len(expected) or {(r['case'],r['acc_width'],r['product_width'],r['active'],r['scenario']) for r in records}!=expected:
        raise RuntimeError('Incomplete/duplicated ISTFT RTL equivalence')
    for r in records:
        source=next(row for row in result['records'] if row['case']==r['case'])
        if (any(r[key]!=source[key] for key in ('spectra','samples','raw_writes','raw_reads','max_overlap'))
                or r['observers_verified'] is not True or type(r['cycles']) is not int or r['cycles']<=0):
            raise RuntimeError('Missing ISTFT arithmetic observations')
    for source in result['records']:
        for active in (1,0):
            for scenario in SCENARIOS:
                if len({r['cycles'] for r in records if r['case']==source['case'] and r['active']==active and r['scenario']==scenario})!=1:
                    raise RuntimeError('ISTFT cycles changed with arithmetic widths')
    expected={(r['case'],a,aw,pw) for r in result['records'] for a in (1,0)
              for aw,pw in ((r['layout']['accumulator_width']-1,41),(45,41),(r['layout']['accumulator_width'],40),(r['layout']['accumulator_width'],43))}
    parameters=result['rtl_parameters']
    if len(parameters)!=len(expected) or {(r['case'],r['active'],r['acc_width'],r['product_width']) for r in parameters}!=expected or any(r['returncode']==0 or r['tag']!='PARAMETER' for r in parameters):
        raise RuntimeError('Incomplete ISTFT parameter rejection')
    negative=result['rtl_negative']
    if len(negative)!=6 or {(r['active'],r['tag']) for r in negative}!={(a,t) for a in (1,0) for t in ('PRODUCT','ACCUMULATOR','RAM_READ')} or any(r['returncode']==0 for r in negative):
        raise RuntimeError('Incomplete ISTFT arithmetic fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed ISTFT vectors')
        artifacts.extend(folder.glob('*'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/stft_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(row,aw,pw,scenario,bad=False):
            folder=base/'vectors'/row['case'];tables=files(row['log2n'],row['log2hop'])
            tables['RECIP_FILE']=str(folder/'recip.mem')
            options=[f'-gLOG2N={row["log2n"]}',f'-gLOG2HOP={row["log2hop"]}',f'-gRESET_ACTIVE={active}',f'-gACC_WIDTH={aw}',f'-gPRODUCT_WIDTH={pw}',
                *(f'-g{key}={ROOT/value}' for key,value in tables.items()),f'-gSYNTH_WINDOW_FILE={folder/"window.mem"}',f'+VECTORS={folder}','+CHECK_ACCUMULATOR',
                *SCENARIOS.get(scenario,[]),*(['+INJECT_'+scenario] if scenario in ('PRODUCT','ACCUMULATOR','RAM_READ') else [])]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet','work.stft_tb',*options,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/f'{row["case"]}_a{aw}_p{pw}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            for aw in sorted({row['layout']['accumulator_width'],44}):
                for pw in (41,42):
                    if active==1:
                        log=work/f'{row["case"]}_a{aw}_p{pw}_lint.log'
                        execute(['verilator','--lint-only','-Wall','--top-module','stft_synthesis',f'-GACC_WIDTH={aw}',f'-GPRODUCT_WIDTH={pw}',
                            f'-GLOG2N={row["log2n"]}',f'-GLOG2HOP={row["log2hop"]}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
                    for scenario in SCENARIOS:
                        text,_=run(row,aw,pw,scenario)
                        numeric=re.search(r'PASS STFT: (\d+) spectra, (\d+) samples, (\d+) cycles',text)
                        raw=re.search(r'PASS ISTFT WIDTHS: (\d+) (\d+) (\d+)',text)
                        if not numeric or not raw:raise RuntimeError('Missing ISTFT numeric/raw evidence')
                        check_observers(text,base/'vectors'/row['case'],'stft')
                        result['rtl_equivalence'].append(dict(case=row['case'],acc_width=aw,product_width=pw,active=active,scenario=scenario,
                            spectra=int(numeric[1]),samples=int(numeric[2]),cycles=int(numeric[3]),raw_writes=int(raw[1]),raw_reads=int(raw[2]),max_overlap=int(raw[3]),observers_verified=True))
            for aw,pw in ((row['layout']['accumulator_width']-1,41),(45,41),(row['layout']['accumulator_width'],40),(row['layout']['accumulator_width'],43)):
                text,rc=run(row,aw,pw,'parameter',True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS STFT:' in text:raise RuntimeError('Unsafe ISTFT widths accepted')
                result['rtl_parameters'].append(dict(case=row['case'],acc_width=aw,product_width=pw,active=active,tag='PARAMETER',returncode=rc))
            print('PASS ISTFT widths',row['case'],'reset',active,flush=True)
        row=result['records'][-1]
        for tag in ('PRODUCT','ACCUMULATOR','RAM_READ'):
            text,rc=run(row,row['layout']['accumulator_width'],41,tag,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS STFT:' in text:raise RuntimeError('ISTFT arithmetic fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/istft_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS ISTFT width study; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
