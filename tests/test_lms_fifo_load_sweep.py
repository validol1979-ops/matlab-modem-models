"""Strict acceptance of LMS FIFO schedules, both numeric streams and directed coverage."""
import copy
import csv
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lms_fifo_load_sweep as sweep


def fixture(profile,load,depth):
    """Synthetic pin-parser fixture, not RTL evidence."""
    replay=sweep.model(profile,load,depth,trace=True);numeric=sweep.fixture(profile)
    controls=list(replay['trace']);rows=[];indices=dict(s=0,f=0,m=0,w=0)
    for cycle in range(len(controls),len(controls)+4):
        controls.append(dict(cycle=cycle,s_valid=0,s_ready=1,s_last=0,f_valid=0,f_ready=1,f_last=0,m_valid=0,m_ready=sweep.ready(load,'m',cycle),m_last=0,w_valid=0,w_ready=sweep.ready(load,'w',cycle),w_last=0,level=0))
    specs=[('s','input',('s_re','s_im','s_dre','s_dim','s_last')),('f','input',('f_re','f_im','f_dre','f_dim','f_last')),('m','expected',('m_pre','m_pim','m_ere','m_eim','m_last')),('w','weights',('w_re','w_im','w_last'))]
    for control in controls:
        row={k:0 for k in sweep.COLUMNS};row.update(control);row.update(configured=1,error=0)
        for port,key,fields in specs:
            if row[port+'_valid']:row.update(zip(fields,numeric[key][indices[port]]))
        rows.append(row)
        for port,_,_ in specs:indices[port]+=bool(row[port+'_valid'] and row[port+'_ready'])
    log=f"PASS LMS FIFO LOAD depth={depth} words={len(numeric['input'])} weights={len(numeric['weights'])} wait={replay['blocked_cycles']} peak={replay['peak']} held_data={sum(r['m_valid'] and not r['m_ready'] for r in rows)} held_weights={sum(r['w_valid'] and not r['w_ready'] for r in rows)} held_fifo={sum(r['f_valid'] and not r['f_ready'] for r in rows)}\n"
    return rows,log


def encode(rows):
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=sweep.COLUMNS);writer.writeheader();writer.writerows(rows);return out.getvalue()


