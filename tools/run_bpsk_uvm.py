#!/usr/bin/env python3
"""Real UVM classes around ORDER2 BPSK RX and TX streaming pilots."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized, digest
from run_rtl import execute, SOURCES
from bpsk_cases import receiver_vectors, save
from uvm_floating_reference import write_float_reference, validate_float_reference, mutate_float_metadata, FILES as FLOAT_FILES

SCENARIOS=('stream','stalled','midreset','cfgreset')
SUMMARY=r'UVM BPSK PILOT checked=(\d+) frames=(\d+) acquisitions=(\d+) errors=(\d+) payload=(\d+) discarded=(\d+) resets=(\d+) partial_payload_discarded=(\d+) partial_errors_discarded=(\d+)'
HANDSHAKES=r'UVM PILOT HANDSHAKES cfg=(\d+) input=(\d+) stalls=(\d+) pending_resets=(\d+)'
SER=r'UVM PILOT SER frame=(\d+) errors=(\d+) symbols=(\d+)'
FLOAT_SER=r'UVM PILOT FLOAT SER frame=(\d+) rtl_errors=(\d+) float_errors=(\d+) delta=(-?\d+) symbols=(\d+)'
FLOAT_SUMMARY=r'UVM PILOT FLOAT SUMMARY frames=(\d+) rtl_errors=(\d+) float_errors=(\d+) symbols=(\d+)'
FLOAT_NEGATIVES=('decision','errorcount','denominator')
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def parse_report(text, model, scenario, reset_active, returncode=0, *, require_partial_errors=True,
                 warm_samples=4200, summary_pattern=SUMMARY):
    summaries=re.findall(summary_pattern,text);handshake_rows=re.findall(HANDSHAKES,text)
    summary=re.search(summary_pattern,text);handshakes=re.search(HANDSHAKES,text)
    if returncode or len(summaries)!=1 or len(handshake_rows)!=1 or re.search(r'UVM_(?:FATAL|ERROR)\s*:\s*[1-9]|UVM_(?:FATAL|ERROR)[^\n]*\[|\*\* (?:Fatal|Error)',text):
        raise RuntimeError('Complete successful UVM pilot report required')
    keys=('checked','frames','acquisitions','payload_errors','payload_symbols','discarded_expected_symbols','resets','discarded_partial_payload','discarded_partial_errors')
    result=dict(zip(keys,map(int,summary.groups())))
    result.update(dict(zip(('cfg_handshakes','input_handshakes','stalls','pending_resets'),map(int,handshakes.groups()))))
    expected_frames=model['frames'];symbols=model['symbols']//expected_frames;denominator=symbols-192
    rows=[tuple(map(int,m)) for m in re.findall(SER,text)]
    if result['frames']!=expected_frames or result['acquisitions']!=expected_frames+int(scenario=='midreset') or len(rows)!=expected_frames:
        raise RuntimeError('UVM frame/acquisition/SER marker count mismatch')
    if result['checked']+result['discarded_expected_symbols']!=model['symbols']+ (symbols if scenario=='midreset' else 0):
        raise RuntimeError('UVM expected symbol queues did not drain')
    expected_cfg=384 if scenario=='midreset' else 288 if scenario=='cfgreset' else 192
    expected_input=model['samples']+(warm_samples if scenario=='midreset' else 0)
    if result['cfg_handshakes']!=expected_cfg or result['input_handshakes']!=expected_input:
        raise RuntimeError('UVM actual input/config handshake count mismatch')
    if scenario!='stream' and result['stalls']<5:
        raise RuntimeError('UVM output backpressure missing')
    if scenario in ('cfgreset','midreset') and result['resets']<2:
        raise RuntimeError('UVM reset replay missing')
    if scenario=='midreset' and (result['discarded_expected_symbols']<1 or result['pending_resets']<1 or result['discarded_partial_payload']<1 or (require_partial_errors and result['discarded_partial_errors']<1)):
        raise RuntimeError('UVM midreset did not discard pending work')
    for index,(frame,errors,count) in enumerate(rows):
        if frame!=index or count!=denominator or errors!=model['payload_errors'][index]:
            raise RuntimeError('UVM original payload SER mismatch')
    if result['payload_errors']!=sum(model['payload_errors']) or result['payload_symbols']!=denominator*expected_frames:
        raise RuntimeError('UVM aggregate payload count mismatch')
    if 'float_payload_errors' in model:
        result.update(parse_float(text,model,rows,denominator))
    result.update(scenario=scenario,reset_active=reset_active,profile='bpsk',ser=result['payload_errors']/result['payload_symbols'] if result['payload_symbols'] else None,
                  defined=result['payload_symbols']>0,per_frame=[dict(frame=f,payload_errors=e,payload_symbols=n,ser=e/n if n else None,defined=n>0) for f,e,n in rows])
    return result


def parse_float(text,model,rows,denominator):
    """Actual RTL versus independent float SER on the same accepted payload interval."""
    floats=[tuple(map(int,m)) for m in re.findall(FLOAT_SER,text)];summary=re.findall(FLOAT_SUMMARY,text)
    if len(floats)!=model['frames'] or len(summary)!=1:raise RuntimeError('UVM float SER markers missing/duplicated')
    expected=model['float_payload_errors']
    if model['float_payload_symbols']!=[denominator]*model['frames']:raise RuntimeError('Float denominator metadata differs from payload interval')
    for index,((frame,rtl,flt,delta,count),(_,errors,symbols)) in enumerate(zip(floats,rows)):
        if frame!=index or rtl!=errors or count!=symbols or count!=denominator or flt!=expected[index] or delta!=rtl-flt:
            raise RuntimeError('UVM float/RTL SER comparison mismatch')
    frames,rtl,flt,symbols=map(int,summary[0])
    if (frames,rtl,flt,symbols)!=(model['frames'],sum(r[1] for r in floats),sum(expected),denominator*model['frames']):
        raise RuntimeError('UVM float SER summary mismatch')
    return dict(float_payload_errors=flt,rtl_minus_float_errors=rtl-flt,float_ser=flt/symbols if symbols else None,
                float_per_frame=[dict(frame=f,rtl_errors=r,float_errors=e,delta=d,payload_symbols=n,
                                      rtl_ser=r/n if n else None,float_ser=e/n if n else None,defined=n>0) for f,r,e,d,n in floats])


def prepare_float(folder,profile_name,model):
    # Written and independently re-validated on the original vectors, before any negative copy.
    meta=write_float_reference(folder,profile_name);validate_float_reference(folder,profile_name)
    model.update(float_payload_errors=meta['float_payload_errors'],float_payload_symbols=meta['float_payload_symbols'],float_reference=meta)
    return model


def float_negative_folders(folder,output,prefix,profile_name,alphabet,records,artifacts):
    folders={}
    for kind in FLOAT_NEGATIVES:
        target=output/f'{prefix}negative_float_{kind}_vectors'
        if target.exists():shutil.rmtree(target)
        changed=mutate_float_metadata(folder,target,kind,alphabet=alphabet)
        try:validate_float_reference(target,profile_name)
        except ValueError as exc:records[f'{prefix}validator_rejects_float_{kind}']=dict(changed=changed,rejected=str(exc))
        else:raise RuntimeError('Independent float validator accepted mutated '+kind)
        artifacts.extend(target/name for name in FLOAT_FILES);folders[kind]=target
    return folders


def verify_negative(text, returncode, category):
    if returncode==0 or re.search(SUMMARY,text) or not re.search(r'UVM_FATAL[^\n]*\['+category+r'\]',text) or not re.search(r'UVM_FATAL\s*:\s*[1-9]',text):
        raise RuntimeError('UVM negative control not rejected: '+category)


def prepare_vectors(folder):
    model=receiver_vectors(folder,frames=4,count=768,seed=19)
    save(folder/'payload_expected.txt',[(errors,) for errors in model['payload_errors']])
    return prepare_float(folder,'bpsk',model)


def poison_truth(source, target, *, alphabet=2):
    shutil.copytree(source,target,dirs_exist_ok=True)
    lines=(target/'rx_trace.txt').read_text().splitlines();row=lines[193].split()
    original=row[9];row[9]=str((int(row[9])+1)%alphabet);lines[193]=' '.join(row)
    (target/'rx_trace.txt').write_text('\n'.join(lines)+'\n')
    for name in ('payload_expected.txt',*FLOAT_FILES):
        if (source/name).is_file() and digest(source/name)!=digest(target/name):
            raise RuntimeError('Original expected error metadata was mutated')
    # Prove all numeric trace fields, and all rows except one truth field, survive.
    src=[line.split() for line in (source/'rx_trace.txt').read_text().splitlines()]
    changed=[line.split() for line in lines]
    for index,(a,b) in enumerate(zip(src,changed)):
        if a!=b and not (index==193 and a[:9]==b[:9] and a[9]==original):
            raise RuntimeError('SER negative changed numeric trace')


from bpsk_cases import rtl_parameters,p as psk
RX_PROFILES={profile.name:profile for profile in psk.PROFILES if profile is not psk.BPSK}
PROFILE_MARKER=r'UVM PILOT PROFILE label_bits=(\d+) index_bits=(\d+) gaincfg=(\d+) cfg_max=(\d+) label_max=(\d+) index_max=(\d+)'


def prepare_profile_vectors(folder,profile):
    model=receiver_vectors(folder,frames=4,count=768,seed=19,profile=profile)
    save(folder/'payload_expected.txt',[(errors,) for errors in model['payload_errors']])
    trace=[list(map(int,line.split())) for line in (folder/'rx_trace.txt').read_text().splitlines()[1:]]
    preamble=[int(line) for line in (folder/'preamble.txt').read_text().splitlines()[1:]]
    symbols=model['symbols']//model['frames'];warm=trace[3*symbols:4*symbols];errors=[0]
    for prefix,row in enumerate(warm,1):errors.append(errors[-1]+int(prefix>192 and row[7]!=row[9]))
    save(folder/'warm_reset_expected.txt',[(k,max(0,k-192),errors[k]) for k in range(symbols+1)])
    simo=profile is psk.QPSK_DIFF
    gains=list(map(int,(folder/'gains.txt').read_text().split()[1:])) if simo else None
    model.update(profile=profile.name,parameters=rtl_parameters(profile),label_bits=(profile.alphabet-1).bit_length(),
                 index_bits=(profile.order-1).bit_length(),simo=simo,gain_configuration=gains,warm_frame=3,warm_samples=4200,
                 immutable_warm_error_prefix=errors,cfg_label_max=max(preamble),
                 decoded_label_max=max(row[7] for row in trace),index_max=max(row[6] for row in trace),
                 gain_control_scope='One actual SIMO gain tuple per reset epoch' if simo else 'NOT_APPLICABLE: single-branch receiver has no gain configuration ports')
    return prepare_float(folder,profile.name,model)


def parse_profile_report(text,model,scenario,reset_active,returncode=0):
    r=parse_report(text,model,scenario,reset_active,returncode,require_partial_errors=False)
    markers=re.findall(PROFILE_MARKER,text)
    if len(markers)!=1:raise RuntimeError('Missing/duplicate complete profile width/config marker')
    label_bits,index_bits,gains,cfgmax,labelmax,indexmax=map(int,markers[0])
    expected_gains=(1+int(scenario in ('midreset','cfgreset'))) if model['simo'] else 0
    if (label_bits,index_bits,gains,cfgmax,labelmax,indexmax)!=(model['label_bits'],model['index_bits'],expected_gains,model['cfg_label_max'],model['decoded_label_max'],model['index_max']):
        raise RuntimeError('Full-width pin label/index/training/gain configuration coverage mismatch')
    if scenario=='midreset':
        prefix=r['checked']-model['symbols'];table=model['immutable_warm_error_prefix']
        if not 192<prefix<model['symbols']//model['frames'] or len(table)!=model['symbols']//model['frames']+1:
            raise RuntimeError('Invalid actual warm-prefix output count')
        if r['discarded_partial_payload']!=prefix-192 or r['discarded_partial_errors']!=table[prefix]:
            raise RuntimeError('Actual partial payload/errors differ from immutable original profile prefix')
    elif r['discarded_partial_payload'] or r['discarded_partial_errors'] or r['discarded_expected_symbols']:
        raise RuntimeError('Unexpected profile partial/reset discard')
    r.update(profile=model['profile'],label_bits=label_bits,index_bits=index_bits,gain_handshakes=gains,
             cfg_label_max=cfgmax,decoded_label_max=labelmax,index_max=indexmax,
             gain_control_scope=model['gain_control_scope'],
             partial_nonzero_error_counter_exercised=scenario=='midreset' and r['discarded_partial_errors']>0,
             original_warm_frame=model['warm_frame'] if scenario=='midreset' else None)
    return r


def poison_profile_warm_truth(source,target,*,alphabet,symbols=768):
    shutil.copytree(source,target,dirs_exist_ok=True)
    lines=(target/'rx_trace.txt').read_text().splitlines();index=1+3*symbols+192;row=lines[index].split()
    original=row.copy();decoded,truth=int(row[7]),int(row[9])
    row[9]=str((truth+1)%alphabet if decoded==truth else decoded);lines[index]=' '.join(row)
    if row[:9]!=original[:9] or row[9]==original[9]:raise RuntimeError('Warm SER fault must change truth only')
    (target/'rx_trace.txt').write_text('\n'.join(lines)+'\n')
    for file in [*source.glob('*.txt'),source/'float_reference.json']:
        if file.name!='rx_trace.txt' and digest(file)!=digest(target/file.name):raise RuntimeError('Warm fault changed immutable input/reference metadata')


def _run_profiles_serial_hdl(output,bindir,uvm,artifacts,profiles):
    records={}
    for profile in profiles:
        name=profile.name;folder=output/f'{name}_vectors';model=prepare_profile_vectors(folder,profile)
        bad_folder=output/f'{name}_negative_ser_vectors';poison_truth(folder,bad_folder,alphabet=profile.alphabet)
        warm_bad=output/f'{name}_negative_warm_ser_vectors';poison_profile_warm_truth(folder,warm_bad,alphabet=profile.alphabet)
        artifacts.extend(folder.glob('*.txt'));artifacts.extend(bad_folder.glob('*.txt'));artifacts.extend(warm_bad.glob('*.txt'));artifacts.append(folder/'float_reference.json')
        float_bad=float_negative_folders(folder,output,f'{name}_',name,profile.alphabet,records,artifacts)
        for active in (1,0):
            work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
            def run(command,log):
                result=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=90)
                text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log);return result.returncode,text
            if not (work/'work').is_dir():
                rc,text=run([bindir/'vlib','work'],work/'vlib.log')
                if rc:raise RuntimeError(f'Profile vlib failed rc{rc}: '+text[-2000:])
            parameters=model['parameters']
            defines=['+define+UVM_NO_DPI']+(['+define+RTL_RESET_LOW'] if active==0 else [])
            defines += [f'+define+PILOT_{param}={parameters[param]}' for param in ('ORDER','AMPLITUDE','DIFFERENTIAL','FEEDFORWARD','TIMING_LOOP','PI4','EQUALIZER')]
            defines += [f'+define+PILOT_SIMO={int(model["simo"])}']
            rc,text=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/bpsk_rx_uvm_tb.sv'],work/'compile.log')
            if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError(f'Profile compile failed/warned rc{rc}: '+text[-6000:])
            positive=work/'run.do';negative=work/'negative.do'
            positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
            negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
            base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_rx_uvm_top',f'-gTABLE_DIR={PILOT/"tables"}','+SYMBOLS=768','+CHECK_RESET_PREFIX','+FLOAT_SER']
            for scenario in SCENARIOS:
                rc,text=run([*base,f'+VECTORS={folder}',f'+SCENARIO={scenario}','-do',positive.name],work/f'{scenario}.log')
                records[f'{name}_{scenario}_reset_{active}']=parse_profile_report(text,model,scenario,active,rc)
                print(f'PASS UVM {name} {scenario} reset={active}',flush=True)
            controls=[('numeric','NUMERIC',folder,['+INJECT_MISMATCH']),('ser','SER',bad_folder,[]),
                      ('label_high_bit','NUMERIC',folder,['+INJECT_LABEL_HIGH_BIT']),
                      ('valid_x','PROTOCOL',folder,['+INJECT_M_VALID_X']),('ready_x','PROTOCOL',folder,['+INJECT_M_READY_X'])]
            controls += [(f'float_{kind}','FLOAT_SER',float_bad[kind],[]) for kind in FLOAT_NEGATIVES]
            if model['simo']:controls.append(('gain_ready_x','PROTOCOL',folder,['+INJECT_GAIN_READY_X']))
            else:records[f'{name}_negative_gain_ready_x_reset_{active}']=dict(status='NOT_APPLICABLE',reason=model['gain_control_scope'])
            for control,category,vector_dir,flags in controls:
                rc,text=run([*base,f'+VECTORS={vector_dir}','+SCENARIO=stream',*flags,'-do',negative.name],work/f'negative_{control}.log')
                verify_negative(text,rc,category);records[f'{name}_negative_{control}_reset_{active}']=dict(returncode=rc,detected_tag=category)
            rc,text=run([*base,f'+VECTORS={warm_bad}','+SCENARIO=midreset','-do',negative.name],work/'negative_warm_ser.log')
            verify_negative(text,rc,'SER');records[f'{name}_negative_warm_ser_reset_{active}']=dict(returncode=rc,detected_tag='SER')
            records[f'{name}_model_reset_{active}']=model
    return records


def run_profile_hdl(output,bindir,uvm,artifacts,profiles,jobs=4):
    """Independent profile libraries run concurrently; all results remain mandatory."""
    profiles=list(profiles)
    if not profiles:return {}
    if not 1<=jobs<=4:raise ValueError('UVM profile jobs must be1..4')
    def one(profile):
        files=[]
        records=_run_profiles_serial_hdl(output,bindir,uvm,files,[profile])
        return records,files
    records={}
    with ThreadPoolExecutor(max_workers=min(jobs,len(profiles))) as pool:
        futures=[pool.submit(one,profile) for profile in profiles]
        for future in as_completed(futures):
            child,files=future.result();records.update(child);artifacts.extend(files)
    return records


TX_SCENARIOS=('stream','gaps','stalled','midreset','outreset')
TX_SUMMARY=r'UVM BPSK TX checked=(\d+) frames=(\d+) input=(\d+) discarded=(\d+) discarded_inputs=(\d+) expected=(\d+) expected_inputs=(\d+) resets=(\d+) before_reset=(\d+) pending_resets=(\d+) held_last_resets=(\d+)'
TX_HANDSHAKES=r'UVM TX HANDSHAKES input=(\d+) output=(\d+) input_stalls=(\d+) output_stalls=(\d+) ready_gaps=(\d+) pending_resets=(\d+)'
TX_FRAME=r'UVM TX FRAME frame=(\d+) inputs=(\d+) samples=(\d+)'


def prepare_tx_vectors(folder):
    from bpsk_cases import generate
    counts=generate(folder);lengths=[1,2,33,192,768]
    samples=sum(8*n+32 for n in lengths)
    if counts['bits']!=sum(lengths) or counts['tx']!=samples:raise RuntimeError('TX vector geometry mismatch')
    return dict(frames=len(lengths),frame_symbols=lengths,input_symbols=sum(lengths),output_samples=samples,
                waveform='Existing production fixed transmit reference, signed18 Q15; no vector/model changes',
                configuration='NOT_APPLICABLE: BPSK_TX has no configuration ports')


def parse_tx_report(text,model,scenario,reset_active,returncode=0,*,modulation='BPSK'):
    if modulation not in ('BPSK','OQPSK','MSK','GMSK'):raise RuntimeError('Unsupported TX modulation')
    tail={'BPSK':32,'OQPSK':36,'MSK':0,'GMSK':32}[modulation]
    if scenario not in TX_SCENARIOS:raise RuntimeError('Unsupported TX scenario')
    summaries=re.findall(TX_SUMMARY.replace('BPSK',modulation),text);handshakes=re.findall(TX_HANDSHAKES,text)
    if returncode or len(summaries)!=1 or len(handshakes)!=1 or re.search(r'UVM_(?:FATAL|ERROR)\s*:\s*[1-9]|UVM_(?:FATAL|ERROR)[^\n]*\[|\*\* (?:Fatal|Error)',text):
        raise RuntimeError('Complete successful TX UVM report required')
    names=('checked','frames','input_checked','discarded_expected_samples','discarded_expected_inputs','expected_samples','expected_inputs','resets','samples_before_reset','pending_resets','held_last_resets')
    r=dict(zip(names,map(int,summaries[0])))
    r.update(dict(zip(('input_handshakes','output_handshakes','input_stalls','output_stalls','ready_source_gaps','monitor_pending_resets'),map(int,handshakes[0]))))
    lengths=model['frame_symbols'];normal_inputs=sum(lengths);normal_outputs=sum(8*n+tail for n in lengths)
    if lengths!=[1,2,33,192,768] or model['frames']!=len(lengths) or model['input_symbols']!=normal_inputs or model['output_samples']!=normal_outputs:
        raise RuntimeError('TX model metadata differs from declared independent frame geometry')
    rows=[tuple(map(int,row)) for row in re.findall(TX_FRAME,text)]
    if rows!=[(f,n,8*n+tail) for f,n in enumerate(lengths)] or r['frames']!=len(lengths):raise RuntimeError('TX frame geometry/completion mismatch')
    mid=scenario=='midreset';out=scenario=='outreset';reset=mid or out
    warm_inputs=768 if mid else 33 if out else 0;warm_outputs=8*warm_inputs+tail if reset else 0
    sent_warm=16 if mid else warm_inputs
    if (r['input_handshakes']!=normal_inputs+sent_warm or r['input_checked']!=r['input_handshakes'] or
        r['output_handshakes']!=r['checked'] or r['expected_samples']!=normal_outputs+warm_outputs or
        r['expected_inputs']!=normal_inputs+warm_inputs or r['discarded_expected_inputs']!=warm_inputs-sent_warm):
        raise RuntimeError('TX actual pin inputs/outputs/expected geometry mismatch')
    if r['checked']+r['discarded_expected_samples']!=r['expected_samples'] or r['input_checked']+r['discarded_expected_inputs']!=r['expected_inputs']:
        raise RuntimeError('TX expected queues did not conserve/drain')
    if r['checked']!=normal_outputs+r['samples_before_reset'] or r['resets']!=1+int(reset) or r['pending_resets']!=int(reset) or r['monitor_pending_resets']!=int(reset):
        raise RuntimeError('TX reset fence/actual discarded sample accounting mismatch')
    if r['held_last_resets']!=int(out):raise RuntimeError('TX held terminal output reset coverage mismatch')
    if mid and not 1<=r['samples_before_reset']<=16*8:raise RuntimeError('TX midreset did not observe partial samples before reset')
    if out and (r['samples_before_reset']!=8*33+tail-1 or r['discarded_expected_samples']!=1):raise RuntimeError('TX outreset must hold/drop exactly terminal TLAST sample')
    if not reset and (r['samples_before_reset'] or r['discarded_expected_samples']):raise RuntimeError('Unexpected TX discard/reset')
    if r['input_stalls']<5:raise RuntimeError('TX held input not exercised')
    if scenario in ('stalled','midreset','outreset') and r['output_stalls']<5:raise RuntimeError('TX held output not exercised')
    if scenario=='gaps' and r['ready_source_gaps']<20:raise RuntimeError('TX ready source gaps not exercised')
    if modulation in ('OQPSK','MSK','GMSK'):
        labels=re.findall(r'UVM TX LABELS bits=(\d+) mask=(\d+)',text)
        bits,mask=(2,15) if modulation=='OQPSK' else (1,3)
        if labels!=[(str(bits),str(mask))]:raise RuntimeError('TX full-width input label coverage missing')
        r.update(label_bits=bits,labels_seen_mask=mask)
    r.update(scenario=scenario,reset_active=reset_active,profile=modulation.lower()+'_tx',per_frame=[dict(frame=f,input_symbols=n,output_samples=count) for f,n,count in rows],
             scope=f'Actual s_valid&&s_ready and m_valid&&m_ready, fixed TX waveform and independent8*n+{tail} counts; reset drops pending expected rows; no cfg ports')
    return r


def verify_tx_negative(text,returncode,category,*,modulation='BPSK'):
    if returncode==0 or re.search(TX_SUMMARY.replace('BPSK',modulation),text) or f'PASS UVM {modulation} TX' in text or not re.search(r'UVM_FATAL[^\n]*\['+category+r'\]',text) or not re.search(r'UVM_FATAL\s*:\s*[1-9]',text):
        raise RuntimeError('TX UVM negative control not rejected: '+category)


def run_tx_hdl(output,bindir,uvm,artifacts):
    folder=output/'tx_vectors';model=prepare_tx_vectors(folder);artifacts.extend(folder.glob('*.txt'));records={}
    for active in (1,0):
        work=output/f'tx_reset_{active}';work.mkdir(parents=True,exist_ok=True)
        def command_run(command,log):
            result=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=90)
            text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log);return result.returncode,text
        if not (work/'work').is_dir():
            rc,text=command_run([bindir/'vlib','work'],work/'vlib.log')
            if rc:raise RuntimeError(f'TX vlib failed rc{rc}: '+text[-2000:])
        defines=['+define+UVM_NO_DPI']+(['+define+RTL_RESET_LOW'] if active==0 else [])
        rc,text=command_run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/bpsk_tx_uvm_tb.sv'],work/'compile.log')
        if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError(f'TX compile failed/warned rc{rc}: '+text[-7000:])
        positive=work/'run.do';negative=work/'negative.do'
        positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_tx_uvm_top',f'+VECTORS={folder}']
        for scenario in TX_SCENARIOS:
            rc,text=command_run([*base,f'+SCENARIO={scenario}','-do',positive.name],work/f'{scenario}.log')
            records[f'tx_{scenario}_reset_{active}']=parse_tx_report(text,model,scenario,active,rc)
            print(f'PASS UVM BPSK TX {scenario} reset={active}',flush=True)
        for name,category,flag,scenario in [('numeric','NUMERIC','INJECT_MISMATCH','stream'),('s_valid_x','PROTOCOL','INJECT_S_VALID_X','stream'),
                    ('s_ready_x','PROTOCOL','INJECT_S_READY_X','stream'),('m_valid_x','PROTOCOL','INJECT_M_VALID_X','stream'),
                    ('m_ready_x','PROTOCOL','INJECT_M_READY_X','stream'),('data_x','NUMERIC','INJECT_M_DATA_X','stream'),
                    ('held_data','STALL','INJECT_HELD_DATA','stalled')]:
            rc,text=command_run([*base,f'+SCENARIO={scenario}',f'+{flag}','-do',negative.name],work/f'negative_{name}.log')
            verify_tx_negative(text,rc,category);records[f'tx_negative_{name}_reset_{active}']=dict(returncode=rc,detected_tag=category)
        records[f'tx_model_reset_{active}']=model
    return records


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=('python','hdl','all'),default='all')
    parser.add_argument('--pilot',choices=('rx','tx','both'),default='both')
    parser.add_argument('--profile',choices=('all','bpsk',*RX_PROFILES),default='all')
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--output',type=Path,help='new isolated output directory')
    args=parser.parse_args();require_unoptimized()
    if not 1<=args.jobs<=4:parser.error('--jobs must be1..4')
    output=args.output.resolve() if args.output else ROOT/'build/rtl/bpsk_uvm'
    output.mkdir(parents=True,exist_ok=args.output is None)
    evidence=begin();target=output/(f'{args.suite}_results.json' if args.pilot=='both' else f'{args.pilot}_{args.suite}_results.json');artifacts=[];records={}
    if args.profile!='all':target=target.with_name(args.profile+'_'+target.name)
    write_json(target,dict(evidence,status='RUNNING'))
    try:
        if args.suite in ('python','all'):
            for test in ('test_bpsk_uvm_evidence','test_uvm_floating_reference'):
                log=output/f'{test}.log';execute([sys.executable,ROOT/f'tests/{test}.py'],ROOT,log);artifacts.append(log)
            records['python']='PASS'
        if args.suite in ('hdl','all') and args.pilot in ('rx','both') and args.profile in ('all','bpsk'):
            folder=output/'vectors';model=prepare_vectors(folder);bad_folder=output/'negative_ser_vectors';poison_truth(folder,bad_folder)
            artifacts.extend(folder.glob('*.txt'));artifacts.extend(bad_folder.glob('*.txt'));artifacts.append(folder/'float_reference.json')
            float_bad=float_negative_folders(folder,output,'',"bpsk",2,records,artifacts)
            bindir,uvm=questa_paths()
            for active in (1,0):
                work=output/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                defines=['+define+UVM_NO_DPI']+(['+define+RTL_RESET_LOW'] if active==0 else [])
                log=work/'compile.log';execute([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/bpsk_rx_uvm_tb.sv'],work,log);artifacts.append(log)
                positive=work/'run.do';negative=work/'negative.do'
                positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                artifacts.extend([positive,negative])
                base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_rx_uvm_top',f'-gTABLE_DIR={PILOT/"tables"}','+SYMBOLS=768','+FLOAT_SER']
                for scenario in SCENARIOS:
                    command=[*base,f'+VECTORS={folder}',f'+SCENARIO={scenario}','-do',positive.name]
                    result=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=90)
                    text=result.stdout+result.stderr;log=work/f'{scenario}.log';log.write_text(text);artifacts.append(log)
                    records[f'{scenario}_reset_{active}']=parse_report(text,model,scenario,active,result.returncode)
                    print(f'PASS UVM BPSK pilot {scenario} reset={active}',flush=True)
                for name,category,vector_dir,flags in [('numeric','NUMERIC',folder,['+INJECT_MISMATCH']),('ser','SER',bad_folder,[]),
                                                      ('valid_x','PROTOCOL',folder,['+INJECT_M_VALID_X']),('ready_x','PROTOCOL',folder,['+INJECT_M_READY_X']),
                                                      *[(f'float_{kind}','FLOAT_SER',float_bad[kind],[]) for kind in FLOAT_NEGATIVES]]:
                    result=subprocess.run([str(x) for x in [*base,f'+VECTORS={vector_dir}','+SCENARIO=stream',*flags,'-do',negative.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    text=result.stdout+result.stderr;log=work/f'negative_{name}.log';log.write_text(text);artifacts.append(log)
                    verify_negative(text,result.returncode,category)
                    records[f'negative_{name}_reset_{active}']=dict(returncode=result.returncode,detected_tag=category)
        if args.suite in ('hdl','all') and args.pilot in ('rx','both'):
            selected=[profile for name,profile in RX_PROFILES.items() if args.profile in ('all',name)]
            if selected:
                bindir,uvm=questa_paths();records.update(run_profile_hdl(output,bindir,uvm,artifacts,selected,jobs=args.jobs))
        if args.suite in ('hdl','all') and args.pilot in ('tx','both'):
            bindir,uvm=questa_paths();records.update(run_tx_hdl(output,bindir,uvm,artifacts))
        write_json(target,dict(finish(evidence,artifacts),status='PASS',records=records,pilot=args.pilot,rx_profile_selection=args.profile,tx_configuration='NOT_APPLICABLE: BPSK_TX has no configuration ports',scope='Real UVM sequencer/driver/monitor/scoreboard around BPSK RX/TX and every other bpsk_rx PSK/QAM profile (QPSK_DIFF as SIMO) selected by CLI. Actual accepted outputs; fixed numeric traces plus immutable original payload error counts; actual RTL SER versus independent float receiver SER on the same Q15 pin waveform and payload interval, reported as measured deltas without a tuned budget. No coverage claim for CPM/OQPSK modems or the section 5 DSP blocks.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS BPSK UVM '+args.suite)


if __name__=='__main__':main()
