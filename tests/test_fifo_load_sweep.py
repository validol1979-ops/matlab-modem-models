"""Acceptance gates reject changed schedules, payloads and incomplete RTL evidence."""
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
import fifo_load_sweep as sweep


def fixture(load,depth):
    """Synthetic parser fixture, never presented as RTL evidence."""
    replay=sweep.model(load,depth,trace=True)
    numeric=sweep.fixture(load)
    rows=[];sent=consumed=seen=0
    controls=list(replay['trace'])
    for cycle in range(len(controls),len(controls)+4):
        ready=load['ready_pattern'][cycle%len(load['ready_pattern'])] and not any(a<=cycle<b for a,b in load['stall_windows'])
        controls.append(dict(cycle=cycle,s_valid=0,s_ready=1,f_valid=0,f_ready=1,m_valid=0,m_ready=int(ready),level=0))
    for sample in controls:
        row=dict(sample,configured=1,s_last=0,s_re=0,s_im=0,f_last=0,f_re=0,f_im=0,m_last=0,m_re=0,m_im=0,m_phase=0)
        for port,index,key,fields in [('s',sent,'input',('s_re','s_im','s_last')),('f',consumed,'input',('f_re','f_im','f_last')),('m',seen,'expected',('m_re','m_im','m_phase','m_last'))]:
            if row[port+'_valid']:
                row.update(zip(fields,numeric[key][index]))
        rows.append(row)
        sent+=bool(row['s_valid'] and row['s_ready']);consumed+=bool(row['f_valid'] and row['f_ready']);seen+=bool(row['m_valid'] and row['m_ready'])
    held_outputs=sum(r['m_valid'] and not r['m_ready'] for r in rows)
    held_fifo=sum(r['f_valid'] and not r['f_ready'] for r in rows)
    log=f"PASS FIFO LOAD depth={depth} words={replay['words']} wait={replay['blocked_cycles']} peak={replay['peak']} held_outputs={held_outputs} held_fifo={held_fifo}\n"
    return rows,log


def encode(rows):
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=sweep.COLUMNS);writer.writeheader();writer.writerows(rows)
    return out.getvalue()


class LoadEvidence(unittest.TestCase):
    def test_finite_workloads_have_exact_legal_depth_boundaries(self):
        data=sweep.report();sweep.check_acceptance(data)
        self.assertEqual([v['budget']['required_capacity'] for v in data['loads']],[50,14,14,21])
        for key,value in [('required_capacity',50.0),('blocked_cycles',False)]:
            bad=copy.deepcopy(data);bad['loads'][0]['budget'][key]=value
            with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            for load in sweep.loads():
                minimum=sweep.model(load)['minimum_depth']
                for depth in (minimum,minimum-1):
                    with self.subTest(load=load['name'],depth=depth):
                        rows,log=fixture(load,depth);path.write_text(encode(rows))
                        actual=sweep.measured(path,load,depth,log)
                        self.assertEqual(actual['wait']==0,depth==minimum)
                        self.assertGreaterEqual(depth,2)

    def test_trace_requires_actual_schedule_numeric_and_quiet_drain(self):
        load=sweep.loads()[2];depth=sweep.model(load)['minimum_depth'];rows,log=fixture(load,depth)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            def rejects(changed,summary=log):
                path.write_text(encode(changed))
                with self.assertRaises(RuntimeError):sweep.measured(path,load,depth,summary)
            rejects(rows[:-4]);rejects(rows[:5]+rows[6:])
            for port,field in [('s','s_re'),('f','f_im'),('m','m_phase'),('m','m_last')]:
                bad=copy.deepcopy(rows);row=next(r for r in bad if r[port+'_valid'] and r[port+'_ready']);row[field]+=1;rejects(bad)
            for field,value in [('s_valid','x'),('s_ready',2),('configured',0),('level',999),('m_ready',2)]:
                bad=copy.deepcopy(rows);bad[3][field]=value;rejects(bad)
            for port,field in [('s','s_re'),('f','f_re'),('m','m_im')]:
                bad=copy.deepcopy(rows)
                for i,r in enumerate(bad[:-1]):
                    if r[port+'_valid'] and not r[port+'_ready']:
                        bad[i+1][field]+=1;break
                else:
                    # The minimum-depth source is intentionally never held.
                    if port=='s':continue
                    self.fail('Fixture did not reach hold '+port)
                rejects(bad)
            rejects(rows,log+log);rejects(rows,log.replace('peak=14','peak=15'));rejects(rows,log+'** Fatal: [NUMERIC] mismatch\n')

    def test_complete_matrix_and_counter_tampering(self):
        data=sweep.report();data['rtl_verified']=True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.csv'
            for load in sweep.loads():
                minimum=sweep.model(load)['minimum_depth']
                for depth in (minimum,minimum-1):
                    rows,log=fixture(load,depth);path.write_text(encode(rows));row=sweep.measured(path,load,depth,log)
                    data['rows'].extend(dict(row,active=a) for a in (0,1))
            data['negative']=[dict(active=a,tag=tag,returncode=13) for a in (0,1) for tag in ('NUMERIC','PHASE','CAPACITY','PROTOCOL')]
            data['lint']=[dict(depth=depth,active=a,warnings=0) for depth in {sweep.model(l)['minimum_depth']+o for l in sweep.loads() for o in (0,-1)} for a in (0,1)]
            sweep.check_acceptance(data)
            for key in ('rows','negative','lint'):
                bad=copy.deepcopy(data);bad[key].pop()
                with self.subTest(key=key),self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            for field,value in [('wait',1),('peak',999),('held_outputs',99),('active',True),('drained_cycle',9999)]:
                bad=copy.deepcopy(data);bad['rows'][0][field]=value
                with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            for code in (0,1,-31,True):
                bad=copy.deepcopy(data);bad['negative'][0]['returncode']=code
                with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            for key in ('negative','lint'):
                bad=copy.deepcopy(data);bad[key][0]['active']=False
                with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
            bad=copy.deepcopy(data);bad['rtl_verified']=False
            with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)

    def test_negatives_require_target_tag_and_exact_code13(self):
        for tag,target in [('NUMERIC','LOAD OUTPUT TARGET'),('PHASE','LOAD OUTPUT TARGET'),('CAPACITY','LOAD CAPACITY TARGET'),('PROTOCOL','LOAD HOLD TARGET')]:
            message='load Costas output: data changed while stalled' if tag=='PROTOCOL' else 'deliberate mismatch'
            good=f'{target} cycle=10\n** Fatal: [{tag}] {message}\n'
            sweep.checked_negative(good,13,tag)
            for code in (0,1,12,14,-31,True):
                with self.assertRaises(RuntimeError):sweep.checked_negative(good,code,tag)
            for text in (good.replace(target,'MISSING'),good.replace(tag,'WRONG'),good+'PASS FIFO LOAD',good.split('\n')[1]+'\n'+target):
                with self.assertRaises(RuntimeError):sweep.checked_negative(text,13,tag)
            if tag=='PROTOCOL':
                with self.assertRaises(RuntimeError):sweep.checked_negative(good.replace(message,'unrelated protocol fault'),13,tag)

    def test_explicit_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'existing';output.mkdir();marker=output/'keep';marker.write_text('original')
            run=subprocess.run([sys.executable,ROOT/'tools/fifo_load_sweep.py','--output',output],capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertIn('FileExistsError',run.stderr);self.assertEqual(marker.read_text(),'original')
            self.assertFalse((output/'results.json').exists())


if __name__=='__main__':unittest.main()
