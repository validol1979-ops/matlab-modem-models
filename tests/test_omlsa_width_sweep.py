"""Exact OM-LSA gain intermediate bounds, minimality and complete raw/register evidence gates."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'common/python')]
import omlsa_gain_widths as widths
import omlsa_fixed as fixed
import omlsa_width_sweep as study

U17=(1<<17)-1;GMAX=(1<<31)-1


def wrap(value,width,signed):
    value&=(1<<width)-1
    return value-(1<<width) if signed and value>>(width-1) else value


def narrow_stage(name,operands,width):
    """One RTL expression evaluated modulo 2^width (the narrowed wire), rounding included."""
    if name=='RECIP_WIDTH':
        q,s=operands;return widths.narrow_rnd(q,s,width)
    if name=='GAMMA_WIDTH':
        power,rn,s=operands;return widths.narrow_rnd(wrap(power*rn,width,False),s,width)
    signed=name in widths.SIGNED
    shift={'XI_WIDTH':16,'V_WIDTH':16,'G1_WIDTH':12,'T_WIDTH':18,'A_WIDTH':16,'OUT_WIDTH':16,'GG_WIDTH':16,'PREV_WIDTH':16}[name]
    raw=wrap(exact_raw(name,operands),width,signed)
    return wrap(raw+(1<<(shift-1)),width,signed)>>shift


def exact_raw(name,operands):
    if name=='XI_WIDTH':
        alpha,prev,gamma=operands;return alpha*prev+(65536-alpha)*max(gamma-65536,0)
    if name=='T_WIDTH':
        xi,te=operands;return (65536+xi)*te
    if name=='A_WIDTH':
        p,ln=operands;return p*(ln-widths.LN05)
    a,b=operands;return a*b


def exact_stage(name,operands):
    if name=='RECIP_WIDTH':
        q,s=operands;return widths.rnd(q,s)
    if name=='GAMMA_WIDTH':
        power,rn,s=operands;return widths.rnd(power*rn,s)
    shift={'XI_WIDTH':16,'V_WIDTH':16,'G1_WIDTH':12,'T_WIDTH':18,'A_WIDTH':16,'OUT_WIDTH':16,'GG_WIDTH':16,'PREV_WIDTH':16}[name]
    return widths.rnd(exact_raw(name,operands),shift)


def corners(name):
    """Full-code operand corners of each expression (the extremes of a monotone product)."""
    g17=(0,1,65535,65536,U17);g31=(0,1,65536,65537,GMAX)
    if name=='RECIP_WIDTH':return product(g17,range(128))
    if name=='GAMMA_WIDTH':return product((0,1,1<<46,(1<<47)-1,1<<47),(0,1,1<<22,1<<23,(1<<24)-1),range(128))
    if name=='XI_WIDTH':return product((0,1,32768,65535,65536),g31,g31)
    if name=='V_WIDTH':return product(g31,g17)
    if name=='G1_WIDTH':return product(g17,(0,1,4096,(1<<20)-1))
    if name=='T_WIDTH':return product(g31,(0,1,65535))
    if name=='A_WIDTH':return product(g17,(-(1<<18),widths.LN05,0,8,(1<<18)-1))
    if name=='OUT_WIDTH':return product((-(1<<23),-1,0,(1<<23)-1),g17)
    if name=='GG_WIDTH':return ((g,g) for g in g17)
    return product(range(0,262141,65535),g31)


class TestOmlsaGainWidths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.layout=widths.layout()

    def test_selected_widths_and_old_layout(self):
        self.assertEqual(self.layout['selected'],[18,72,47,48,37,48,37,41,34,49])
        self.assertEqual(self.layout['old'],[128]*10)
        self.assertEqual(study.SELECTED,tuple(self.layout['selected']))
        self.assertEqual(len(study.LAYOUTS),12);self.assertEqual(len(study.INVALID),20);self.assertEqual(len(study.UNSAFE),10)

    def test_fixed_rounding_rows_fit_exactly_and_not_one_bit_less(self):
        for name in widths.PARAMETERS[2:]:
            row=self.layout['rows'][name];signed=name in widths.SIGNED;w=row['width']
            with self.subTest(name=name):
                self.assertTrue(widths.representable(row,w,signed))
                self.assertFalse(widths.representable(row,w-1,signed))
                self.assertEqual(row['rounded_max'],(row['max']+row['add'])>>{'G1_WIDTH':12,'T_WIDTH':18}.get(name,16))

    def test_variable_rounding_exact_for_every_shift_code(self):
        for name,high in (('RECIP_WIDTH',U17),('GAMMA_WIDTH',widths.POWER_MAX*((1<<24)-1))):
            w=self.layout['rows'][name]['width'];self.assertEqual(w,high.bit_length()+1)
            for v in (0,1,high,high>>1,(1<<(w-2)),(1<<(w-2))-1):
                for s in range(128):self.assertEqual(widths.narrow_rnd(v,s,w),widths.rnd(v,s),(name,v,s))
            self.assertTrue(any(widths.narrow_rnd(high,s,w-1)!=widths.rnd(high,s) for s in range(128)))

    def test_corner_extrema_match_bounds_and_narrower_width_fails(self):
        for name in widths.PARAMETERS:
            row=self.layout['rows'][name];w=row['width'];signed=name in widths.SIGNED
            raws=[];mismatch=False
            for operands in corners(name):
                exact=exact_stage(name,operands)
                self.assertEqual(narrow_stage(name,operands,w),exact,(name,operands))
                mismatch|=narrow_stage(name,operands,w-1)!=exact
                if name not in ('RECIP_WIDTH','GAMMA_WIDTH'):raws.append(exact_raw(name,operands))
            with self.subTest(name=name):
                self.assertTrue(mismatch)
                if raws:self.assertEqual((min(raws),max(raws)),(row['min'],row['max']))

    def test_random_full_code_operands_are_exact(self):
        rng=random.Random(5)
        draws={'RECIP_WIDTH':lambda:(rng.randrange(1<<17),rng.randrange(128)),
               'GAMMA_WIDTH':lambda:(rng.randrange((1<<47)+1),rng.randrange(1<<24),rng.randrange(128)),
               'XI_WIDTH':lambda:(rng.randrange(65537),rng.randrange(GMAX+1),rng.randrange(GMAX+1)),
               'V_WIDTH':lambda:(rng.randrange(GMAX+1),rng.randrange(1<<17)),'G1_WIDTH':lambda:(rng.randrange(1<<17),rng.randrange(1<<20)),
               'T_WIDTH':lambda:(rng.randrange(GMAX+1),rng.randrange(1<<16)),'A_WIDTH':lambda:(rng.randrange(1<<17),rng.randrange(-(1<<18),1<<18)),
               'OUT_WIDTH':lambda:(rng.randrange(-(1<<23),1<<23),rng.randrange(1<<17)),'GG_WIDTH':lambda:(lambda g:(g,g))(rng.randrange(1<<17)),
               'PREV_WIDTH':lambda:(rng.randrange(262141),rng.randrange(GMAX+1))}
        for name,draw in draws.items():
            w=self.layout['rows'][name]['width']
            for _ in range(2000):
                operands=draw();self.assertEqual(narrow_stage(name,operands,w),exact_stage(name,operands),(name,operands))

    def test_rom_contents_inside_full_codes_and_contracts(self):
        self.assertLessEqual(max(fixed.RECIP),U17);self.assertLess(max(fixed.TF),1<<20);self.assertLess(max(fixed.TE),1<<16)
        self.assertTrue(all(-(1<<18)<=v<(1<<18) for v in fixed.LN));self.assertLessEqual(max(fixed.EXPN),U17)
        self.assertEqual(widths.LN05,fixed.LN05);self.assertEqual(widths.GMAX,fixed.GMAX)
        self.assertEqual(widths.POWER_MAX,(-(1<<23))**2*2)
        self.assertEqual(self.layout['rows']['A_WIDTH']['difference_width'],20)
        self.assertEqual(self.layout['rows']['GG_WIDTH']['rounded_max'],262140)


class TestOmlsaWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            b=source['bins']
            for layout,a,scenario in product(study.LAYOUTS,(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],layout=layout[0],widths=list(layout[1]),active=a,scenario=scenario,
                    outputs=source['outputs'],cycles=100,observers_verified=True,bins=b,reciprocals=2*b,registers=8*b,
                    prev_registers=b-source['transactions'],**dict.fromkeys(study.PEAKS,1)))
        r['rtl_parameters']=[dict(log2n=n,layout=l[0],active=a,tag='PARAMETER',returncode=13) for n,l,a in product((4,5,6),study.INVALID,(1,0))]
        r['rtl_directed']=[dict(log2n=n,layout=l,active=a,checks=list(study.DIRECTED)) for n,l,a in product((4,6),('selected','old_all'),(1,0))]
        r['rtl_unsafe']=[dict(layout=l[0],widths=list(l[1]),active=a,tag='ARITHMETIC',returncode=13) for l,a in product(study.UNSAFE,(1,0))]
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),(*study.TAGS,'ARITHMETIC'))]
        return r

    def test_json_roundtrip_and_case_scope(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(self.model['records']),5)
        self.assertEqual({r['log2n'] for r in self.model['records']},{4,5,6})
        self.assertTrue(all(r['bins']>0 and r['transactions']>=3 for r in self.model['records']))

    def test_changed_incomplete_or_duplicated_records_rejected(self):
        for field,value in (('bins',0),('vector_hashes',{}),('outputs',0)):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=deepcopy(self.model);r['bounds']['selected'][0]=17
        with self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_directed','rtl_unsafe','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_raw_counts_peaks_cycles_and_fault_status(self):
        changes=[(k,0) for k in study.COUNTS]+[('gamma_peak',-1),('xi_peak',1<<47),('recip_peak',1<<17),('recip_peak',2),
                                               ('cycles',True),('cycles',101),('observers_verified',False),('outputs',1)]
        for field,value in changes:
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_unsafe','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_directed'][0]['checks'][1]=0
        with self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_unsafe'][0]['tag']='PARAMETER'
        with self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json';p=subprocess.run([sys.executable,'-O',str(ROOT/'tools/omlsa_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
