"""Шлюзы приёмки RTL-исследования: покрытие сетки, слова, метрики и отрицательный контроль."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import run_costas_stream_acquisition as runner
from regression_evidence import begin, digest, require_pass, verify


class AcquisitionRTL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.reference = runner.load_reference(runner.REFERENCE)
        cls.trajectories = runner.prepare_vectors(cls.base / 'vectors', cls.reference)

    def test_vectors_cover_original_grid_and_use_original_quantizer(self):
        self.assertEqual(len(self.trajectories), 73)
        self.assertEqual(len({t.name for t in self.trajectories}), 73)
        for trajectory in self.trajectories:
            params = trajectory.parameters
            data, _, clipped = runner.study.signal(*(params[key] for key in runner.PARAMETERS[:4]))
            inputs = trajectory.folder.joinpath('cl_in.txt').read_text().splitlines()
            self.assertEqual(int(inputs[0]), 3072)
            self.assertEqual([tuple(map(int, row.split()[:2])) for row in inputs[1:]], data)
            self.assertEqual([int(row.split()[2]) for row in inputs[1:]], [0] * 3071 + [1])
            self.assertEqual(clipped, params['clipped_components'])
            self.assertEqual(len(trajectory.expected), 3072)
        control = self.trajectories[-1]
        self.assertEqual(control.folder.joinpath('cl_cfg.txt').read_text(), '0 0\n')
        self.assertEqual({row[2] for row in control.expected}, {0})

    def test_reference_rejects_partial_duplicate_grid_and_wrong_control(self):
        mutations = [lambda r: r['cases'].pop(),
                     lambda r: r['cases'].__setitem__(1, r['cases'][0]),
                     lambda r: r['zero_gain_control'].__setitem__('gains', [.08, .001]),
                     lambda r: r.__setitem__('samples', 1024),
                     lambda r: r.__setitem__('window', 64),
                     lambda r: r.__setitem__('delay_advances', 9)]
        path = self.base / 'invalid_reference.json'
        for mutate in mutations:
            reference = copy.deepcopy(self.reference)
            mutate(reference)
            path.write_text(json.dumps(reference))
            with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, 'REFERENCE'):
                runner.load_reference(path)

    def write_observed(self, rows):
        path = self.base / 'observed.txt'
        path.write_text(''.join(' '.join(map(str, row)) + '\n' for row in rows))
        return path

    def test_observed_words_and_metrics_equal_reference(self):
        # В положительном unit-тесте RTL заменён векторами; настоящий Questa запускается раннером.
        for trajectory in (self.trajectories[0], self.trajectories[-1]):
            phases = runner.check_observed(trajectory, self.write_observed(trajectory.expected))
            measured = runner.check_metrics(trajectory, phases)
            self.assertEqual(measured, trajectory.reference)

    def test_observed_rejects_corruption_of_each_word_field(self):
        trajectory = self.trajectories[0]
        for field in range(4):
            rows = list(trajectory.expected)
            word = list(rows[133])
            word[field] += 1
            rows[133] = tuple(word)
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'NUMERIC'):
                runner.check_observed(trajectory, self.write_observed(rows))

    def test_observed_rejects_truncation_extra_rows_and_malformed_rows(self):
        trajectory = self.trajectories[0]
        for rows in (trajectory.expected[:-1], trajectory.expected + [trajectory.expected[-1]]):
            with self.assertRaisesRegex(RuntimeError, 'COUNT'):
                runner.check_observed(trajectory, self.write_observed(rows))
        for row in ('0 0 x 0', '0 0 0', '0 0 0 2', '0 0 0 0 extra', ''):
            path = self.base / 'malformed.txt'
            path.write_text(row + '\n')
            with self.subTest(row=row), self.assertRaisesRegex(RuntimeError, 'FORMAT'):
                runner.check_observed(trajectory, path)

    def test_metrics_use_supplied_phases_and_require_all_fields(self):
        trajectory = copy.copy(self.trajectories[0])
        phases = [row[2] for row in trajectory.expected]
        with self.assertRaisesRegex(RuntimeError, 'METRICS'):
            runner.check_metrics(trajectory, [0] * len(phases))
        trajectory.reference = dict(trajectory.reference, mean_abs_folded_last_window_rad=999.)
        with self.assertRaisesRegex(RuntimeError, 'METRICS'):
            runner.check_metrics(trajectory, phases)

    def test_dense_requires_single_clean_complete_pass(self):
        text = ('COSTAS_STREAM backpressure hold checks: 0\n'
                'PASS COSTAS_STREAM: 3072 samples, 3072 outputs, run_max 3072, gap_max 0, '
                'out_gap_max 0, span 3071, cycles 3106')
        self.assertEqual(runner.check_dense(text, 3072)['outputs'], 3072)
        for bad in ('', text + '\n' + text, text + '\n** Error: failure',
                    text.replace('3072 outputs', '3071 outputs'),
                    text.replace('run_max 3072', 'run_max 3071'),
                    text.replace('gap_max 0', 'gap_max 1', 1),
                    text.replace('out_gap_max 0', 'out_gap_max 1'),
                    text.replace('span 3071', 'span 3072')):
            with self.subTest(text=bad), self.assertRaises(RuntimeError):
                runner.check_dense(bad, 3072)

    def test_numeric_negative_requires_exact_exit_and_expected_fatal(self):
        fatal = '** Fatal: [NUMERIC] costas_stream output'
        self.assertEqual(runner.check_negative(fatal, 13, 'NUMERIC', 'costas_stream output'),
                         {'status': 'PASS', 'vsim_exit_code': 13})
        for text, code in ((fatal, 0), (fatal, 1), (fatal, -11),
                           ('** Fatal: [NUMERIC] another scoreboard', 13)):
            with self.subTest(text=text, code=code), self.assertRaises(RuntimeError):
                runner.check_negative(text, code, 'NUMERIC', 'costas_stream output')

    def test_summary_matches_historical_counts(self):
        summary = runner.summarize(self.reference['cases'])
        self.assertEqual([r['cases'] for r in summary], [18] * 4)
        self.assertEqual([r['acquired'] for r in summary], [18, 18, 18, 14])
        self.assertEqual([r['tracking_at_end'] for r in summary], [18, 18, 17, 0])
        self.assertEqual([r['cases_with_quadrant_changes'] for r in summary], [0, 0, 0, 2])
        self.assertEqual([r['bad_windows_after_acquisition'] for r in summary], [0, 0, 10, 125])

    def test_failed_launch_saves_hashes_and_cannot_pass_acceptance(self):
        folder = self.base / 'failed_launch'
        folder.mkdir()
        log = folder / 'vsim.log'
        log.write_text('')
        evidence = begin()
        commands = [dict(argv=['vsim', '-version'], returncode=-31)]
        with self.assertRaisesRegex(RuntimeError, 'Command failed'):
            with runner.record_failure(folder, evidence, [log], commands,
                                       dict(positive_runs=0), 'reference-hash'):
                raise RuntimeError('Command failed (-31): vsim')
        result = json.loads((folder / 'acquisition_results.json').read_text())
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['progress']['positive_runs'], 0)
        self.assertEqual(result['artifact_hashes'][str(log)], digest(log))
        self.assertEqual(json.loads((folder / 'commands.json').read_text()), commands)
        verify(result)
        with self.assertRaisesRegex(RuntimeError, 'Complete passing'):
            require_pass(result)

    def test_existing_output_is_never_overwritten(self):
        folder = self.base / 'previous_evidence'
        folder.mkdir()
        witness = folder / 'acquisition_results.json'
        witness.write_text('previous evidence\n')
        with (patch.object(sys, 'argv', ['runner', '--output-dir', str(folder)]),
              patch.object(runner, 'questa_paths', return_value=(self.base, self.base))):
            with self.assertRaises(FileExistsError):
                runner.main()
        self.assertEqual(witness.read_text(), 'previous evidence\n')


if __name__ == '__main__':
    unittest.main()
