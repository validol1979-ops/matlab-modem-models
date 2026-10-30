"""Регрессионные проверки замечаний: свидетельства, импорты, входы и отрицательные контроли."""
from pathlib import Path
import importlib.util
import io
import json
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'common/python')]
from regression_evidence import begin,finish,verify,require_pass,require_numeric_failure,mquote,questa_paths
from research_core import run
from modem_core import fit_carrier
from check_contracts import fixtures


class RegressionGuards(unittest.TestCase):
    def test_evidence_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'common').mkdir();source=root/'common/model.py';source.write_text('x=1\n')
            evidence=finish(begin(root),root=root);verify(evidence,root)
            source.write_text('x=2\n')
            with self.assertRaisesRegex(RuntimeError,'Stale'):verify(evidence,root)
            with self.assertRaisesRegex(RuntimeError,'Stale'):finish(evidence,root=root)

    def test_evidence_rejects_changed_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'common').mkdir();(root/'common/model.py').write_text('x=1\n')
            log=root/'result.log';log.write_text('PASS')
            evidence=finish(begin(root),[log],root);log.write_text('FAIL')
            with self.assertRaisesRegex(RuntimeError,'artifact'):verify(evidence,root)

    def test_report_requires_completed_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'common').mkdir();(root/'common/model.py').write_text('x=1')
            evidence=begin(root)
            for status in ('RUNNING','FAIL','PASS'):
                with self.assertRaisesRegex(RuntimeError,'Complete'):
                    require_pass(dict(evidence,status=status),root)
            require_pass(dict(finish(evidence,root=root),status='PASS'),root)

    def test_typed_report_rejects_every_unfinished_input(self):
        import report_typed_results
        names=['build/all_results.json','build/typed/all_results.json','build/typed/matlab_results.json',
               'build/typed/originals/matlab_results.json','build/typed/originals/python_results.json',
               'build/contracts/all_results.json','build/contracts/matlab_results.json','build/typed_browser/results.json']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'common').mkdir();(root/'common/model.py').write_text('x=1')
            evidence=dict(finish(begin(root),root=root),status='PASS')
            for name in names+['docs/typed_model_catalog.json','docs/typed_visual/report_data.json']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(evidence))
            for name in names:
                (root/name).write_text(json.dumps(dict(evidence,status='RUNNING')))
                with self.subTest(name=name),patch.object(report_typed_results,'ROOT',root),self.assertRaisesRegex(RuntimeError,'Complete'):
                    report_typed_results.main()
                (root/name).write_text(json.dumps(evidence))
            self.assertFalse((root/'docs/typed_verification_results.json').exists())

    def test_external_artifact_can_be_verified(self):
        with tempfile.TemporaryDirectory() as tmp,tempfile.TemporaryDirectory() as outside:
            root=Path(tmp);(root/'common').mkdir();(root/'common/model.py').write_text('x=1')
            log=Path(outside)/'result.log';log.write_text('PASS')
            evidence=finish(begin(root),[log],root);verify(evidence,root)
            log.write_text('FAIL')
            with self.assertRaisesRegex(RuntimeError,'artifact'):verify(evidence,root)

    def test_verification_commands_reject_optimization(self):
        for name in ('check_matlab_msk.py','report_typed_results.py','report_matlab_originals.py',
                     'visual_report.py','typed_visual_report.py','check_visual_browser.py',
                     'check_typed_browser.py','check_research_references.py'):
            with self.subTest(name=name):
                result=subprocess.run([sys.executable,'-O',str(ROOT/'tools'/name)],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('without Python optimization',result.stderr)

    def test_questa_launcher_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'questa';(home/'bin').mkdir(parents=True);(home/'vco').write_text('launcher')
            (home/'bin/vsim').symlink_to('../vco');link=Path(tmp)/'vsim';link.symlink_to(home/'bin/vsim')
            with patch('regression_evidence.shutil.which',return_value=str(link)),patch.dict('os.environ',{},clear=True):
                self.assertEqual(questa_paths()[0],home/'bin')

    def test_invalid_modem_configuration(self):
        from modem_core import load_config,validate_config
        cfg=load_config(ROOT/'modems/bpsk_costas_2008_08_25/config.json')
        for change in ({'differential':'quadrant'}, {'differential':'pi4'}, {'family':'oqpsk'}, {'family':'gmsk','order':4}, {'rolloff':float('nan')}):
            with self.subTest(change=change),self.assertRaises(ValueError): validate_config(dict(cfg,**change))

    def test_report_rejects_stale_test_evidence(self):
        import report_results
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'common').mkdir();source=root/'common/model.py';source.write_text('x=1\n')
            evidence=finish(begin(root),root=root)
            records={'modems/catalog.json':[{'name':'demo'}],
                     'build/python_results.json':dict(evidence,status='PASS',modems=1,python_tests=1),
                     'build/cross_results.json':dict(evidence,status='PASS',modems=1),
                     'build/questa/results.json':[dict(evidence,status='PASS',modem='demo')]}
            for name,value in records.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            source.write_text('raise RuntimeError("Untested")\n')
            with patch.object(report_results,'ROOT',root),self.assertRaisesRegex(RuntimeError,'Stale'):report_results.main()
            self.assertFalse((root/'docs/verification_results.json').exists())

    def test_typed_import_is_passive_and_discoverable(self):
        paths=list((ROOT/'algorithms').glob('*/*/tests/test_model.py'))+list((ROOT/'modems').glob('*/tests/test_model.py'))
        self.assertEqual(len(paths),13)
        for index,path in enumerate(paths):
            with self.subTest(path=str(path)),patch('subprocess.run') as launch:
                spec=importlib.util.spec_from_file_location(f'guard_model_{index}',path)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                launch.assert_not_called()
                self.assertEqual(unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases(),1)

    def test_uvm_summary_is_not_a_failure_message(self):
        for text in ('UVM_FATAL : 0','UVM_INFO [NUMERIC] passed\nUVM_FATAL : 0','UVM_FATAL [INPUT] missing\nUVM_FATAL : 1'):
            with self.subTest(text=text),self.assertRaises(RuntimeError):require_numeric_failure(text)
        require_numeric_failure('UVM_FATAL file.sv(12) @ 0: [NUMERIC] mismatch\nUVM_FATAL : 1')

    def test_input_contract_boundaries(self):
        for accepted,(name,op,p,x,a) in fixtures():
            with self.subTest(case=name):
                if accepted:self.assertTrue(np.all(np.isfinite(run(op,p,x,a))))
                else:
                    with self.assertRaises(ValueError):run(op,p,x,a)
        for op,p,x,a in [(1.5,[0],[1],[]),(-1,[],[1],[]),('dft',[0],[np.nan],[]),('dft',[np.inf],[1],[]),('dft',[1j],[1],[])]:
            with self.assertRaises(ValueError):run(op,p,x,a)

    def test_zero_carrier_reference_is_rejected(self):
        with self.assertRaises(ValueError):fit_carrier(np.ones(4),np.array([1,0,1,1]))
        with self.assertRaises(ValueError):fit_carrier(np.zeros(4),np.ones(4))
        with self.assertRaises(ValueError):fit_carrier(np.ones(4),np.array([1,1e-170,1,1]))

    def test_m_path_quoting(self):
        self.assertEqual(mquote(Path("/tmp/owner's models/vectors.txt")),"/tmp/owner''s models/vectors.txt")

if __name__=='__main__':unittest.main()
