"""Independent finite-burst schedules, pin-trace validation and incomplete-evidence rejection."""
import copy,csv,io
from itertools import product
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'common/python')]
import fifo_budget as b
import axis_fifo_sweep as s


def fixture(length=16,capacity=14):
    """Synthetic independent transaction queue; not measured RTL evidence."""
    pending=[];departures={};sent=taken=0;rows=[]
    lasts=[int(i==length-1) for i in range(length)]
    for c in range(8*length+16):
        sv=int(sent<length);fv=int(bool(pending) and c-pending[0]>=2);fr=int(c>=2 and (c-2)%8==0)
        pop=fv and fr;ready=int(len(pending)<capacity or pop);mv=int(c in departures)
        row=[c,sv,ready,lasts[sent] if sv else 0,fv,fr,lasts[taken] if fv else 0,mv,1,departures.get(c,0),len(pending)]
        rows.append(row)
        if pop:pending.pop(0);departures[c+7]=lasts[taken];taken+=1
        if sv and ready:pending.append(c);sent+=1
        if sent==taken==length and c>=max(departures)+3:break
    text=io.StringIO();writer=csv.writer(text);writer.writerow(s.COLUMNS);writer.writerows(rows)
    return text.getvalue(),lasts


class Budgets(unittest.TestCase):
    def test_exact_capacity_against_independent_event_count(self):
        for length,interval,start in product(range(1,70),(1,2,3,8,17),(1,2,5,73)):
            outstanding=peak=0
            for c in range(max(start,length)+interval*length+1):
                if c>=start and (c-start)%interval==0 and outstanding:outstanding-=1
                if c<length:outstanding+=1
                peak=max(peak,outstanding)
            actual=b.finite_burst(length,interval,start)
            self.assertEqual(actual['required_capacity'],peak)
            self.assertGreaterEqual(actual['ram_power_of_two'],max(2,peak))
        self.assertEqual([b.finite_burst(n,8)['required_capacity'] for n in (16,64,128,512)],[14,56,112,448])

    def test_unbounded_deficit_and_invalid_inputs(self):
        for blocks in range(1,100):
            self.assertEqual(b.finite_burst(8*blocks,8)['required_capacity'],7*blocks)
        self.assertFalse(b.report()['sustained_service']['finite_fifo_suffices'])
        self.assertTrue(b.finite_burst(128,1)['infinite_one_per_cycle_supported'])
        for args in ((0,8,2),(1,0,2),(1,8,0),(True,8,2),(16,8.0,2),(16,8,False)):
            with self.assertRaises(ValueError):b.finite_burst(*args)


