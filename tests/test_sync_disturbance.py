"""Selected noise/fade trajectories, with controls and accepted-output evidence."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from sync_scenarios import costas_disturbance_scenario,costas_disturbance_metrics
from sync_cases import vectors
from sync_slip_evidence import check_costas_disturbances


class SyncDisturbance(unittest.TestCase):
    def test_named_disturbances_and_unperturbed_controls(self):
        for kind in ('noise_burst','fade_frequency_excursion'):
            with self.subTest(kind=kind):
                _,_,phases,metrics,reference,disabled=costas_disturbance_scenario(kind)
                self.assertTrue(all(metrics[name] for name in ('acquired','lost_mod90_lock',
                                     'relocked_mod90','adjacent_quadrant','disabled_rejected')))
                control=costas_disturbance_metrics(disabled,disabled,reference)
                self.assertFalse(control['acquired'])
                self.assertFalse(control['relocked_mod90'])
                _,_,_,clean,_,_=costas_disturbance_scenario(kind,disturbed=False)
                self.assertFalse(clean['lost_mod90_lock'])
                self.assertFalse(clean['adjacent_quadrant'])
                self.assertLess(clean['enabled_recovery_true_rms_deg'],1)

    def test_observed_trajectory_ranges_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            report=vectors(folder,transactions=1,seed=41)
            observed=folder/'observed.txt'
            body=(folder/'cl_out.txt').read_text().splitlines()[1:]
            observed.write_text('\n'.join(body)+'\n')
            result=check_costas_disturbances(folder,observed)
            self.assertEqual(set(result),{'noise_burst','fade_frequency_excursion'})
            for entry in report['cl_disturbances']:
                self.assertEqual(entry['row_stop']-entry['row_start'],1000)
                self.assertTrue(result[entry['kind']]['rtl_verified'])
            observed.write_text('\n'.join(body[:-1])+'\n')
            with self.assertRaisesRegex(RuntimeError,r'\[DISTURBANCE\].*incomplete'):
                check_costas_disturbances(folder,observed)

    def test_false_quadrant_correction_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);vectors(folder,transactions=1,seed=41)
            shifted=[]
            for line in (folder/'cl_out.txt').read_text().splitlines()[1:]:
                re,im,phase,last=map(int,line.split())
                phase=((phase+(1<<30)+(1<<31))%(1<<32))-(1<<31)
                shifted.append(f'{re} {im} {phase} {last}')
            observed=folder/'observed.txt';observed.write_text('\n'.join(shifted)+'\n')
            with self.assertRaisesRegex(RuntimeError,r'\[DISTURBANCE\]'):
                check_costas_disturbances(folder,observed)


if __name__=='__main__':unittest.main()
