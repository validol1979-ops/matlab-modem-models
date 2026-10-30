"""Endpoint proofs for every stored-operand code in configuration expressions."""
from itertools import product
import copy
from pathlib import Path
import random
import subprocess
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import mmse3_config_widths as widths
import mmse3_fixed as fixed
sys.path.insert(0, str(ROOT/'tools'))
import mmse3_config_width_sweep as sweep


class TestMmse3ConfigWidths(unittest.TestCase):
    def fits(self, value, bits):
        self.assertGreaterEqual(value, -(1 << (bits-1)))
        self.assertLess(value, 1 << (bits-1))

    def check_terms(self, terms, entry, bits):
        total = 0
        for index, (term, sign) in enumerate(zip(terms, entry['signs'])):
            self.assertLessEqual(entry['product']['minimum'], term)
            self.assertLessEqual(term, entry['product']['maximum'])
            self.fits(term, bits)
            signed = sign*term
            self.fits(signed, bits)
            self.assertLessEqual(entry['signed_terms'][index]['minimum'], signed)
            self.assertLessEqual(signed, entry['signed_terms'][index]['maximum'])
            total += signed
            self.fits(total, bits)
            self.assertLessEqual(entry['prefixes'][index]['minimum'], total)
            self.assertLessEqual(total, entry['prefixes'][index]['maximum'])
        # RTL determinant/mentry += evaluates a two-product RHS before adding
        # to the accumulator. Check each such RHS as well as scalar prefixes.
        if len(terms) == 6:
            for index in (0, 2, 4):
                self.fits(terms[index]*entry['signs'][index]+
                          terms[index+1]*entry['signs'][index+1], bits)
        return total

    def test_layout_exact_extrema_and_minimal_widths(self):
        bounds = widths.layout()
        g, a, h = 1 << 39, 1 << 83, 1 << 17
        self.assertEqual(bounds['stored'], {'gram': 40, 'adj': 84, 'det': 128, 'm': 106})
        self.assertEqual([bounds[k]['required_bits'] for k in ('adj', 'det', 'm')],
                         [81, 126, 104])
        expected = {
            ('adj', 'real'): (-4*g*g+2*g, 4*g*g-2*g),
            ('adj', 'imag'): (-4*g*g+2*g, 4*g*g-2*g),
            ('det', 'real'): (-6*g*a+3*g, 6*g*a-3*g),
            ('det', 'imag'): (-6*g*a+6*g, 6*g*a),
            ('m', 'real'): (-6*a*h+6*h, 6*a*h),
            ('m', 'imag'): (-6*a*h+3*h, 6*a*h-3*h),
        }
        for (kind, axis), (low, high) in expected.items():
            entry = bounds[kind][axis]
            bits = bounds[kind]['required_bits']
            self.assertEqual((entry['minimum'], entry['maximum']), (low, high))
            self.fits(low, bits)
            self.fits(high, bits)
            # A witnessed scalar result lies outside the next narrower signed
            # interval: sufficiency alone would not establish minimality.
            self.assertTrue(low < -(1 << (bits-2)) or high >= 1 << (bits-2))
            if kind == 'adj':
                self.assertEqual((entry['odd_negated']['minimum'],
                                  entry['odd_negated']['maximum']), (low, high))

    def test_all_256_adjugate_corners_all_entries_prefixes_and_parities(self):
        limit = 1 << 39
        bounds = widths.layout()['adj']
        extrema = [[[None, None] for _ in range(2)] for _ in range(2)]
        for corner in product((-limit, limit-1), repeat=8):
            x, y, z, t = [corner[i:i+2] for i in (0, 2, 4, 6)]
            terms = ((x[0]*y[0], x[1]*y[1], z[0]*t[0], z[1]*t[1]),
                     (x[0]*y[1], x[1]*y[0], z[0]*t[1], z[1]*t[0]))
            totals = [self.check_terms(terms[axis], bounds[name], 81)
                      for axis, name in enumerate(('real', 'imag'))]
            for row, col in product(range(3), repeat=2):
                ra, rb = [i for i in range(3) if i != col]
                ca, cb = [i for i in range(3) if i != row]
                g = [(0, 0)]*9
                for index, pair in zip((3*ra+ca, 3*rb+cb, 3*ra+cb, 3*rb+ca),
                                       (x, y, z, t)):
                    g[index] = pair
                parity = (row+col) % 2
                observed = widths.adjugate(g)[3*row+col]
                self.assertEqual(observed, tuple((-1 if parity else 1)*v for v in totals))
                for axis in range(2):
                    self.fits(observed[axis], 81)
                    low, high = extrema[parity][axis]
                    extrema[parity][axis] = [observed[axis] if low is None else min(low, observed[axis]),
                                            observed[axis] if high is None else max(high, observed[axis])]
        for parity, axis in product(range(2), repeat=2):
            entry = bounds[('real', 'imag')[axis]]
            self.assertEqual(extrema[parity][axis], [entry['minimum'], entry['maximum']])

    def test_all_4096_determinant_corners_and_prefixes(self):
        gmax, amax = 1 << 39, 1 << 83
        bounds = widths.layout()['det']
        extrema = [[None, None], [None, None]]
        for corner in product((0, 1), repeat=12):
            gvalues = [(-gmax, gmax-1)[v] for v in corner[:6]]
            avalues = [(-amax, amax-1)[v] for v in corner[6:]]
            gpairs = list(zip(gvalues[::2], gvalues[1::2]))
            apairs = list(zip(avalues[::2], avalues[1::2]))
            g, a = [(0, 0)]*9, [(0, 0)]*9
            terms = ([], [])
            for k, ((gr, gi), (ar, ai)) in enumerate(zip(gpairs, apairs)):
                g[k], a[3*k] = (gr, gi), (ar, ai)
                terms[0].extend((gr*ar, gi*ai))
                terms[1].extend((gr*ai, gi*ar))
            totals = [self.check_terms(terms[axis], bounds[name], 126)
                      for axis, name in enumerate(('real', 'imag'))]
            self.assertEqual(widths.determinant(g, a), tuple(totals))
            for axis, total in enumerate(totals):
                low, high = extrema[axis]
                extrema[axis] = [total if low is None else min(low, total),
                                 total if high is None else max(high, total)]
        for axis, name in enumerate(('real', 'imag')):
            self.assertEqual(extrema[axis], [bounds[name]['minimum'], bounds[name]['maximum']])

    def test_all_4096_m_corners_and_prefixes(self):
        amax, hmax = 1 << 83, 1 << 17
        bounds = widths.layout()['m']
        extrema = [[None, None], [None, None]]
        for corner in product((0, 1), repeat=12):
            av = [(-amax, amax-1)[v] for v in corner[:6]]
            hv = [(-hmax, hmax-1)[v] for v in corner[6:]]
            apairs = list(zip(av[::2], av[1::2]))
            hpairs = list(zip(hv[::2], hv[1::2]))
            terms = ([], [])
            for (ar, ai), (hr, hi) in zip(apairs, hpairs):
                terms[0].extend((ar*hr, ai*hi))
                terms[1].extend((ai*hr, ar*hi))
            totals = [self.check_terms(terms[axis], bounds[name], 104)
                      for axis, name in enumerate(('real', 'imag'))]
            # Replication covers every row/col indexing route in one call.
            self.assertEqual(widths.mentry(apairs*3, hpairs*3), [tuple(totals)]*9)
            for axis, total in enumerate(totals):
                low, high = extrema[axis]
                extrema[axis] = [total if low is None else min(low, total),
                                 total if high is None else max(high, total)]
        for axis, name in enumerate(('real', 'imag')):
            self.assertEqual(extrema[axis], [bounds[name]['minimum'], bounds[name]['maximum']])

    def test_integer_matrix_reference_and_raw_banks(self):
        rng = random.Random(3484106)
        for _ in range(40):
            h = [(rng.randrange(-131072, 131072), rng.randrange(-131072, 131072))
                 for _ in range(9)]
            lam = rng.randrange(1, 1 << 34)
            values = widths.trace(h, lam)
            g = values['gram']
            cofactors = []
            for row, col in product(range(3), repeat=2):
                ra, rb = [i for i in range(3) if i != row]
                ca, cb = [i for i in range(3) if i != col]
                left = fixed._mul(g[3*ra+ca], g[3*rb+cb])
                right = fixed._mul(g[3*ra+cb], g[3*rb+ca])
                sign = -1 if (row+col) % 2 else 1
                cofactors.append(tuple(sign*(x-y) for x, y in zip(left, right)))
            self.assertEqual(values['adj'], [cofactors[3*c+r] for r, c in product(range(3), repeat=2)])
            self.assertEqual(values['det'], fixed._sum(fixed._mul(g[k], cofactors[k]) for k in range(3)))
            self.assertEqual(values['m'], [fixed._sum(fixed._mul(cofactors[3*k+r], fixed._conj(h[3*c+k]))
                                                       for k in range(3))
                                           for r, c in product(range(3), repeat=2)])
            self.assertEqual(values['det'][1], 0)
            self.assertGreater(values['det'][0], 0)
            banks = widths.banks(values)
            self.assertEqual([b['name'] for b in banks],
                             ['adj_re', 'adj_im', 'det_re', 'det_im', 'm_re', 'm_im'])
            self.assertEqual([b['count'] for b in banks], [9, 9, 1, 1, 9, 9])
            for bank in banks:
                kind = bank['name'].split('_')[0]
                pair_list = [values[kind]] if kind == 'det' else values[kind]
                components = [v[bank['name'].endswith('im')] for v in pair_list]
                self.assertEqual((bank['min'], bank['max']), (min(components), max(components)))
                self.fits(bank['min'], widths.layout()[kind]['required_bits'])
                self.fits(bank['max'], widths.layout()[kind]['required_bits'])

    def test_arbitrary_matrix_reference_and_operand_domain_validation(self):
        rng = random.Random(408418)
        for _ in range(12):
            g = [(rng.randrange(-(1 << 39), 1 << 39), rng.randrange(-(1 << 39), 1 << 39)) for _ in range(9)]
            a = [(rng.randrange(-(1 << 83), 1 << 83), rng.randrange(-(1 << 83), 1 << 83)) for _ in range(9)]
            h = [(rng.randrange(-(1 << 17), 1 << 17), rng.randrange(-(1 << 17), 1 << 17)) for _ in range(9)]
            self.assertEqual(widths.determinant(g, a), fixed._sum(fixed._mul(g[k], a[3*k]) for k in range(3)))
            self.assertEqual(widths.mentry(a, h), [fixed._sum(fixed._mul(a[3*r+k], fixed._conj(h[3*c+k]))
                                                              for k in range(3)) for r, c in product(range(3), repeat=2)])
        for bad in ([((1 << 39), 0)]*9, [(False, 0)]*9, [(0.0, 0)]*9, [(0, 0)]*8):
            with self.assertRaises(ValueError):
                widths.adjugate(bad)
        with self.assertRaises(ValueError):
            widths.determinant([(0, 0)]*9, [(1 << 83, 0)]*9)
        with self.assertRaises(ValueError):
            widths.mentry([(0, 0)]*9, [(1 << 17, 0)]*9)
        with self.assertRaises(ValueError):
            widths.trace([(0, 0)]*9, 1 << 34)