class Pins(unittest.TestCase):
    def test_minimum_and_one_word_short_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'pins.csv'
            for d in (2,13,14,15):
                text,lasts=fixture(capacity=d);p.write_text(text);r=s.measure(p,16,d,0,lasts)
                self.assertEqual(r['wait']==0,d>=14);self.assertEqual(r['peak'],min(d,14))
                self.assertEqual((r['first_service'],r['min_interval'],r['max_interval']),(2,8,8))

    def test_idle_last_may_be_unreset_but_valid_last_must_be_known(self):
        text,lasts=fixture();rows=list(csv.DictReader(io.StringIO(text)))
        for r in rows:
            for port in ('s','f','m'):
                if r[port+'_valid']=='0':r[port+'_last']='x'
        def encode():
            out=io.StringIO();w=csv.DictWriter(out,fieldnames=s.COLUMNS);w.writeheader();w.writerows(rows);return out.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'pins.csv';p.write_text(encode());s.measure(p,16,14,0,lasts)
            next(r for r in rows if r['f_valid']=='1')['f_last']='x';p.write_text(encode())
            with self.assertRaises(RuntimeError):s.measure(p,16,14,0,lasts)

    def test_missing_cycles_unknown_pins_occupancy_last_and_partial_trace(self):
        text,lasts=fixture();lines=text.splitlines()
        cases=[text.replace('cycle,','wrong,'), '\n'.join(lines[:5]+lines[6:])+'\n',
               '\n'.join(lines[:-12])+'\n']
        for column,value in (('level','99'),('s_valid','x'),('s_ready','2'),('m_last','1')):
            rows=list(csv.DictReader(io.StringIO(text)))
            row=next(r for r in rows if r['m_valid']=='1') if column=='m_last' else rows[3]
            row[column]=value;out=io.StringIO();w=csv.DictWriter(out,fieldnames=s.COLUMNS);w.writeheader();w.writerows(rows);cases.append(out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'pins.csv'
            for bad in cases:
                p.write_text(bad)
                with self.subTest(tail=bad[-60:]),self.assertRaises(RuntimeError):s.measure(p,16,14,0,lasts)


class Evidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Synthetic coverage solely exercises the validator, never a DUT result.
        d=s.report();d['rtl_verified']=True
        for (w,n),a in product(s.GEOMETRIES,(1,0)):
            d['unit'].append(dict(width=w,depth=n,active=a,pushed=10*n,popped=8*n,discarded=2*n,peak=n,
                swaps=4*n,full_swaps=4*n,resets=2,write_wraps=8,read_wraps=8,backlog_bubbles=1))
        for length,l,a,scenario in product(s.LENGTHS,s.LAYOUTS,(1,0),s.SCENARIOS):
            n=s.depth(length,l);need=b.finite_burst(length,8)['required_capacity'];wait=int(n<need)
            d['integration'].append(dict(length=length,layout=l,active=a,scenario=scenario,depth=n,words=length,
                wait=wait,peak=min(n,need),arrival_span=length+wait,first_service=2,min_interval=8,max_interval=8))
        for (w,n),a,t in product(((1,2),(73,256)),(1,0),('DATA','LAST','LEVEL')):
            d['negative'].append(dict(bench='unit',width=w,depth=n,active=a,tag=t,returncode=13))
        for a,t in product((1,0),('NUMERIC','PHASE','CAPACITY')):
            d['negative'].append(dict(bench='costas',width=36,depth=s.depth(64,'short' if t=='CAPACITY' else 'minimum'),active=a,tag=t,returncode=13))
        for (w,n),a in product(s.INVALID,(1,0)):d['parameters'].append(dict(width=w,depth=n,active=a,returncode=13))
        for w,n in s.GEOMETRIES:d['lint'].append(dict(width=w,depth=n,warnings=0))
        cls.complete=d

    def test_complete_json_and_missing_or_duplicate_sections(self):
        import json
        s.check_acceptance(json.loads(json.dumps(self.complete)));s.check_acceptance(s.report())
        for section in s.SECTIONS:
            for duplicate in (False,True):
                d=copy.deepcopy(self.complete)
                if duplicate:d[section][-1]=d[section][0]
                else:d[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):s.check_acceptance(d)

    def test_forged_counters_budgets_polarities_and_fault_codes(self):
        for section,key,v in [('unit','peak',0),('unit','discarded',0),('unit','full_swaps',0),('unit','backlog_bubbles',0),('unit','active',True),
                ('integration','depth',1),('integration','wait',True),('integration','arrival_span',1),
                ('integration','first_service',1),('integration','max_interval',9),('negative','returncode',0),
                ('parameters','returncode',True),('lint','warnings',1)]:
            d=copy.deepcopy(self.complete);d[section][0][key]=v
            with self.subTest(section=section,key=key),self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['unit'][0]['backlog_bubbles']=147
        s.check_acceptance(d)  # The counter includes random traffic after the directed bubble.
        d=copy.deepcopy(self.complete);d['budget']['rows'][0]['required_capacity']-=1
        with self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=s.report();d['unit']=[self.complete['unit'][0]]
        with self.assertRaises(RuntimeError):s.check_acceptance(d)

class ParentAudit(unittest.TestCase):
    def test_parent_replays_pins_and_rejects_changed_counters_or_missing_artifacts(self):
        from unittest.mock import patch
        from regression_evidence import begin,finish
        text,lasts=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tools').mkdir();(root/'tools/fixture.py').write_text('# hash fixture\n')
            trace=root/'runs/integration_16_minimum_1_0/pins.csv';trace.parent.mkdir(parents=True);trace.write_text(text)
            unit=root/'runs/unit_37_3_1_/simulation.log';unit.parent.mkdir(parents=True)
            unit.write_text('PASS AXIS FIFO width=37 depth=3 pushed=30 popped=24 discarded=6 peak=3 swaps=12 full_swaps=12 resets=2 write_wraps=8 read_wraps=8 backlog_bubbles=1\n')
            row=dict(s.measure(trace,16,14,0,lasts),length=16,layout='minimum',depth=14,active=1,scenario=0)
            d=dict(status='PASS',rtl_verified=True,vectors=[dict(length=16,lasts=lasts)],unit=[dict(s.parse_unit(unit.read_text()),active=1)],integration=[row],**finish(begin(root),[trace,unit],root))
            # Full matrix validation has separate corruption tests above; here
            # isolate the parent's independent artifact replay and hash checks.
            with patch.object(s,'check_acceptance'):
                self.assertEqual(set(s.verified_artifacts(d,root)),{trace,unit})
                for fault in ('measure','unit','artifact','verified'):
                    bad=copy.deepcopy(d)
                    if fault=='measure':bad['integration'][0]['wait']+=1
                    elif fault=='unit':bad['unit'][0]['pushed']+=1
                    elif fault=='verified':bad['rtl_verified']=False
                    else:bad['artifact_hashes'].pop(str(trace.relative_to(root)))
                    with self.subTest(fault=fault),self.assertRaises(RuntimeError):s.verified_artifacts(bad,root)
                trace.write_text(text+'\n')
                with self.assertRaisesRegex(RuntimeError,'artifact'):s.verified_artifacts(d,root)


if __name__=='__main__':unittest.main()
