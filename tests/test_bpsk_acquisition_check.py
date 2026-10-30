"""Acceptance gates for the Verilator adapter, without simulator execution."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import bpsk_verilator as v
from bpsk_acquire_review import (ACQUIRE_SCENARIOS, checked_acquire, checked_divide,
                                 checked_divide_negative, divider_counts)
from bpsk_cases import generate, b
from run_bpsk import numeric_negative


class VerilatorAcceptance(unittest.TestCase):
    def test_negative_requires_numeric_fatal_and_abort(self):
        text='%Fatal: bench.sv:1: [NUMERIC] corrupted expectation\n'
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'negative.log'
            for code,output in [(1,text),(-6,text),(134,text)]:
                with patch.object(v.subprocess,'run',return_value=subprocess.CompletedProcess([],code,output,'')):
                    self.assertEqual(v.command(['sim'],folder,log,negative=True),text)
            for code,output in [(0,text),(2,text),(-31,text),(-6,'[NUMERIC] no fatal'),
                                (-6,text.replace('NUMERIC','TIMEOUT')),
                                *[(-6,text+marker) for marker in ('PASS BPSK receiver:', 'PASS BPSK direct acquisition:',
                                                                 'PASS ACQUIRE SCENARIO', 'PASS BPSK divider modes:', 'PASS DIVIDE BOUNDARIES')]]:
                with self.subTest(code=code,output=output),patch.object(v.subprocess,'run',return_value=subprocess.CompletedProcess([],code,output,'')):
                    with self.assertRaises(RuntimeError):v.command(['sim'],folder,log,negative=True)

    def test_build_preserves_scoreboard_and_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);bench=root/'bench.sv'
            bench.write_text('import uvm_pkg::*;\n`include "uvm_macros.svh"\nif(actual!==expected) `uvm_fatal("NUMERIC","mismatch")\n')
            with patch.object(v,'command') as run:
                exe=v.build(root/'build','bench',[bench],dict(RESET_ACTIVE=0))
                self.assertEqual(exe,root/'build/obj/sim')
                self.assertIn('--assert',run.call_args.args[0])
                self.assertIn('-GRESET_ACTIVE=0',run.call_args.args[0])
                self.assertIn('if(actual!==expected)',(root/'build/bench.sv').read_text())
                self.assertIn('$fatal', (root/'build/uvm_macros.svh').read_text())
                with self.assertRaises(FileExistsError):v.build(root/'build','bench',[bench])


class StateCoverageAcceptance(unittest.TestCase):
    @staticmethod
    def acquisition_log(scenario, count=2, negative=False):
        hits=0 if scenario=='baseline' else (1 if negative else count)
        text=''.join(f'ACQUIRE TARGET scenario={scenario} case={j} state=7 div=1 score=1 replay=1\n' for j in range(hits))
        if negative:return text+'UVM_FATAL @ 1: reporter [NUMERIC] mismatch\nUVM_FATAL : 1\n'
        text+=''.join(f'PASS DIRECT ACQUISITION case={j} repeat={k} A=677\n' for j in range(count) for k in range(2))
        if scenario=='busy_start':
            text+=''.join(f'ACQUIRE BUSY START case={j} pulsed_latency=676 clean_latency=676\n' for j in range(count))
        return text+f'PASS ACQUIRE SCENARIO {scenario}: reached={hits} exact={2*count} divisor_checks={8*count}\nPASS BPSK direct acquisition: {count} exact results\n'

    def test_every_state_and_exact_result_is_required(self):
        for scenario in ACQUIRE_SCENARIOS:
            good=self.acquisition_log(scenario)
            with self.subTest(scenario=scenario):
                self.assertEqual(checked_acquire(good,scenario,2)['exact_results'],4)
                for bad in (good+good,good.replace('repeat=1','repeat=0'),good.replace('exact=4','exact=3'),
                            good.replace('divisor_checks=16','divisor_checks=0'),good+'%Fatal: [PROTOCOL] extra done',
                            good.replace('PASS BPSK direct','FAIL BPSK direct')):
                    with self.assertRaises(RuntimeError):checked_acquire(bad,scenario,2)
                if scenario!='baseline':
                    for bad in (good.replace('ACQUIRE TARGET','MISSING'),good.replace('case=1 state','case=0 state'),
                                good.replace('state=7','state=0')):
                        with self.assertRaises(RuntimeError):checked_acquire(bad,scenario,2)
                key={'reset_div':'div','busy_start':'div','reset_score':'score','reset_replay':'replay'}.get(scenario)
                if key:
                    with self.assertRaises(RuntimeError):checked_acquire(good.replace(f'{key}=1',f'{key}=0'),scenario,2)
                if scenario=='busy_start':
                    for bad in (good.replace('ACQUIRE BUSY START','MISSING'),good.replace('clean_latency=676','clean_latency=677')):
                        with self.assertRaises(RuntimeError):checked_acquire(bad,scenario,2)

    def test_acquisition_negative_requires_reaching_state_and_code_13(self):
        with tempfile.TemporaryDirectory() as folder:
            for scenario in ACQUIRE_SCENARIOS:
                fatal=self.acquisition_log(scenario,negative=True)
                checked_acquire(fatal,scenario,2,negative=True)
                if scenario!='baseline':
                    with self.assertRaises(RuntimeError):checked_acquire(fatal.split('\n',1)[1],scenario,2,negative=True)
                for marker in ('PASS ACQUIRE SCENARIO','PASS BPSK direct acquisition:'):
                    with self.assertRaises(RuntimeError):checked_acquire(fatal+marker,scenario,2,negative=True)
                for code in (0,1,2,12,14,-6,-31,13):
                    with self.subTest(scenario=scenario,code=code),patch('run_bpsk.subprocess.run',return_value=subprocess.CompletedProcess([],code,fatal,'')):
                        if code==13:
                            self.assertEqual(numeric_negative(['vsim'],folder,Path(folder)/'negative.log','PASS BPSK direct acquisition:')['returncode'],13)
                        else:
                            with self.assertRaises(RuntimeError):numeric_negative(['vsim'],folder,Path(folder)/'negative.log','PASS BPSK direct acquisition:')

    def test_divider_unsigned_endpoints_and_invalid_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);counts=generate(path);endpoints=divider_counts(path/'divide.txt')
            self.assertEqual(counts['divide'],3089)
            self.assertEqual(endpoints,dict(all=3089,one=14,max=11))
            rows=[tuple(map(int,row.split())) for row in (path/'divide.txt').read_text().splitlines()[1:]]
            for d in (1,2**32-1):
                selected=[(n,q) for n,den,q in rows if den==d]
                self.assertTrue({-2**63,2**63-1,0,1,-1}.issubset({n for n,_ in selected}))
                for n,q in selected:self.assertEqual(q,b.divide(n,d))
            self.assertTrue(all(d>0 for _,d,_ in rows))
            with self.assertRaises((ValueError,ZeroDivisionError)):b.divide(1,0)

    def test_divider_requires_each_endpoint_and_both_modes(self):
        counts=dict(all=3089,one=14,max=11)
        for scenario,one,maximum in [('all',14,11),('one',14,0),('max',0,11)]:
            good=f'PASS DIVIDE BOUNDARIES scenario={scenario} one={one} max={maximum} modes=1,2\nPASS BPSK divider modes: {counts[scenario]} exact results, latency=66/34\n'
            self.assertEqual(checked_divide(good,scenario,counts)['steps_per_cycle'],[1,2])
            for bad in (good+good,good.replace('modes=1,2','modes=2'),good.replace('66/34','66/35'),
                        good.replace(f'one={one}',f'one={one+1}'),good.replace(f'max={maximum}',f'max={maximum+1}'),
                        good+'UVM_FATAL [NUMERIC] mismatch'):
                with self.assertRaises(RuntimeError):checked_divide(bad,scenario,counts)

    def test_divider_negative_requires_target_denominator_and_mode(self):
        for scenario,d in [('one',1),('max',2**32-1)]:
            for mode in (1,2):
                good=f'DIVIDE TARGET scenario={scenario} denominator={d} modes=1,2\nUVM_FATAL @ 1: reporter [NUMERIC] divider scenario={scenario} row=0 d={d} mode={mode}\nUVM_FATAL : 1\n'
                checked_divide_negative(good,scenario,mode)
                for bad in (good.replace('DIVIDE TARGET','MISSING'),good.replace(f'mode={mode}',f'mode={3-mode}'),
                            good.replace(f'denominator={d}','denominator=0'),good+'PASS BPSK divider modes:'):
                    with self.assertRaises(RuntimeError):checked_divide_negative(bad,scenario,mode)


if __name__=='__main__':unittest.main()