class TestMmse3ConfigEvidence(unittest.TestCase):
    """Synthetic complete matrices verify acceptance, without claiming RTL runs."""
    @classmethod
    def setUpClass(cls):
        cls.model = sweep.report()
        cls.complete = copy.deepcopy(cls.model)
        cls.complete['rtl_verified'] = True
        for source,target,active,scenario in product(cls.model['records'],sweep.LAYOUTS,(1,0),sweep.SCENARIOS):
            banks = sweep.scaled_banks(source,sweep.configurations(scenario))
            counts = [b['count'] for b in banks]
            cls.complete['rtl_equivalence'].append(dict(
                case=source['case'],layout=target[0],active=active,scenario=scenario,
                widths=list(target[1:]),outputs=source['outputs'],cycles=500,
                observers_verified=True,epochs=sweep.epochs(scenario),configs=sweep.configurations(scenario),
                banks=banks,adj_checks=sum(counts[:2]),det_checks=sum(counts[2:4]),
                m_checks=sum(counts[4:]),total_checks=sum(counts)))
        cls.complete['rtl_frozen'] = [dict(case=s['case'],active=a,scenario=scenario,
                                          old_outputs=s['outputs'],new_outputs=s['outputs'],
                                          old_cycles=500,new_cycles=500)
                                     for s,a,scenario in product(cls.model['records'],(1,0),sweep.SCENARIOS)]
        cls.complete['rtl_directed'] = [dict(layout=l[0],active=a,passed=True,widths=list(l[1:]),
                                            epochs=1,configs=1,banks=sweep.directed_banks(),
                                            total_checks=sum(sweep.DIRECTED_COUNTS.values()),**sweep.DIRECTED_COUNTS)
                                       for l,a in product(sweep.LAYOUTS,(1,0))]
        cls.complete['rtl_parameters'] = [dict(layout=l[0],active=a,returncode=13)
                                         for l,a in product(sweep.INVALID,(1,0))]
        cls.complete['rtl_negative'] = [dict(bench=b,tag=t,active=a,returncode=13)
                                       for b,t,a in product(('stream','directed'),sweep.TAGS,(1,0))]
        cls.complete['rtl_lint'] = [dict(layout=l[0],warnings=0) for l in sweep.LAYOUTS]

    def reject(self, result):
        with self.assertRaises((RuntimeError, KeyError, TypeError, ValueError)):
            sweep.check_acceptance(result)

    def test_model_and_complete_acceptance_and_exact_coverage_sizes(self):
        sweep.check_acceptance(self.model)
        sweep.check_acceptance(self.complete)
        self.assertEqual([r['case'] for r in self.model['records']],list(sweep.CASES))
        self.assertEqual([len(self.complete[k]) for k in sweep.SECTIONS],[450,90,12,10,12,5])
        self.assertEqual(self.model['baseline_hashes'],sweep.BASELINE_HASHES)
        self.assertEqual(self.model['bounds']['adj']['required_bits'],81)
        for source in self.model['records']:
            self.assertEqual([b['count'] for b in source['banks']],[9,9,1,1,9,9])
            self.assertTrue(source['vector_hashes'])
        for r in self.complete['rtl_equivalence']:
            self.assertEqual(r['adj_checks'],18*sweep.configurations(r['scenario']))
            self.assertEqual(r['epochs'],sweep.epochs(r['scenario']))
        self.assertEqual(self.complete['rtl_directed'][0]['total_checks'],86528)

    def test_changed_model_and_unverified_claims_rejected(self):
        for key in ('scope','bounds','records','baseline_revision','baseline_hashes'):
            changed = copy.deepcopy(self.model)
            changed[key] = None
            with self.subTest(key=key):
                self.reject(changed)
        for key in sweep.SECTIONS:
            changed = copy.deepcopy(self.model)
            changed[key] = [copy.deepcopy(self.complete[key][0])]
            with self.subTest(unverified_section=key):
                self.reject(changed)
        changed = copy.deepcopy(self.model)
        changed['rtl_verified'] = 1
        self.reject(changed)
        for value in (40.0,True):
            changed = copy.deepcopy(self.model)
            changed['bounds']['stored']['gram'] = value
            self.reject(changed)
        changed = copy.deepcopy(self.model)
        changed['records'][0]['banks'][1]['min'] = 0.0
        self.reject(changed)

    def test_every_coverage_deletion_duplicate_and_key_type_rejected(self):
        for key in sweep.SECTIONS:
            for mutation in ('delete','duplicate','type'):
                changed = copy.deepcopy(self.complete)
                if mutation == 'delete':
                    changed[key].pop()
                elif mutation == 'duplicate':
                    changed[key].append(copy.deepcopy(changed[key][0]))
                else:
                    field = 'layout' if key=='rtl_lint' else 'active'
                    changed[key][0][field] = False if field=='active' else 0
                with self.subTest(section=key,mutation=mutation):
                    self.reject(changed)
        changed = copy.deepcopy(self.complete)
        changed['rtl_negative'][0]['tag'] = 'MMSE3_CONFIG_ADJ'
        self.reject(changed)
        changed = copy.deepcopy(self.complete)
        changed['rtl_equivalence'][0]['scenario'] = 'other'
        self.reject(changed)

    def test_stream_counts_widths_reset_epochs_and_timing_mutations_rejected(self):
        changes = [('outputs',0),('outputs',303.0),('cycles',0),('cycles',501),('cycles',500.0),
                   ('observers_verified',False),('widths',[80,126,104]),('widths',[81,125,104]),
                   ('widths',[81,126,103]),('widths',[81.0,126,104]),('epochs',0),('epochs',1.0),
                   ('configs',0),('configs',True)]
        for field in (*sweep.DIRECTED_COUNTS,'total_checks'):
            changes.extend(((field,0),(field,float(self.complete['rtl_equivalence'][0][field]))))
        for key,value in changes:
            changed = copy.deepcopy(self.complete)
            changed['rtl_equivalence'][0][key] = value
            with self.subTest(key=key,value=value):
                self.reject(changed)
        for scenario,field in product(('midreset','outreset','cfgreset'),('epochs','configs')):
            changed = copy.deepcopy(self.complete)
            record = next(r for r in changed['rtl_equivalence'] if r['scenario']==scenario)
            record[field] += 1
            with self.subTest(reset=scenario,field=field):
                self.reject(changed)
        changed = copy.deepcopy(self.complete)
        # Observer additions can change random scheduling; compare layouts
        # inside the current TB and frozen old/new inside the original TB.
        for r in changed['rtl_equivalence']:
            if (r['case'],r['active'],r['scenario'])==('identity',1,'stream'):
                r['cycles'] += 1
        sweep.check_acceptance(changed)

    def test_all_raw_bank_values_names_and_types_rejected(self):
        for section in ('rtl_equivalence','rtl_directed'):
            for index,key in product(range(6),('count','min','max')):
                changed = copy.deepcopy(self.complete)
                changed[section][0]['banks'][index][key] += 1
                with self.subTest(section=section,bank=index,key=key):
                    self.reject(changed)
            for mutation in ('missing','duplicate','name','type'):
                changed = copy.deepcopy(self.complete)
                banks = changed[section][0]['banks']
                if mutation=='missing':
                    banks.pop()
                elif mutation=='duplicate':
                    banks.append(copy.deepcopy(banks[0]))
                elif mutation=='name':
                    banks[0]['name'] = 'm_re'
                else:
                    banks[1]['min'] = float(banks[1]['min'])
                with self.subTest(section=section,mutation=mutation):
                    self.reject(changed)

    def test_frozen_directed_exit_codes_and_lint_mutations_rejected(self):
        for key,value in (('old_cycles',0),('new_cycles',501),('old_cycles',500.0),
                          ('new_outputs',0),('old_outputs',303.0)):
            changed = copy.deepcopy(self.complete)
            changed['rtl_frozen'][0][key] = value
            with self.subTest(frozen=key,value=value):
                self.reject(changed)
        for field in ('passed','widths','banks','epochs','configs',*sweep.DIRECTED_COUNTS,'total_checks'):
            changed = copy.deepcopy(self.complete)
            del changed['rtl_directed'][0][field]
            with self.subTest(directed_missing=field):
                self.reject(changed)
        for field,values in (('passed',(False,1)),('widths',([81,126,103],[81,126.0,104])),
                             ('epochs',(0,2,1.0)),('configs',(0,2,True))):
            for value in values:
                changed = copy.deepcopy(self.complete)
                changed['rtl_directed'][0][field] = value
                self.reject(changed)
        for field,expected in sweep.DIRECTED_COUNTS.items():
            for value in (0,expected+1,float(expected),True):
                changed = copy.deepcopy(self.complete)
                changed['rtl_directed'][0][field] = value
                self.reject(changed)
        for section,value in product(('rtl_negative','rtl_parameters'),(0,True,13.0,None,-11,1)):
            changed = copy.deepcopy(self.complete)
            changed[section][0]['returncode'] = value
            with self.subTest(section=section,returncode=value):
                self.reject(changed)
        for value in (1,False,0.0):
            changed = copy.deepcopy(self.complete)
            changed['rtl_lint'][0]['warnings'] = value
            self.reject(changed)

    def summary(self, banks, widths=(81,126,104), epoch=1):
        counts = [b['count'] for b in banks]
        text = ''.join(f"MMSE3 CONFIG BANK bank={i} count={b['count']} min={b['min']} max={b['max']}\n"
                       for i,b in enumerate(banks))
        return text+('PASS MMSE3 CONFIG ADJ_WIDTH=%d DET_WIDTH=%d M_WIDTH=%d epochs=%d '
                     'adj_re=%d adj_im=%d det_re=%d det_im=%d m_re=%d m_im=%d total=%d\n') % (
                         *widths,epoch,*counts,sum(counts))

    def test_parser_requires_unique_complete_summary_banks_and_matching_counts(self):
        banks = self.model['records'][0]['banks']
        text = self.summary(banks)
        parsed = sweep.parse_raw(text)
        self.assertEqual(parsed['banks'],banks)
        for bad in ('',text+text,text.replace('bank=1','bank=0'),
                    text.replace('bank=5','bank=6'),text.replace('total=38','total=39'),
                    text.replace('adj_re=9','adj_re=10'),
                    '\n'.join(text.splitlines()[1:])):
            with self.subTest(raw_bad=bad[-100:]):
                with self.assertRaises(RuntimeError):
                    sweep.parse_raw(bad)
        self.assertEqual(sweep.numeric('PASS MMSE3: 303 outputs, 500 cycles'),(303,500))
        for bad in ('', 'PASS MMSE3: outputs cycles', 'PASS MMSE3: 1 outputs, 2 cycles\n'*2):
            with self.assertRaises(RuntimeError):
                sweep.numeric(bad)
        banks = sweep.directed_banks()
        text = self.summary(banks)
        text += ''.join(f"MMSE3 CONFIG DIRECTED BANK bank={i} count={b['count']} min={b['min']} max={b['max']}\n"
                        for i,b in enumerate(banks))
        marker = 'PASS MMSE3 CONFIG DIRECTED ADJ_WIDTH=81 DET_WIDTH=126 M_WIDTH=104 adj=4608 det=8192 m=73728\n'
        text += marker
        parsed = sweep.parse_directed(text)
        self.assertEqual(parsed['banks'],banks)
        self.assertEqual(parsed['total_checks'],86528)
        for bad in (text+marker,text.replace('adj=4608','adj=4607'),
                    text.replace('DIRECTED ADJ_WIDTH=81','DIRECTED ADJ_WIDTH=84'),
                    text.replace('DIRECTED BANK bank=5','DIRECTED BANK bank=6')):
            with self.assertRaises(RuntimeError):
                sweep.parse_directed(bad)

    def test_optimized_python_cannot_emit_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'optimized.json'
            run = subprocess.run([sys.executable,'-O',str(ROOT/'tools/mmse3_config_width_sweep.py'),
                                  '--output',str(output)],capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('without Python optimization',run.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
