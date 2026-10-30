#!/usr/bin/env python3
"""Place/route portable RTL in both vendors; reject warnings and bad timing."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import shutil
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,verify
from rtl_constraints import generate
from rtl_cases import BLOCKS
from run_rtl import SOURCES as RTL_SOURCES

TOPS={key:value['top'] for key,value in BLOCKS.items()}
TOPS.update(ram='sync_ram',rom='sync_rom',bit_sync='bit_sync',reset_sync='reset_sync',bpsk_tx='bpsk_tx',bpsk_rx='bpsk_rx',qpsk_tx='qpsk_tx',qpsk_rx='qpsk_rx',
           qpsk_half_diff_tx='qpsk_half_diff_tx',qpsk_axis_diff_tx='qpsk_axis_diff_tx',qpsk_axis_tx='qpsk_axis_tx',
           qpsk_half_diff_rx='qpsk_half_diff_rx',qpsk_axis_diff_ff_rx='qpsk_axis_diff_ff_rx',
           psk8_axis_tx='psk8_axis_tx',psk8_rotated_tx='psk8_rotated_tx',psk8_ff_rx='psk8_ff_rx',psk8_fb_rx='psk8_fb_rx',psk8_rotated_fb_rx='psk8_rotated_fb_rx',
           qpsk_diff_tx='qpsk_diff_tx',simo_rx='simo_rx',mrc2='fxp_mrc2',pi4_tx='pi4_tx',pi4_rx='pi4_rx',qam16_tx='qam16_tx',qam16_rx='qam16_rx',
           qam16_eq_rx='qam16_eq_rx',qam16_dfe_rx='qam16_dfe_rx',qam64_tx='qam64_tx',qam64_rx='qam64_rx',
           msk_tx='msk_tx',msk_rx='msk_rx',gmsk_tx='gmsk_tx',gmsk_rx='gmsk_rx',oqpsk_tx='oqpsk_tx',oqpsk_rx='oqpsk_rx',fft64='fft_r2sdf',fft1024='fft_r2sdf',ofdm_tx='ofdm_tx',ofdm_rx='ofdm_rx',stft_analysis='stft_analysis',stft_synthesis='stft_synthesis',pfb='pfb_analysis',fir='fir_runtime',notch='notch_iir',kalman='kalman_scalar',fsk_tx='fsk_tx',fsk_rx='fsk_rx',beamform='beamform',alamouti='alamouti_rx',costas='costas_loop',gardner='gardner_timing',lms='lms_filter',ldpc='ldpc_decoder',gf2='gf2_encoder',mmse2='mmse2',rls='rls_filter',omlsa='omlsa')


def execute(command,output,log):
    with log.open('w') as stream:
        process=subprocess.run([str(x) for x in command],cwd=output,stdout=stream,stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f'Synthesis failed ({process.returncode}); inspect {log}\n{log.read_text()[-6000:]}')


def warnings(text,vendor,allowed):
    pattern=r'^\s*(?:CRITICAL )?WARNING:\s*\[([^\]]+)\].*$' if vendor=='xilinx' else r'^\s*(?:Critical )?Warning\s*\((\d+)\):.*$'
    messages=[(match[1],match[0]) for match in re.finditer(pattern,text,re.MULTILINE)]
    unknown=[]
    for code,line in messages:
        rule=allowed.get(code)
        accepted=rule is not None
        if isinstance(rule,dict):accepted=bool(re.search(rule['pattern'],line.lstrip()))
        if not accepted or line.lstrip().startswith(('CRITICAL','Critical')):unknown.append(line)
    if unknown:raise RuntimeError('Unapproved synthesis warnings:\n'+'\n'.join(dict.fromkeys(unknown)))
    return list(dict.fromkeys(line for _,line in messages))


def timing_acceptance(setup,hold,spec,vendor):
    required=float(spec['acceptance']['setup_slack_ns'])
    if vendor=='altera':required=max(required,float(spec['acceptance']['altera_setup_margin_ns']))
    if not math.isfinite(setup) or not math.isfinite(hold) or setup<=0 or setup<required or hold<=float(spec['acceptance']['hold_slack_ns']):
        raise RuntimeError(f'Timing rejected: setup {setup:.3f} ns (must exceed {required}), hold {hold:.3f} ns')


def quartus_phase(block,phase):
    """Split a long Quartus run into resumable map, fit and final STA jobs.

    Every phase validates the original source snapshot. Intermediate runs never
    produce PASS evidence; only finished STA with accepted warnings/slacks can.
    """
    output=ROOT/'build/rtl/synth';directory=output/block/'altera';directory.mkdir(parents=True,exist_ok=True)
    checkpoint=output/block/'quartus_stage.json';pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
    quartus=Path(os.environ.get('QUARTUS_ROOT',str(Path.home()/'altera/25.1std/quartus')))/'bin'
    top=TOPS[block];kind=list(TOPS).index(block)
    if phase=='map':
        evidence=begin();spec=generate(ROOT/'rtl/constraints/common.yaml',directory/'constraints')
        stage=Path(tempfile.mkdtemp(prefix='modems-rtl-quartus-'));project=stage/'project';project.mkdir()
        sources=RTL_SOURCES+[ROOT/'rtl/rtl_synth_top.sv']
        staged=[]
        for source in sources+list(pilot.glob('*.svh')):
            copy=stage/source.relative_to(ROOT);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,copy)
            if source.suffix=='.sv':staged.append(copy)
        manifest=stage/'sources.txt';manifest.write_text('\n'.join(map(str,staged))+'\n')
        shutil.copytree(pilot/'tables',project/'rtl/modems/bpsk_costas_2008_08_25/tables')
        shutil.copytree(ROOT/'rtl/common/mem',project/'rtl/common/mem',ignore=shutil.ignore_patterns('*.sv'))
        sdc=stage/'timing.sdc';shutil.copy2(directory/'constraints/timing.sdc',sdc)
        for script in ('rtl_synth_quartus.tcl','rtl_timing_quartus.tcl','rtl_pins_quartus.tcl','rtl_resources_quartus.tcl'):shutil.copy2(ROOT/'tools'/script,stage/script)
        job=dict(evidence,stage=str(stage),spec=spec,status='MAPPING',artifacts=[])
        write_json(checkpoint,job);write_json(output/block/'altera.json',dict(evidence,status='RUNNING'))
        pins=stage/'pins.tcl';execute([quartus/'quartus_sta','-t',stage/'rtl_pins_quartus.tcl',spec['targets']['altera'],pins],project,directory/'pins.log')
        log=directory/'runner_map.log'
        execute([quartus/'quartus_sh','-t',stage/'rtl_synth_quartus.tcl',stage,project,top,spec['targets']['altera'],sdc,manifest,kind,pins,spec['io']['output_load_pf'],'map'],project,log)
        job.update(status='MAPPED',artifacts=[str(directory/'pins.log'),str(log)])
        stage_inputs=[manifest,sdc,pins,project/f'{top}.qsf',*stage.rglob('*.sv'),*stage.rglob('*.svh'),*stage.rglob('*.tcl'),*project.rglob('*.mem')]
        job['artifact_hashes']=finish(evidence,stage_inputs)['artifact_hashes']
        verify(evidence);write_json(checkpoint,job);print(f'PASS Quartus map {block}; fit and STA still required')
        return
    if not checkpoint.is_file():raise RuntimeError('Run --quartus-phase map first')
    job=json.loads(checkpoint.read_text());verify(job);stage=Path(job['stage']);project=stage/'project';spec=job['spec']
    if phase=='fit':
        if job['status']!='MAPPED':raise RuntimeError('Map must complete before fit')
        log=directory/'runner_fit.log';execute([quartus/'quartus_fit','--read_settings_files=on','--write_settings_files=off',top],project,log)
        job['status']='FITTED';job['artifacts'].append(str(log));verify(job);write_json(checkpoint,job)
        print(f'PASS Quartus fit {block}; STA still required');return
    if job['status']!='FITTED':raise RuntimeError('Fit must complete before STA')
    execute([quartus/'quartus_sta','-t',stage/'rtl_timing_quartus.tcl',project,top],project,directory/'timing.log')
    execute([quartus/'quartus_sh','-t',stage/'rtl_resources_quartus.tcl',project,top],project,directory/'resources.log')
    shutil.copytree(project,directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('db','incremental_db'))
    corners=[]
    for line in (directory/'timing.tsv').read_text().splitlines():
        name,s,h=line.split('\t');corners.append(dict(condition=name,setup_slack_ns=float(s),hold_slack_ns=float(h)))
    if not corners:raise RuntimeError('No operating conditions evaluated')
    setup=min(c['setup_slack_ns'] for c in corners);hold=min(c['hold_slack_ns'] for c in corners)
    resources={}
    for line in (directory/'resources.tsv').read_text().splitlines():
        fields=line.split('\t')
        if len(fields)>1:resources[fields[0]]=fields[1]
    policy=json.loads((ROOT/'rtl/warnings.json').read_text())['altera']
    logs=[Path(p) for p in job['artifacts']]+[directory/'timing.log',directory/'resources.log']
    accepted=warnings('\n'.join(p.read_text() for p in logs),'altera',policy)
    if any('latch' in key.lower() and re.search(r'[1-9]',str(value)) for key,value in resources.items()):raise RuntimeError('Latch resource detected')
    timing_acceptance(setup,hold,spec,'altera')
    artifacts=[*logs,directory/'timing.tsv',directory/'resources.tsv',directory/'setup.rpt',directory/'hold.rpt',directory/'unconstrained.rpt',directory/'fmax.rpt',directory/'constraints/timing.sdc',*directory.rglob('*.mem')]
    record=dict(block=block,top=top,vendor='altera',part=spec['targets']['altera'],status='PASS',frequency_mhz=spec['clock']['frequency_mhz'],output_load_pf=spec['io']['output_load_pf'],setup_slack_ns=setup,hold_slack_ns=hold,resources=resources,accepted_warnings=accepted,operating_conditions=corners,
                scope='Block in a physical IO harness, including harness resources; not board timing.',**finish({k:job[k] for k in ('started_at_utc','source_hashes')},artifacts))
    write_json(output/block/'altera.json',record);job['status']='COMPLETE';write_json(checkpoint,job)
    print(f'PASS {block} altera: setup {setup:.3f} ns, hold {hold:.3f} ns')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--quartus-phase',choices=['all','map','fit','finish'],default='all')
    parser.add_argument('--block',choices=list(TOPS));parser.add_argument('--vendor',choices=['xilinx','altera','both'],default='both')
    args=parser.parse_args()
    if args.quartus_phase!='all':
        if not args.block or args.vendor!='altera':parser.error('--quartus-phase requires --block and --vendor altera')
        quartus_phase(args.block,args.quartus_phase)
        return
    selected={args.block:TOPS[args.block]} if args.block else TOPS
    vivado=Path(os.environ.get('VIVADO_ROOT','/tools/Xilinx/Vivado/2024.2'))/'bin/vivado'
    quartus=Path(os.environ.get('QUARTUS_ROOT',str(Path.home()/'altera/25.1std/quartus')))/'bin'
    vendors=['xilinx','altera'] if args.vendor=='both' else [args.vendor]
    output=ROOT/'build/rtl/synth';output.mkdir(parents=True,exist_ok=True)
    spec=generate(ROOT/'rtl/constraints/common.yaml',output/'constraints')
    policy=json.loads((ROOT/'rtl/warnings.json').read_text());evidence=begin()
    aggregate=output/('results.json' if not args.block and args.vendor=='both' else f'{args.block or "all"}_{args.vendor}_results.json')
    write_json(aggregate,dict(evidence,status='RUNNING'));records=[];all_artifacts=[]
    pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
    sources=RTL_SOURCES+[ROOT/'rtl/rtl_synth_top.sv']
    manifest=output/'sources.txt';manifest.write_text('\n'.join(map(str,sources))+'\n')
    for block,top in selected.items():
        for vendor in vendors:
            directory=output/block/vendor;directory.mkdir(parents=True,exist_ok=True)
            rom_copy=directory/'rtl/common/mem/test_rom.mem';rom_copy.parent.mkdir(parents=True,exist_ok=True);rom_copy.write_bytes((ROOT/'rtl/common/mem/test_rom.mem').read_bytes())
            shutil.copytree(ROOT/'rtl/common/mem',directory/'rtl/common/mem',ignore=shutil.ignore_patterns('*.sv'),dirs_exist_ok=True)
            tables_copy=directory/'rtl/modems/bpsk_costas_2008_08_25/tables'
            shutil.copytree(pilot/'tables',tables_copy,dirs_exist_ok=True)
            target=output/block/f'{vendor}.json';write_json(target,dict(evidence,status='RUNNING'))
            log=directory/'runner.log';part=spec['targets'][vendor]
            if vendor=='xilinx':
                execute([vivado,'-mode','batch','-nojournal','-log',directory/'vivado.log','-source',ROOT/'tools/rtl_synth_vivado.tcl','-tclargs',ROOT,directory,top,part,output/'constraints/timing.xdc',manifest,list(TOPS).index(block)],directory,log)
                metrics=dict(line.split('\t') for line in (directory/'metrics.tsv').read_text().splitlines())
                setup=float(metrics.pop('setup_slack_ns'));hold=float(metrics.pop('hold_slack_ns'))
                resources={name:int(value) for name,value in metrics.items()}
                artifact_paths=[directory/'metrics.tsv',directory/'utilization.rpt',directory/'timing.rpt',directory/'critical.rpt',directory/'loops.rpt']
            else:
                # Quartus 25.1 Tcl cannot reliably open Cyrillic paths. Stage
                # byte-identical sources and scripts in an ASCII-only directory.
                with tempfile.TemporaryDirectory(prefix='modems-rtl-quartus-') as tmp:
                    stage=Path(tmp);project=stage/'project';project.mkdir()
                    staged_sources=[]
                    for source in sources:
                        copy=stage/source.relative_to(ROOT);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,copy);staged_sources.append(copy)
                    shutil.copytree(pilot/'tables',project/'rtl/modems/bpsk_costas_2008_08_25/tables')
                    for header in pilot.glob('*.svh'):
                        copy=stage/header.relative_to(ROOT);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(header,copy)
                    staged_manifest=stage/'sources.txt';staged_manifest.write_text('\n'.join(map(str,staged_sources))+'\n')
                    staged_sdc=stage/'timing.sdc';shutil.copy2(output/'constraints/timing.sdc',staged_sdc)
                    for script in ('rtl_synth_quartus.tcl','rtl_timing_quartus.tcl','rtl_pins_quartus.tcl'):shutil.copy2(ROOT/'tools'/script,stage/script)
                    shutil.copytree(ROOT/'rtl/common/mem',project/'rtl/common/mem',ignore=shutil.ignore_patterns('*.sv'))
                    staged_pins=stage/'pins.tcl'
                    execute([quartus/'quartus_sta','-t',stage/'rtl_pins_quartus.tcl',part,staged_pins],project,directory/'pins.log')
                    shutil.copy2(staged_pins,project/'pins.tcl')
                    try:
                        execute([quartus/'quartus_sh','-t',stage/'rtl_synth_quartus.tcl',stage,project,top,part,staged_sdc,staged_manifest,list(TOPS).index(block),staged_pins,spec['io']['output_load_pf']],project,log)
                        execute([quartus/'quartus_sta','-t',stage/'rtl_timing_quartus.tcl',project,top],project,directory/'timing.log')
                    finally:
                        shutil.copytree(project,directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('db','incremental_db'))
                corners=[]
                for line in (directory/'timing.tsv').read_text().splitlines():
                    name,s,h=line.split('\t');corners.append(dict(condition=name,setup_slack_ns=float(s),hold_slack_ns=float(h)))
                if not corners:raise RuntimeError('No operating conditions evaluated')
                setup=min(c['setup_slack_ns'] for c in corners);hold=min(c['hold_slack_ns'] for c in corners)
                resources={}
                for line in (directory/'resources.tsv').read_text().splitlines():
                    fields=line.split('\t')
                    if len(fields)>1:resources[fields[0]]=fields[1]
                artifact_paths=[directory/'timing.tsv',directory/'resources.tsv',directory/'setup.rpt',directory/'hold.rpt',directory/'unconstrained.rpt',directory/'fmax.rpt',directory/'timing.log']
            log_text=log.read_text()+((directory/'timing.log').read_text() if vendor=='altera' else '')
            accepted_warnings=warnings(log_text,vendor,policy[vendor])
            if any('latch' in key.lower() and re.search(r'[1-9]',str(value)) for key,value in resources.items()):raise RuntimeError('Latch resource detected')
            timing_acceptance(setup,hold,spec,vendor)
            period=1000/float(spec['clock']['frequency_mhz'])
            record=dict(block=block,top=top,vendor=vendor,part=part,status='PASS',frequency_mhz=spec['clock']['frequency_mhz'],output_load_pf=spec['io']['output_load_pf'],
                        setup_slack_ns=setup,hold_slack_ns=hold,resources=resources,accepted_warnings=accepted_warnings,
                        estimated_fmax_mhz=1000/(period-setup),scope='Block in a physical IO harness, including harness resources; not integrated modem or board timing.')
            if vendor=='altera':record['operating_conditions']=corners
            artifacts=[log,*rom_copy.parent.glob('*.mem'),*tables_copy.glob('*.mem'),manifest,output/f'constraints/timing.{"xdc" if vendor=="xilinx" else "sdc"}',*artifact_paths]
            record.update(finish(evidence,artifacts));write_json(target,record);all_artifacts += artifacts+[target];records.append(record)
            print(f'PASS {block} {vendor}: setup {setup:.3f} ns, hold {hold:.3f} ns',flush=True)
    write_json(aggregate,dict(status='PASS',records=records,**finish(evidence,all_artifacts)))
    print(f'PASS {len(records)} RTL syntheses')


if __name__=='__main__':main()
