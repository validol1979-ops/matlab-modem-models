"""Reject incomplete, reordered or regressed continuous RX evidence."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bpsk_rx_continuous_rate as rate
from bpsk_cases import receiver_vectors


def evidence(count=192, frames=4, *, extra=False, a=677, d=36):
    model = dict(symbols=count*frames, frames=frames, samples=(8*count+d)*frames,
                 payload_errors=[0]*frames)
    buffers = 3 if 8*count+96 <= 2048 else 2
    other = 103 if extra else 0
    tail = 32*(frames-1)
    reservations = ''.join(f'RX RESERVE cycle={100+100*f if f<buffers else 1003+300*(f-buffers)} '
                           f'frame={f} buffer={f%buffers}\n' for f in range(frames))
    block = (f'RX BUFFER BLOCK frame={buffers} buffer=0 first=900 last=1002 cycles=103 release=1003\n'
             if extra else '')
    text = (f'PASS BPSK receiver: {model["symbols"]} symbols, {frames} acquisitions, 0 payload errors\n'
            f'RX RATE accepted={model["samples"]} offered={model["samples"]+tail+other} '
            f'blocked={tail+other} tail_blocked={tail} other_blocked={other} '
            f'frames={frames} boundaries={frames-1} min_gap=32 max_gap={32+other} tail_checks={32*frames}\n'
            f'RX BLOCK STATES wait=0 acquire=0 track={other} retire=0\n' + block + reservations +
            ''.join(f'RX ACQUISITION start={100+1000*f} done={100+1000*f+a} A={a}\n' +
                    ''.join(f'RX EVENT cycle={1000+300*f+i} kind={kind} process_buffer={f%buffers}\n'
                            for i,kind in enumerate(('acquisition_done','tracking_done','retire')))
                    for f in range(frames)))
    return model, text


class RateEvidence(unittest.TestCase):
    def test_bursts_and_series_have_only_tail_gaps(self):
        for count, frames, d in ((192,4,36),(768,4,36),(2048,4,36),(192,16,36),(192,16,0)):
            with self.subTest(count=count,frames=frames,d=d):
                model, text = evidence(count,frames,d=d)
                row = rate.checked_rate(text, model, 1)
                self.assertEqual(row['other_blocked'], 0)
                self.assertEqual((row['a_min'],row['a_max'],row['queued_processing_period']),(677,677,1559))
                self.assertEqual(row['buffer_count'], 3 if count == 192 else 2)
                for old,new in [('max_gap=32','max_gap=33'),('min_gap=32','min_gap=33')]:
                    with self.assertRaises(RuntimeError):rate.checked_rate(text.replace(old,new),model,1)

    def test_series_must_not_exhaust_buffers(self):
        for frames in (4,16):
            model,text=evidence(frames=frames,extra=True)
            with self.assertRaises(RuntimeError):rate.checked_rate(text,model,0)

    def test_acquisition_budget_and_measurement(self):
        model,text=evidence(a=686)
        self.assertEqual(rate.checked_rate(text,model,1)['a_max'],686)
        for bad in (text.replace('A=686','A=687'),text.replace('A=686','A=685'),
                    text.replace('RX ACQUISITION','OMITTED'),text+text,
                    text.replace('start=1100','start=100')):
            with self.assertRaises(RuntimeError):rate.checked_rate(bad,model,1)
        model,text=evidence(a=687)
        with self.assertRaises(RuntimeError):rate.checked_rate(text,model,1)

    def test_capacity_boundary(self):
        for count,buffers in ((244,3),(245,2)):
            model,text=evidence(count)
            self.assertEqual(rate.checked_rate(text,model,1)['buffer_count'],buffers)
        model,text=evidence(245)
        with self.assertRaises(RuntimeError):rate.checked_rate(text.replace('frame=2 buffer=0','frame=2 buffer=2'),model,1)

    def test_missing_or_corrupted_coverage_fails(self):
        model,text=evidence(frames=16)
        for old,new in [(f'accepted={model["samples"]}','accepted=1'),
                         (f'offered={model["samples"]+480}','offered=1'),
                         ('tail_blocked=480','tail_blocked=479'),('frames=16 boundaries','frames=15 boundaries'),
                         ('boundaries=15','boundaries=14'),('min_gap=32','min_gap=31'),
                         ('tail_checks=512','tail_checks=511'),('3072 symbols','3071 symbols'),
                         ('track=0','track=1'),('kind=tracking_done','kind=retire'),
                         ('process_buffer=2','process_buffer=1'),('buffer=2','buffer=3'),
                         ('frame=2 buffer=2','frame=1 buffer=2'),('cycle=1003 frame=3','cycle=1002 frame=3')]:
            with self.subTest(old=old):
                self.assertIn(old,text)
                with self.assertRaises(RuntimeError):rate.checked_rate(text.replace(old,new),model,1)
        for bad in (text.splitlines()[0],text.replace('PASS BPSK receiver:','FAIL:'),
                    text+'UVM_ERROR [PROTOCOL]\n',text.replace('RX RESERVE','OMITTED')):
            with self.assertRaises(RuntimeError):rate.checked_rate(bad,model,1)

    def test_d0_generator_uses_exact_minimum_pin_length(self):
        with tempfile.TemporaryDirectory() as folder:
            model=receiver_vectors(Path(folder),count=192,frames=2,frame_padding=0)
            self.assertEqual(model['samples'],2*8*192)
            lines=(Path(folder)/'rx_wave.txt').read_text().splitlines()[1:]
            self.assertEqual([i for i,line in enumerate(lines) if line.split()[-1]=='1'],[1535,3071])
            self.assertEqual((Path(folder)/'rx_acquire.txt').read_text().splitlines()[0],'2')
            for d in (-1,65):
                with self.assertRaises(ValueError):receiver_vectors(Path(folder),frame_padding=d)
            with self.assertRaises(ValueError):receiver_vectors(Path(folder),loopback=True,frame_padding=0)


if __name__ == '__main__':unittest.main()
