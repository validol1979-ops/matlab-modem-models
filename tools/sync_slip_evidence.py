"""Measure quadrant relocking from accepted RTL outputs and a known carrier reference."""
import json
from pathlib import Path

from sync_scenarios import costas_slip_metrics, costas_disturbance_metrics


def _counted(path, convert):
    lines = Path(path).read_text().splitlines()
    if not lines or int(lines[0]) != len(lines) - 1:
        raise ValueError('[SLIP] incomplete counted reference')
    return [convert(line) for line in lines[1:]]


def check_costas_slip(folder, observed):
    folder = Path(folder)
    try:
        metadata = json.loads((folder / 'cl_slip.json').read_text())
        if metadata is None:
            return None
        expected = _counted(folder / 'cl_out.txt', lambda line: tuple(map(int, line.split())))
        actual = [tuple(map(int, line.split())) for line in Path(observed).read_text().splitlines()]
        if len(actual) != len(expected) or any(len(row) != 4 for row in actual):
            raise ValueError('incomplete accepted RTL trajectory')
        start, stop = metadata['row_start'], metadata['row_stop']
        if not 0 <= start < stop <= len(actual):
            raise ValueError('invalid scenario row range')
        reference = _counted(folder / metadata['reference_file'], float)
        disabled = _counted(folder / 'cl_slip_disabled.txt', int)
        if len(reference) != stop - start or len(disabled) != len(reference):
            raise ValueError('reference and trajectory lengths differ')
        phases = [row[2] for row in actual[start:stop]]
        metrics = costas_slip_metrics(phases, disabled, reference)
        if not metrics['slipped']:
            raise ValueError('accepted DUT phases do not show the required quadrant relocking')
        control = costas_slip_metrics(disabled, disabled, reference)
        if control['slipped']:
            raise ValueError('disabled loop passes the relocking criterion')
        if actual != expected:
            raise ValueError('captured trajectory differs from the scored DUT outputs')
        return dict(rtl_verified=True, samples=stop-start, metrics=metrics,
                    disabled_control_rejected=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f'[SLIP] {exc}') from exc


def check_costas_disturbances(folder, observed):
    """Confirm loss and later quadrant relocking from the actual accepted DUT phases."""
    folder = Path(folder)
    try:
        metadata = json.loads((folder/'cl_disturbances.json').read_text())
        if not metadata:
            return {}
        expected = _counted(folder/'cl_out.txt', lambda line: tuple(map(int,line.split())))
        actual = [tuple(map(int,line.split())) for line in Path(observed).read_text().splitlines()]
        if len(actual) != len(expected) or any(len(row) != 4 for row in actual):
            raise ValueError('incomplete accepted RTL trajectory')
        result = {}
        for entry in metadata:
            start, stop = entry['row_start'], entry['row_stop']
            if not 0 <= start < stop <= len(actual):
                raise ValueError('invalid disturbance row range')
            reference = _counted(folder/entry['reference_file'],float)
            disabled = _counted(folder/entry['disabled_file'],int)
            phases = [row[2] for row in actual[start:stop]]
            metrics = costas_disturbance_metrics(phases,disabled,reference)
            if not all(metrics[name] for name in ('acquired','lost_mod90_lock','relocked_mod90',
                                                 'adjacent_quadrant','disabled_rejected')):
                raise ValueError(f'{entry["kind"]}: required loss/relocking not observed')
            result[entry['kind']] = dict(rtl_verified=True,samples=stop-start,metrics=metrics)
        if actual != expected:
            raise ValueError('captured disturbance phases differ from scored outputs')
        return result
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RuntimeError(f'[DISTURBANCE] {exc}') from exc


def check_costas_acquisition(folder, observed):
    """Classify every sampled phase/CFO point from actual accepted DUT phases."""
    import costas_acquisition as ac
    folder = Path(folder)
    try:
        metadata = json.loads((folder/'cl_acquisition.json').read_text())
        if not metadata:
            return {}
        keys = [(row['phase_deg'],row['cfo_rad_per_sample']) for row in metadata]
        if len(keys) != len(ac.EXPECTED) or set(keys) != set(ac.EXPECTED):
            raise ValueError('incomplete or duplicated acquisition grid')
        expected = _counted(folder/'cl_out.txt',lambda line: tuple(map(int,line.split())))
        actual = [tuple(map(int,line.split())) for line in Path(observed).read_text().splitlines()]
        if len(actual) != len(expected) or any(len(row) != 4 for row in actual):
            raise ValueError('incomplete accepted RTL grid trajectory')
        measured = []
        for row in metadata:
            start,stop = row['row_start'],row['row_stop']
            if not 0 <= start < stop <= len(actual) or stop-start != ac.N:
                raise ValueError('invalid acquisition row range')
            reference = _counted(folder/row['reference_file'],float)
            if len(reference) != ac.N:
                raise ValueError('incomplete acquisition reference')
            if reference != ac.reference(row['phase_deg'],row['cfo_rad_per_sample']).tolist():
                raise ValueError('reference does not match the declared phase/CFO')
            error = ac.error_degrees([v[2] for v in actual[start:stop]],reference)
            windows = [ac.window_metrics(error,a,b) for a,b in ac.WINDOWS]
            classes = [ac.classify(window) for window in windows]
            offsets = [window['quadrant_offset_deg'] for window in windows]
            if classes[0] != classes[1] or (classes[0] != ac.UNLOCKED and offsets[0] != offsets[1]):
                raise ValueError('acquisition windows disagree')
            key = row['phase_deg'],row['cfo_rad_per_sample']
            expected_class,expected_offset = ac.EXPECTED[key]
            if classes[0] != expected_class or (expected_offset is not None and offsets[0] != expected_offset):
                raise ValueError(f'{key}: observed quadrant classification differs from the fixture')
            measured.append(dict(phase_deg=key[0],cfo_rad_per_sample=key[1],
                                 classification=classes[0],windows=windows))
        if actual != expected:
            raise ValueError('accepted grid capture differs from scored outputs')
        return dict(rtl_verified=True,points=len(measured),cases=measured,
                    scope='Finite phase/CFO grid; no continuous acquisition boundary is claimed')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RuntimeError(f'[ACQUISITION] {exc}') from exc
