#!/usr/bin/env python3
"""Bit-exact acquisition/receiver scoreboards with Verilator; never runs Questa."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from bpsk_cases import receiver_vectors, rtl_parameters, p, generate
from bpsk_verilator import build, command, ROOT
from regression_evidence import begin, finish
from run_bpsk import VARIANTS, parse_rtl_payload_ser
from bpsk_acquire_review import (direct_vectors, checked_acquire, checked_divide, divider_counts,
                                 ACQUIRE_SCENARIOS, DIVIDE_SCENARIOS, checked_divide_negative)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profiles',default='all')
    parser.add_argument('--direct-only',action='store_true',help='state-directed acquisition and divider review only')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--quick',action='store_true',help='one reset polarity, stream/stalled only')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    evidence=begin()
    profiles=[profile for profile in (p.BPSK,*VARIANTS) if args.profiles=='all' or profile.name in args.profiles.split(',')]
    if not profiles:raise ValueError('No selected profiles')
    if args.direct_only and args.quick:raise ValueError('--direct-only requires both reset polarities')
    def job(item):
        profile,active=item;folder=out/f'{profile.name}_reset{active}'
        parameters=rtl_parameters(profile);parameters.update(SYMBOLS=244,RESET_ACTIVE=active)
        if profile is p.QPSK_DIFF:parameters['SIMO']=1
        rows=[]
        if not args.direct_only:
            binary=build(folder,'bpsk_rx_tb',[ROOT/'rtl/tb/bpsk_rx_tb.sv'],parameters)
            report=receiver_vectors(folder/'vectors',frames=7,count=244,seed=119,profile=profile)
            def receiver_run(exe,vectors,model,scenario,options=()):
                log=folder/f'{scenario}.log'
                text=command([exe,f'+VECTORS={vectors}',*options],ROOT,log)
                ser=parse_rtl_payload_ser(text,model,profile=profile.name,scenario=scenario,reset_active=active)
                cycles=list(map(int,re.findall(r'RX ACQUISITION start=\d+ done=\d+ A=(\d+)',text)))
                if len(cycles)!=model['frames'] and scenario!='reset':raise RuntimeError('Missing A measurements')
                rows.append(dict(profile=profile.name,reset_active=active,scenario=scenario,A=sorted(set(cycles)),symbols=model['symbols'],ser=ser))
            for scenario,options in [('stream',[]),('stalled',['+STALL_OUTPUT'])]:
                receiver_run(binary,folder/'vectors',report,scenario,options)
            command([binary,f'+VECTORS={folder/"vectors"}','+INJECT_MISMATCH'],ROOT,folder/'negative.log',negative=True)
            if not args.quick:
                review=receiver_vectors(folder/'review',frames=3,count=244,seed=119,profile=profile)
                for index in (0,191):
                    text=command([binary,f'+VECTORS={folder/"review"}',f'+CFG_COLLISION={index}'],ROOT,folder/f'cfg{index}.log')
                    if f'PASS BPSK RX cfg arbitration index={index} symbols=732 acquisitions=3' not in text:raise RuntimeError('Missing cfg arbitration')
                parameters['SYMBOLS']=768
                wide=build(folder/'wide','bpsk_rx_tb',[ROOT/'rtl/tb/bpsk_rx_tb.sv'],parameters)
                model=receiver_vectors(folder/'wide_vectors',frames=7,count=768,seed=23,profile=profile)
                for scenario,options in [('wide_stream',[]),('reset',['+RESET_MID_FRAME']),('wide_stalled',['+STALL_OUTPUT'])]:
                    receiver_run(wide,folder/'wide_vectors',model,scenario,options)
                if profile is p.BPSK:
                    text=command([wide,f'+VECTORS={folder/"wide_vectors"}','+PROTOCOL_ONLY'],ROOT,folder/'protocol.log')
                    if 'PASS BPSK protocol guards' not in text:raise RuntimeError('Protocol guards missing')
        if not args.quick:
            direct_parameters=dict(ORDER=profile.order,AMPLITUDE=profile.amplitude,BLOCK_FIT=int(profile.block_fit),RESET_ACTIVE=active)
            direct=build(folder/'direct','bpsk_acquire_tb',[ROOT/'rtl/tb/bpsk_acquire_tb.sv'],direct_parameters)
            n=direct_vectors(folder/'direct_vectors',profile)
            for scenario in ACQUIRE_SCENARIOS:
                probe=[direct,f'+VECTORS={folder/"direct_vectors"}',f'+ACQUIRE_SCENARIO={scenario}']
                text=command(probe,ROOT,folder/f'direct_{scenario}.log')
                checks=checked_acquire(text,scenario,n)
                rows.append(dict(profile=profile.name,reset_active=active,scenario=scenario,**checks))
                text=command([*probe,'+INJECT_MISMATCH'],ROOT,folder/f'direct_{scenario}_negative.log',negative=True)
                checked_acquire(text,scenario,n,negative=True)
        print(f'PASS {profile.name} reset={active} scenarios={len(rows)}',flush=True)
        return rows
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows=sum(list(pool.map(job,[(profile,active) for profile in profiles for active in ((1,) if args.quick else (1,0))])),[])
    if not args.quick:
        generate(out/'blocks_vectors')
        endpoints=divider_counts(out/'blocks_vectors/divide.txt')
        for active in (1,0):
            if not args.direct_only:
                binary=build(out/f'blocks_reset{active}','bpsk_blocks_tb',[ROOT/'rtl/tb/bpsk_blocks_tb.sv'],dict(RESET_ACTIVE=active))
                text=command([binary,f'+VECTORS={out/"blocks_vectors"}'],ROOT,out/f'blocks_reset{active}.log')
                if 'PASS BPSK blocks' not in text:raise RuntimeError('Blocks incomplete')
            binary=build(out/f'divider_reset{active}','bpsk_divide_modes_tb',[ROOT/'rtl/tb/bpsk_divide_modes_tb.sv'],dict(RESET_ACTIVE=active))
            for scenario in DIVIDE_SCENARIOS:
                probe=[binary,f'+VECTORS={out/"blocks_vectors"}',f'+DIVIDE_SCENARIO={scenario}']
                text=command(probe,ROOT,out/f'divider_reset{active}_{scenario}.log')
                checks=checked_divide(text,scenario,endpoints)
                rows.append(dict(reset_active=active,scenario=f'divider/{scenario}',**checks))
                if scenario!='all':
                    for mode in (1,2):
                        text=command([*probe,'+INJECT_MISMATCH',f'+INJECT_STEP_MODE={mode}'],ROOT,
                                     out/f'divider_reset{active}_{scenario}_mode{mode}_negative.log',negative=True)
                        checked_divide_negative(text,scenario,mode)
    (out/'results.json').write_text(json.dumps(dict(finish(evidence,list(out.rglob('*.log'))),status='PASS',backend='verilator',rows=rows),indent=2)+'\n')


if __name__=='__main__':main()
