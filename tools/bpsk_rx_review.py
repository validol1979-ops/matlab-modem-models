"""Directed RX arbitration/recovery vectors and strict coverage acceptance."""
import re
from bpsk_cases import receiver_vectors

EPOCH_COUNTS=(244,244,244,245,244,245,244)


def recovery_vectors(folder):
    return [receiver_vectors(folder/f'epoch{i}',frames=3,count=n,seed=119+i)
            for i,n in enumerate(EPOCH_COUNTS)]


def checked_review(text, *, collision=None, report=None):
    if re.search(r'UVM_(?:FATAL|ERROR)[^\n]*\[|\*\* (?:Fatal|Error)',text):
        raise RuntimeError('RX review simulation failed')
    if collision is not None:
        marker=re.findall(r'BPSK RX cfg collision index=(\d+) accepted_cfg=(\d+) blocked_data=(\d+)',text)
        passed=re.findall(r'PASS BPSK RX cfg arbitration index=(\d+) symbols=(\d+) acquisitions=(\d+)',text)
        if marker!=[(str(collision),'192',str(192-collision))] or passed!=[(str(collision),str(report['symbols']),str(report['frames']))]:
            raise RuntimeError('Incomplete RX configuration collision coverage')
        return dict(collision=collision,symbols=report['symbols'],acquisitions=report['frames'])
    epochs=[tuple(map(int,row)) for row in re.findall(r'BPSK RX review epoch N=(\d+) symbols=(\d+) acquisitions=(\d+) short_frames=(\d+)',text)]
    expected=[(n,3*n,3,int(n<=244)) for n in EPOCH_COUNTS]
    events=re.findall(r'BPSK RX (review epoch N=\d+|short reset mode=\d+)',text)
    expected_events=[f'review epoch N={n}' for n in EPOCH_COUNTS]
    expected_events.insert(1,'short reset mode=1');expected_events.insert(3,'short reset mode=2')
    if (events!=expected_events or epochs!=expected or re.findall(r'BPSK RX short reset mode=(\d+)',text)!=['1','2'] or
        text.count('PASS BPSK RX short recovery: 7 epochs, 21 frames, 5130 symbols, 21 acquisitions')!=1):
        raise RuntimeError('Incomplete numerical short-buffer recovery coverage')
    return dict(epochs=epochs,symbols=5130,acquisitions=21,reset_modes=[1,2])
