#!/usr/bin/env python3
"""BPSK integer reference, strict lint, Questa numeric scoreboards."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_numeric_failure
from run_rtl import execute,SOURCES
from bpsk_cases import generate,mrc_vectors,receiver_vectors,rtl_parameters,p as psk
from bpsk_rx_review import recovery_vectors,checked_review
from bpsk_acquire_review import (direct_vectors, checked_acquire, checked_divide, divider_counts,
                                 checked_divide_negative, ACQUIRE_SCENARIOS, DIVIDE_SCENARIOS)

# QPSK and 8-PSK configurations of the same cores, one per integer profile.
# QPSK_DIFF runs as simo_rx: two branches combined by fxp_mrc2 before the core.
VARIANTS=(psk.QPSK,psk.QPSK_HALF_DIFF,psk.QPSK_AXIS_DIFF_FF,psk.QPSK_AXIS,psk.PSK8_FF,psk.PSK8_FB,psk.PSK8_ROTATED_FB,psk.QPSK_DIFF,psk.PI4,psk.QAM16,psk.QAM16_EQ,psk.QAM16_DFE,psk.QAM64)

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
SIMO=ROOT/'rtl/modems/simo_maximal_ratio_combining_2010_08_27'


def parse_rtl_payload_ser(text,report,*,profile,scenario,reset_active):
    """Measure raw accepted DUT labels against original truth, after training."""
    frames=report['frames'];symbols=report['symbols'];expected_errors=report['payload_errors']
    if frames<1 or symbols%frames or symbols//frames<192 or len(expected_errors)!=frames:
        raise RuntimeError('Invalid SER frame metadata')
    denominator=symbols//frames-192
    rows=[tuple(map(int,row)) for row in re.findall(r'RTL PAYLOAD SER frame=(\d+) errors=(\d+) symbols=(\d+)',text)]
    marker=re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors',text)
    if not marker or re.search(r'UVM_(?:FATAL|ERROR)|\*\* (?:Error|Fatal)',text):
        raise RuntimeError('Complete successful DUT receiver run required for SER evidence')
    if tuple(map(int,marker.groups()))!=(symbols,frames,sum(expected_errors)) or len(rows)!=frames:
        raise RuntimeError('Missing or incomplete actual-DUT SER markers')
    details=[]
    for index,(frame,error,count) in enumerate(rows):
        if frame!=index or count!=denominator or not 0<=error<=count or error!=expected_errors[index]:
            raise RuntimeError('DUT SER frame index, denominator or error count mismatch')
        details.append(dict(frame=frame,payload_errors=error,payload_symbols=count,
                            defined=count>0,ser=error/count if count else None))
    total_errors=sum(row[1] for row in rows);payload_symbols=frames*denominator
    return dict(profile=profile,scenario=scenario,reset_active=reset_active,frames=details,
                payload_errors=total_errors,payload_symbols=payload_symbols,
                defined=payload_symbols>0,ser=total_errors/payload_symbols if payload_symbols else None,
                scope='Actual DUT m_bit on m_valid&&m_ready versus original transmitted labels (trace column9), excluding192 training symbols. Raw finite-frame SER; no truth rotation. Bench uses UVM macros, not a full UVM environment.')


def numeric_negative(command,work,log,pass_marker):
    """Use a relative Tcl basename: Cyrillic absolute -do paths can break vish."""
    bad=subprocess.run([str(x) for x in [*command,'+INJECT_MISMATCH','-do','numeric_negative.do']],
                       cwd=work,capture_output=True,text=True,timeout=90)
    negative=bad.stdout+bad.stderr;log.write_text(negative)
    if bad.returncode!=13 or pass_marker in negative:
        raise RuntimeError(f'Numeric negative control not rejected: rc={bad.returncode}')
    require_numeric_failure(negative)
    return dict(returncode=bad.returncode,detected_tag='[NUMERIC]')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all')
    parser.add_argument('--output',type=Path,help='new isolated output directory')
    args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=args.output.resolve() if args.output else ROOT/'build/rtl/bpsk'
    output.mkdir(parents=True,exist_ok=args.output is None)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for script in (ROOT/'tests/test_bpsk_fixed.py',ROOT/'tests/test_psk_fixed.py',ROOT/'tests/test_mrc_fixed.py',ROOT/'tests/test_bpsk_ser_evidence.py',ROOT/'tests/test_bpsk_rx_review.py',ROOT/'tests/test_bpsk_acquisition_check.py',ROOT/'tools/bpsk_tables.py',ROOT/'tools/bpsk_precision.py'):
            log=output/f'{script.stem}.log';command=[sys.executable,script]+(['--check'] if script.stem=='bpsk_tables' else ['--output',output/'precision_results.json'] if script.stem=='bpsk_precision' else [])
            text=execute(command,ROOT,log);artifacts.append(log)
        artifacts.append(output/'precision_results.json')
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for active in (1,0):
            for steps in (1,2):
                log=output/f'lint_divider_steps{steps}_reset{active}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module','bpsk_divide',
                              f'-GRESET_ACTIVE={active}',f'-GSTEPS_PER_CYCLE={steps}',f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError('Lint warnings: divider modes')
                artifacts.append(log)
        for source in [*PILOT.glob('*.sv'),*SIMO.glob('*.sv')]:
            top=source.stem;log=output/f'lint_{top}.log';text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        for variant in VARIANTS:
            parameters=dict(rtl_parameters(variant),BLOCK_FIT=int(variant.block_fit))
            for top,names in (('bpsk_tx',('ORDER','AMPLITUDE','DIFFERENTIAL','TX_AXIS','PI4')),('bpsk_acquire',('ORDER','AMPLITUDE','BLOCK_FIT')),
                              ('bpsk_track',('ORDER','AMPLITUDE','DIFFERENTIAL','FEEDFORWARD','TIMING_LOOP','PI4','EQUALIZER')),('bpsk_rx',('ORDER','AMPLITUDE','DIFFERENTIAL','FEEDFORWARD','TIMING_LOOP','PI4','EQUALIZER'))):
                log=output/f'lint_{top}_{variant.name}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,*[f'-G{name}={parameters[name]}' for name in names],f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top} {variant.name}')
                artifacts.append(log)
                if top=='bpsk_rx':
                    low_log=output/f'lint_{top}_{variant.name}_reset0.log'
                    text=execute(['verilator','--lint-only','-Wall','--top-module',top,'-GRESET_ACTIVE=0',*[f'-G{name}={parameters[name]}' for name in names],f'-I{PILOT}',*SOURCES],ROOT,low_log)
                    if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top} {variant.name} reset0')
                    artifacts.append(low_log)
        # Other buffered RX cores repeat the same arbitration, and SIMO's combiner
        # has a separate gain configuration port. Cover both reset polarities.
        for active in (1,0):
            for top,options,label in [('bpsk_rx',[], 'bpsk'),('simo_rx',[], 'simo'),('fxp_mrc2',[], 'mrc'),
                                      ('cpm_rx',['-GGMSK=0'],'msk'),('cpm_rx',['-GGMSK=1'],'gmsk'),
                                      *[('oqpsk_rx',[f'-GLOOP_DELAY={d}'],f'oqpsk_delay{d}') for d in (1,8,10,16)]]:
                log=output/f'lint_review_{label}_reset{active}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-GRESET_ACTIVE={active}',*options,f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
                artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        vectors=output/'vectors';counts=generate(vectors);counts.update(mrc_vectors(vectors/'mrc'));rx=receiver_vectors(vectors);loopback=receiver_vectors(vectors/'loopback',frames=3,loopback=True);extra={}
        for name,count,seed,frames in [('alternate',768,82,4),('minimum',192,19,1),('maximum',2048,19,3)]:
            extra[name]=receiver_vectors(vectors/name,count=count,seed=seed,frames=frames)
        # QPSK variants reuse the same cores; vectors come from each integer profile.
        variant_reports={}
        for variant in VARIANTS:
            folder=vectors/variant.name;report={'stream':receiver_vectors(folder,profile=variant)}
            report['loopback']=receiver_vectors(folder/'loopback',frames=3,loopback=True,profile=variant)
            for name,count,seed,frames in [('minimum',192,23,1),('maximum',2048,23,3)]:
                report[name]=receiver_vectors(folder/name,count=count,seed=seed,frames=frames,profile=variant)
            variant_reports[variant.name]=report
        review_reports={'bpsk':receiver_vectors(vectors/'review'/'bpsk',count=244,frames=3,seed=119)}
        for variant in VARIANTS:
            review_reports[variant.name]=receiver_vectors(vectors/'review'/variant.name,count=244,frames=3,seed=119,profile=variant)
        recovery_reports=recovery_vectors(vectors/'recovery')
        direct_counts={profile.name:direct_vectors(vectors/'direct'/profile.name,profile) for profile in (psk.BPSK,*VARIANTS)}
        endpoints=divider_counts(vectors/'divide.txt')
        artifacts.extend(vectors.rglob('*.txt'))
        bindir,uvm=questa_paths()
        for active in (1,0):
            work=output/f'reset_{active}';work.mkdir(exist_ok=True)
            ser_records={};negative_records={}
            negative_script=work/'numeric_negative.do'
            negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.append(negative_script)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            execute([bindir/'vlog','-64','-sv','+define+UVM_NO_DPI',f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/bpsk_blocks_tb.sv',ROOT/'rtl/tb/bpsk_divide_modes_tb.sv',ROOT/'rtl/tb/bpsk_acquire_tb.sv',ROOT/'rtl/tb/bpsk_rx_tb.sv',ROOT/'rtl/tb/mrc_blocks_tb.sv',ROOT/'rtl/tb/bpsk_rx_buffers_tb.sv',ROOT/'rtl/tb/rx_cfg_priority_tb.sv'],work,work/'compile.log')
            base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_blocks_tb',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}',f'+VECTORS={vectors}']
            text=execute([*base,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'simulation.log')
            found=re.findall(r'PASS BPSK block (\d+): (\d+) exact outputs',text)
            if len(found)!=6 or 'PASS BPSK blocks' not in text or re.search(r'UVM_(?:FATAL|ERROR)|\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-8000:])
            for (_,checked),name in zip(found,['tx','fir','cordic','rotate','interp','divide']):
                if int(checked)!=counts[name]:raise RuntimeError('Incomplete vector coverage')
            acquisition_records={};divider_records={}
            for scenario in DIVIDE_SCENARIOS:
                probe=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_divide_modes_tb',
                       f'-gRESET_ACTIVE={active}',f'+VECTORS={vectors}',f'+DIVIDE_SCENARIO={scenario}']
                log=work/f'divider_{scenario}.log'
                text=execute([*probe,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                divider_records[scenario]=checked_divide(text,scenario,endpoints);artifacts.append(log)
                if scenario!='all':
                    for mode in (1,2):
                        log=work/f'divider_{scenario}_mode{mode}_negative.log'
                        negative_records[f'divider/{scenario}/{mode}']=numeric_negative(
                            [*probe,f'+INJECT_STEP_MODE={mode}'],work,log,'PASS BPSK divider modes:')
                        checked_divide_negative(log.read_text(),scenario,mode);artifacts.append(log)
            for profile in (psk.BPSK,*VARIANTS):
                for scenario in ACQUIRE_SCENARIOS:
                    probe=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_acquire_tb',
                           f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}',
                           f'-gORDER={profile.order}',f'-gAMPLITUDE={profile.amplitude}',f'-gBLOCK_FIT={int(profile.block_fit)}',
                           f'+VECTORS={vectors/"direct"/profile.name}',f'+ACQUIRE_SCENARIO={scenario}']
                    log=work/f'acquire_{profile.name}_{scenario}.log'
                    text=execute([*probe,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                    acquisition_records[f'{profile.name}/{scenario}']=checked_acquire(text,scenario,direct_counts[profile.name])
                    artifacts.append(log)
                    log=work/f'acquire_{profile.name}_{scenario}_negative.log'
                    negative_records[f'acquire/{profile.name}/{scenario}']=numeric_negative(probe,work,log,'PASS BPSK direct acquisition:')
                    checked_acquire(log.read_text(),scenario,direct_counts[profile.name],negative=True);artifacts.append(log)
            negative_records['bpsk_blocks']=numeric_negative(base,work,work/'negative.log','PASS BPSK blocks')
            artifacts += [work/'compile.log',work/'simulation.log',work/'negative.log']
            mrcbase=[*base];mrcbase[mrcbase.index('work.bpsk_blocks_tb')]='work.mrc_blocks_tb';mrcbase[mrcbase.index(f'+VECTORS={vectors}')]=f'+VECTORS={vectors/"mrc"}'
            text=execute([*mrcbase,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'mrc_blocks.log')
            divided=re.search(r'PASS MRC divider: (\d+) exact quotients',text);combined=re.search(r'PASS MRC combiner: (\d+) configurations, (\d+) exact outputs',text)
            if not divided or not combined or 'PASS MRC blocks' not in text or re.search(r'UVM_(?:FATAL|ERROR)|\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-8000:])
            if (int(divided[1]),int(combined[1]),int(combined[2]))!=(counts['divide_wide'],counts['mrc_configs'],counts['mrc_samples']):raise RuntimeError('Incomplete MRC vector coverage')
            negative_records['mrc_blocks']=numeric_negative(mrcbase,work,work/'mrc_negative.log','PASS MRC blocks')
            artifacts += [work/'mrc_blocks.log',work/'mrc_negative.log']
            rxbase=[*base];rxbase[rxbase.index('work.bpsk_blocks_tb')]='work.bpsk_rx_tb'
            for scenario in ('stream','stalled','reset'):
                log=work/f'rx_{scenario}.log'
                text=execute([*rxbase,*(['+STALL_OUTPUT'] if scenario=='stalled' else ['+RESET_MID_FRAME'] if scenario=='reset' else []),'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                match=re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors',text)
                if not match or tuple(map(int,match.groups()))!=(rx['symbols'],rx['frames'],sum(rx['payload_errors'])) or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
                ser_records[f'bpsk/{scenario}']=parse_rtl_payload_ser(text,rx,profile='bpsk',scenario=scenario,reset_active=active)
                artifacts.append(log)
            text=execute([*rxbase,'+PROTOCOL_ONLY','-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'protocol.log')
            if 'PASS BPSK protocol guards' not in text or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
            artifacts.append(work/'protocol.log')
            loopbase=[*rxbase];loopbase[loopbase.index(f'+VECTORS={vectors}')]=f'+VECTORS={vectors/"loopback"}'
            text=execute([*loopbase,'-gLOOPBACK=1','+STALL_OUTPUT','-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'loopback.log')
            match=re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors',text)
            if not match or tuple(map(int,match.groups()))!=(loopback['symbols'],loopback['frames'],0) or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
            ser_records['bpsk/loopback']=parse_rtl_payload_ser(text,loopback,profile='bpsk',scenario='loopback',reset_active=active)
            artifacts.append(work/'loopback.log')
            for name,report in extra.items():
                extra_base=[*rxbase];extra_base[extra_base.index(f'+VECTORS={vectors}')]=f'+VECTORS={vectors/name}'
                symbol_count=report['symbols']//report['frames'];log=work/f'rx_{name}.log'
                text=execute([*extra_base,f'-gSYMBOLS={symbol_count}',*(['+STALL_OUTPUT'] if name=='minimum' else []),'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                match=re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors',text)
                if not match or tuple(map(int,match.groups()))!=(report['symbols'],report['frames'],sum(report['payload_errors'])) or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
                ser_records[f'bpsk/{name}']=parse_rtl_payload_ser(text,report,profile='bpsk',scenario=name,reset_active=active)
                artifacts.append(log)
            negative_records['bpsk_receiver']=numeric_negative(rxbase,work,work/'rx_negative.log','PASS BPSK receiver:')
            artifacts.append(work/'rx_negative.log')
            for variant in VARIANTS:
                qvectors=vectors/variant.name;qpsk=variant_reports[variant.name];prefix=variant.name
                qbase=[*rxbase,*[f'-g{name}={value}' for name,value in rtl_parameters(variant).items()],*(['-gSIMO=1'] if variant is psk.QPSK_DIFF else [])];qbase[qbase.index(f'+VECTORS={vectors}')]=f'+VECTORS={qvectors}'
                for scenario,folder,options in [('stream',qvectors,[]),('stalled',qvectors,['+STALL_OUTPUT']),('reset',qvectors,['+RESET_MID_FRAME']),
                                                ('loopback',qvectors/'loopback',['-gLOOPBACK=1','+STALL_OUTPUT']),
                                                ('minimum',qvectors/'minimum',['-gSYMBOLS=192','+STALL_OUTPUT']),('maximum',qvectors/'maximum',['-gSYMBOLS=2048'])]:
                    report=qpsk['stream' if scenario in ('stream','stalled','reset') else scenario];log=work/f'{prefix}_{scenario}.log'
                    command=[*qbase,*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'];command[command.index(f'+VECTORS={qvectors}')]=f'+VECTORS={folder}'
                    text=execute(command,work,log)
                    match=re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors',text)
                    if not match or tuple(map(int,match.groups()))!=(report['symbols'],report['frames'],sum(report['payload_errors'])) or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
                    ser_records[f'{prefix}/{scenario}']=parse_rtl_payload_ser(text,report,profile=prefix,scenario=scenario,reset_active=active)
                    artifacts.append(log)
                if variant is psk.QPSK:
                    text=execute([*qbase,'+PROTOCOL_ONLY','-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{prefix}_protocol.log')
                    if 'PASS BPSK protocol guards' not in text or 'UVM_FATAL' in text:raise RuntimeError(text[-8000:])
                    artifacts.append(work/f'{prefix}_protocol.log')
                negative_records[f'{prefix}_receiver']=numeric_negative(qbase,work,work/f'{prefix}_negative.log','PASS BPSK receiver:')
                artifacts.append(work/f'{prefix}_negative.log')
            review_records={}
            for variant in (psk.BPSK,*VARIANTS):
                name=variant.name;report=review_reports[name]
                command=[*rxbase,*[f'-g{key}={value}' for key,value in rtl_parameters(variant).items()],*(['-gSIMO=1'] if variant is psk.QPSK_DIFF else []),'-gSYMBOLS=244']
                command[command.index(f'+VECTORS={vectors}')]=f'+VECTORS={vectors/"review"/name}'
                for index in (0,191):
                    log=work/f'review_{name}_cfg{index}.log'
                    probe=[*command,f'+CFG_COLLISION={index}']
                    text=execute([*probe,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                    review_records[f'{name}/cfg{index}']=checked_review(text,collision=index,report=report);artifacts.append(log)
                    log=work/f'review_{name}_cfg{index}_negative.log'
                    negative_records[f'{name}/cfg{index}']=numeric_negative(probe,work,log,'PASS BPSK RX cfg arbitration');artifacts.append(log)
            command=[*rxbase,'+SHORT_RECOVERY']
            command[command.index(f'+VECTORS={vectors}')]=f'+VECTORS={vectors/"recovery"}'
            log=work/'short_recovery.log'
            text=execute([*command,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
            review_records['short_recovery']=checked_review(text);artifacts.append(log)
            log=work/'short_recovery_negative.log'
            negative_records['short_recovery']=numeric_negative(command,work,log,'PASS BPSK RX short recovery');artifacts.append(log)
            for top,options,marker in [('bpsk_rx_buffers_tb',[],'PASS BPSK RX buffer guards'),
                                       *[('rx_cfg_priority_tb',[f'-gFAMILY={family}'],f'PASS RX family cfg priority family={family}') for family in range(3)]]:
                log=work/f'review_{top}_{"_".join(options)}.log'
                text=execute([bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),f'work.{top}',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                if marker not in text or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError('RX guard failed')
                if top=='bpsk_rx_buffers_tb' and re.findall(r'BPSK RX invalid short RETIRE written=(\d+)',text)!=['2048','132']:
                    raise RuntimeError('Missing invalid short bank retirement')
                artifacts.append(log)
                review_records[f'guards/{top}/{options}']='PASS'
            review_records['recovery_models']=recovery_reports
            records[f'reset_{active}']=dict(counts=counts,receiver=rx,receiver_extra=extra,loopback=loopback,variants=variant_reports,
                                           rtl_payload_ser=ser_records,rx_review=review_records,acquisition_review=acquisition_records,divider_review=divider_records,negative_controls=negative_records,negative_control='PASS')
            print(f'PASS BPSK blocks reset={active}',flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS BPSK {args.suite}')

if __name__=='__main__':main()
