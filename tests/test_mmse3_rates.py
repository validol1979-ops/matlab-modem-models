"""Actual-cycle ledger checks, independent denominators and CLI rejection controls."""
import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import run_mmse3_rates as p
from regression_evidence import begin,finish,require_pass


def ledger(active=1,profile='identity'):
    """A tiny specified event ledger: 8 frames, 12 samples/frame, ready always1.

    Pin transfers are scheduled explicitly. Config has9 words; data21..116 shifted
    by192 clocks gives213..308; complete input triples produce output218..313.
    This supplies test data, not a fixed arithmetic model or a simulation claim.
    """
    rows=[]
    for c in range(2,336):
        cfg_valid=int(7<=c<=15);configured=int(c>=212)
        takes=list(range(213,309));pushes=list(range(217,311,3));pops=list(range(218,314))
        reserves=list(range(213,309,3))
        fifo=3*sum(k<c for k in pushes)-sum(k<c for k in pops)
        pending=sum(k<c for k in reserves)-sum(k<c for k in pushes)
        index=(c-213)%3 if 213<=c<=309 else 0
        last_input=min(c-214,95)
        frame_active=int(last_input>=0 and last_input%12!=11)
        state=1 if 16<=c<=24 else 2 if 25<=c<=33 else 3 if c==34 else 4 if 35<=c<=193 else 5 if 194<=c<=202 else 6 if 203<=c<=211 else 0
        p_valid=int(c in range(216,310,3));e_valid=int(c in pushes)
        cfg_count=c-7 if cfg_valid else 0
        cfg_ready=int(c>5 and state==0 and not frame_active and index==0 and fifo==0 and pending==0 and not p_valid and not e_valid)
        cfg_pair=p.configuration(profile)[c-7] if cfg_valid else (0,0)
        s_valid=int(c in takes);m_valid=int(fifo>0)
        s_pair=(c-213,-(c-213)) if s_valid else (0,0)
        serial=c-218
        if profile=='identity':m_pair=(serial,-serial) if m_valid else (0,0)
        else:
            base,component=3*(serial//3),serial%3
            m_pair=((base+1,-base-1),(-base-2,base+2),(-base,-base))[component] if m_valid else (0,0)
        row=dict(cycle=c,rst=active if c<=5 else 1-active,cfg_valid=cfg_valid,cfg_ready=cfg_ready,cfg_last=int(c==15),
                 cfg_re=cfg_pair[0],cfg_im=cfg_pair[1],cfg_lambda=0,configured=configured,error=0,
                 s_valid=s_valid,s_ready=configured,s_last=int(s_valid and (c-213)%12==11),s_re=s_pair[0],s_im=s_pair[1],
                 m_valid=m_valid,m_ready=1,m_last=int(m_valid and serial%12==11),m_re=m_pair[0],m_im=m_pair[1],
                 fifo=fifo,pending=pending,index=index,p_valid=p_valid,e_valid=e_valid,frame_active=frame_active,
                 cfg_count=cfg_count,cstate=state,capacity=16)
        rows.append(row)
    return rows


def write_trace(path,rows):
    with Path(path).open('w') as fd:
        writer=csv.DictWriter(fd,fieldnames=p.FIELDS);writer.writeheader();writer.writerows(rows)


class TestMmse3Rates(unittest.TestCase):
    def setUp(self):
        self.rows=ledger()

    def rejected_cli(self,rows):
        with tempfile.TemporaryDirectory() as directory:
            trace=Path(directory)/'trace.csv';write_trace(trace,rows)
            run=subprocess.run([sys.executable,str(ROOT/'tools/run_mmse3_rates.py'),'--analyze-trace',str(trace),
                '--length','12','--frames','8'],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('[RATE]',run.stderr)
            self.assertNotIn('PASS MMSE3',run.stdout)

    def test_sample_vector_frame_denominators_and_corresponding_latency(self):
        result=p.analyze_rows(self.rows,'identity',1,'ready',12,8)
        self.assertEqual(result['input']['samples'],96)
        self.assertEqual(result['input']['vectors'],32)
        self.assertEqual(result['input']['frames'],8)
        central=result['input']['central_period']
        self.assertEqual((central['cycles'],central['samples'],central['vectors'],central['frames']),(48,48,16,4))
        self.assertEqual(central['samples_per_cycle'],1)
        self.assertEqual(central['vectors_per_cycle'],1/3)
        self.assertEqual(central['frames_per_cycle'],1/12)
        self.assertEqual(result['full_first_input_to_last_output']['cycles'],101)
        self.assertEqual(result['full_first_input_to_last_output']['output_samples_per_cycle'],96/101)
        self.assertEqual(result['vector_latency']['last_input_to_first_output_min'],3)
        self.assertEqual(result['vector_latency']['last_input_to_last_output_max'],5)
        self.assertEqual(result['configuration']['last_word_to_configured_cycles'],197)
        self.assertEqual(result['sampled_reset_cycles'],4)

    def test_both_polarities_and_independent_unitary_matrix_mapping(self):
        for active in (1,0):
            for profile in p.PROFILES:
                result=p.analyze_rows(ledger(active,profile),profile,active,'ready',12,8)
                self.assertEqual(result['output']['samples'],96)
                h=np.asarray([complex(re,im)/32768 for re,im in p.configuration(profile)]).reshape(3,3)
                np.testing.assert_array_equal(h.conj().T@h,np.eye(3))
                observation=np.asarray([complex(15,-15),complex(16,-16),complex(17,-17)])
                expected=np.linalg.inv(h)@observation
                np.testing.assert_array_equal(expected,[complex(*p.output_pair(k,profile)) for k in (15,16,17)])

    def test_count_fault_nonzero_no_pass(self):
        next(r for r in self.rows if r['cycle']==308)['s_valid']=0
        self.rejected_cli(self.rows)

    def test_drop_fault_with_renumbered_cycles_nonzero_no_pass(self):
        del self.rows[248]
        for k,row in enumerate(self.rows):row['cycle']=k+2
        self.rejected_cli(self.rows)

    def test_duplicate_transfer_with_renumbered_cycles_nonzero_no_pass(self):
        self.rows.insert(249,copy.deepcopy(self.rows[248]))
        for k,row in enumerate(self.rows):row['cycle']=k+2
        self.rejected_cli(self.rows)

    def test_cycle_fault_nonzero_no_pass(self):
        self.rows[250]['cycle']+=1
        self.rejected_cli(self.rows)

    def test_reset_fault_nonzero_no_pass(self):
        self.rows[250]['rst']=1
        self.rejected_cli(self.rows)

    def test_cfg_output_pending_and_hold_faults_rejected(self):
        for field,value,cycle in [('cfg_re',0,7),('m_re',-1,250),('pending',5,250),('s_valid',0,250),('p_valid',0,216),('capacity',17,250)]:
            rows=ledger();next(r for r in rows if r['cycle']==cycle)[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):p.analyze_rows(rows,'identity',1,'ready',12,8)
        rows=ledger();row=next(r for r in rows if r['cycle']==250);row['m_ready']=0
        with self.assertRaises(ValueError):p.analyze_rows(rows,'identity',1,'ready',12,8)

    def test_stored_count_or_rate_poison_recomputed_from_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace=Path(directory)/'trace.csv';write_trace(trace,self.rows)
            original=p.analyze(trace,'identity',1,'ready',12,8)
            record=dict(specification=dict(profile='identity',reset_active=1,mode='ready',length=12,frames=8),trace=str(trace),metrics=original)
            p.validate_record(record)
            for key in ('samples','vectors','frames'):
                broken=copy.deepcopy(record);broken['metrics']['input'][key]-=1
                with self.subTest(key=key),self.assertRaises(ValueError):p.validate_record(broken)
            broken=copy.deepcopy(record);broken['metrics']['output']['central_period']['samples_per_cycle']=.5
            with self.assertRaises(ValueError):p.validate_record(broken)

    def test_timeout_group_stopped_and_log_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'timeout.log'
            with self.assertRaisesRegex(RuntimeError,'subprocess timeout'):
                p.run_command([sys.executable,'-c','import time; time.sleep(5)'],ROOT,log,timeout=.05)
            self.assertIn('[RATE] subprocess timeout',log.read_text())

    def test_failed_run_and_optimized_cli_overwrite_stale_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'results.json';target.write_text('{"status":"PASS"}')
            with patch.object(p,'run_command',side_effect=RuntimeError('forced subprocess failure')),self.assertRaises(RuntimeError):
                p.main(['--suite','hdl','--output',directory])
            self.assertEqual(json.loads(target.read_text())['status'],'FAIL')
            run=subprocess.run([sys.executable,'-O',str(ROOT/'tools/run_mmse3_rates.py'),'--suite','hdl','--output',directory],
                               capture_output=True,text=True,timeout=10)
            self.assertNotEqual(run.returncode,0)
            self.assertEqual(json.loads(target.read_text())['status'],'FAIL')
            self.assertNotIn('PASS MMSE3',run.stdout)

    def test_source_artifact_freshness_excludes_stale_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace=Path(directory)/'trace.csv';write_trace(trace,self.rows)
            evidence=dict(finish(begin(),[trace]),status='PASS');require_pass(evidence)
            with trace.open('a') as fd:fd.write('corrupt\n')
            with self.assertRaisesRegex(RuntimeError,'Stale regression artifact'):require_pass(evidence)
            stale=copy.deepcopy(evidence);stale['source_hashes']['tools/run_mmse3_rates.py']='0'*64
            with self.assertRaises(RuntimeError):require_pass(stale)


if __name__=='__main__':unittest.main(verbosity=2)