class LmsLoadEvidence(unittest.TestCase):
    def test_exact_boundaries_all_profiles_and_independent_output_targets(self):
        sweep.check_acceptance(sweep.report())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            for profile in sweep.profiles():
                for load in sweep.loads():
                    minimum=sweep.model(profile,load)['minimum_depth']
                    for depth in (minimum,minimum-1):
                        with self.subTest(profile=profile['name'],load=load['name'],depth=depth):
                            self.assertGreaterEqual(depth,2)
                            rows,log=fixture(profile,load,depth);path.write_text(encode(rows));r=sweep.measured(path,profile,load,depth,log)
                            self.assertEqual(r['wait']==0,depth==minimum)
                            self.assertEqual((r['words'],r['weights']),(16,3*profile['taps']))
                            if load['name']=='mstall':self.assertEqual(r['singleton_weights_before_data'],1)
                            if load['name'] in ('wstall','mixed'):self.assertGreater(r['held_last_weights'],0)
                            if load['name']=='mixed':self.assertGreater(r['simultaneous_output_holds'],0)

    def test_both_numeric_streams_input_payload_and_all_holds_are_checked(self):
        profile=sweep.profiles()[-1];load=sweep.loads()[-1];depth=sweep.model(profile,load)['minimum_depth']-1
        rows,log=fixture(profile,load,depth)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            def reject(changed,summary=log):
                path.write_text(encode(changed))
                with self.assertRaises(RuntimeError):sweep.measured(path,profile,load,depth,summary)
            for port,fields in [('s',('s_re','s_im','s_dre','s_dim','s_last')),('f',('f_re','f_im','f_dre','f_dim','f_last')),('m',('m_pre','m_pim','m_ere','m_eim','m_last')),('w',('w_re','w_im','w_last'))]:
                for field in fields:
                    bad=copy.deepcopy(rows);next(r for r in bad if r[port+'_valid'] and r[port+'_ready'])[field]+=1
                    with self.subTest(port=port,field=field):reject(bad)
                bad=copy.deepcopy(rows)
                index=next(i for i,r in enumerate(bad[:-1]) if r[port+'_valid'] and not r[port+'_ready'])
                bad[index+1][fields[0]]+=1;reject(bad)
                bad=copy.deepcopy(rows);bad[index+1][port+'_valid']=0;reject(bad)
            for field,value in [('configured',0),('error',1),('level',999),('s_ready',2),('m_ready',2),('w_ready',2),('f_valid','x')]:
                bad=copy.deepcopy(rows);bad[3][field]=value;reject(bad)
            reject(rows[:5]+rows[6:]);reject(rows[:-4]);reject(rows,log+log);reject(rows,log+'** Fatal: [WEIGHTS] deliberate\n')

    def test_complete_matrix_and_directed_counter_tampering(self):
        data=sweep.report();data['rtl_verified']=True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            for profile in sweep.profiles():
                for load in sweep.loads():
                    minimum=sweep.model(profile,load)['minimum_depth']
                    for depth in (minimum,minimum-1):
                        rows,log=fixture(profile,load,depth);path.write_text(encode(rows));row=sweep.measured(path,profile,load,depth,log)
                        data['rows'].extend(dict(row,active=a) for a in (0,1))
            data['negative']=[dict(kind=kind,active=a,returncode=13) for kind in sweep.KINDS for a in (0,1)]
            data['lint']=[dict(log2n=n,depth=d,active=a,warnings=0) for n,d,a in sorted(sweep.configurations())]
            sweep.check_acceptance(data);self.assertEqual(len(data['rows']),160)
            for key in ('rows','negative','lint'):
                bad=copy.deepcopy(data);bad[key].pop()
                with self.subTest(key=key),self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            for field,value in [('wait',999),('peak',999),('active',True),('weights',0),('simultaneous_output_holds',999),('held_last_weights',999),('singleton_weights_before_data',999)]:
                bad=copy.deepcopy(data);bad['rows'][0][field]=value
                with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            for key in ('negative','lint'):
                bad=copy.deepcopy(data);bad[key][0]['active']=False
                with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            bad=copy.deepcopy(data);bad['negative'][0]['returncode']=1
            with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            bad=copy.deepcopy(data);bad['rtl_verified']=False
            with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)

    def test_model_metadata_requires_exact_types(self):
        data=sweep.report()
        for key,value in [('required_capacity',14.0),('blocked_cycles',False)]:
            bad=copy.deepcopy(data);bad['budgets'][0]['budget'][key]=value
            with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
        bad=copy.deepcopy(data);bad['profiles'][0]['taps']=True
        with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)

    def test_negative_requires_target_exact_kind_message_and_rc13(self):
        targets=dict(NUMERIC='LMS LOAD DATA TARGET',WEIGHTS='LMS LOAD WEIGHTS TARGET',CAPACITY='LMS LOAD CAPACITY TARGET',M_HOLD='LMS LOAD HOLD DATA TARGET',W_HOLD='LMS LOAD HOLD WEIGHTS TARGET')
        for kind in sweep.KINDS:
            tag='PROTOCOL' if kind in ('M_HOLD','W_HOLD') else kind
            message='LMS load '+('data' if kind=='M_HOLD' else 'weight')+' output: data changed while stalled' if tag=='PROTOCOL' else 'deliberate mismatch'
            text=f'{targets[kind]} cycle=11\n** Fatal: [{tag}] {message}\n'
            sweep.checked_negative(text,13,kind)
            for code in (0,1,12,14,-31,True):
                with self.assertRaises(RuntimeError):sweep.checked_negative(text,code,kind)
            for bad in (text.replace(targets[kind],'MISSING'),text+'PASS LMS FIFO LOAD',text.replace('['+tag+']','[WRONG]'),text.split('\n')[1]+'\n'+targets[kind]):
                with self.assertRaises(RuntimeError):sweep.checked_negative(bad,13,kind)
            if tag=='PROTOCOL':
                with self.assertRaises(RuntimeError):sweep.checked_negative(text.replace(message,'wrong output instance'),13,kind)

    def test_explicit_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'existing';folder.mkdir();marker=folder/'keep';marker.write_text('original')
            proc=subprocess.run([sys.executable,ROOT/'tools/lms_fifo_load_sweep.py','--output',folder],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0);self.assertIn('FileExistsError',proc.stderr)
            self.assertEqual(marker.read_text(),'original');self.assertFalse((folder/'results.json').exists())


if __name__=='__main__':unittest.main()
