"""Require completed per-field clamp comparisons and rejected monitor violations."""
import re
import subprocess


def check_observers(text, folder, block):
    files=[path for path in folder.glob('*_expected.txt')
           if not path.name.endswith('_fft_expected.txt')]
    if not files:raise RuntimeError('Missing clamp expectations')
    for path in files:
        name=path.name.removesuffix('_expected.txt')
        lines=path.read_text().splitlines()
        fields=int(lines[0]);rows=[list(map(int,line.split())) for line in lines[1:]]
        if len(rows)!=fields or any(len(row)!=3 or min(row)<0 or sum(row[1:])>row[0] for row in rows):
            raise RuntimeError(f'Malformed clamp expectations {name}')
        expected=sum(row[0] for row in rows),sum(sum(row[1:]) for row in rows)
        matches=re.findall(r'PASS SATURATION '+re.escape(name)+r': (\d+) evaluations, (\d+) events',text)
        if len(matches)!=1 or tuple(map(int,matches[0]))!=expected:
            raise RuntimeError(f'Clamp observer not verified: {name}, expected {expected}')
    if not re.search(r'PASS BOUNDS '+re.escape(block)+r': [1-9]\d* checks',text):
        raise RuntimeError('Missing exercised bounds comparison')


def negative_controls(common, folder, work, artifacts, final_pass):
    script=work/'observers.do'
    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
    artifacts.append(script)
    for name,flag,tag in [('events','+INJECT_SAT_MISMATCH','SATURATION'),
                          ('evaluations','+INJECT_SAT_EVAL_MISMATCH','SATURATION'),
                          ('bounds','+INJECT_BOUND_MISMATCH','BOUNDS')]:
        result=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do',script.name]],
                              cwd=work,capture_output=True,text=True,timeout=90)
        text=result.stdout+result.stderr;path=work/f'negative_{name}.log';path.write_text(text);artifacts.append(path)
        if not result.returncode or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(final_pass,text):
            raise RuntimeError(f'Negative observer control {name} not rejected: {text[-1500:]}')


def check_embedded_fft(text, folder, names):
    """Require each nested FFT stage comparison and its independent operation count."""
    for name in names:
        path=folder/f'{name}_fft_expected.txt'
        lines=path.read_text().splitlines()
        log2n=int(lines[0]);rows=[tuple(map(int,line.split())) for line in lines[1:]]
        if len(rows)!=8*log2n or any(len(row)!=3 or min(row)<0 or row[1]+row[2]>row[0]
                                      for row in rows):
            raise RuntimeError(f'Malformed embedded FFT expectations {name}')
        expected=sum(row[0] for row in rows),sum(row[1]+row[2] for row in rows)
        marker=r'PASS EMBEDDED FFT '+re.escape(name)+r': (\d+) evaluations, (\d+) events'
        matches=re.findall(marker,text)
        if len(matches)!=1 or tuple(map(int,matches[0]))!=expected:
            raise RuntimeError(f'Embedded FFT observer not verified: {name}, expected {expected}')


def negative_fft_controls(common, folder, work, artifacts, final_pass):
    script=work/'observers.do'
    if not script.is_file():
        script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts.append(script)
    for name,flag in [('events','+INJECT_FFT_SAT_MISMATCH'),
                      ('evaluations','+INJECT_FFT_SAT_EVAL_MISMATCH')]:
        result=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do',script.name]],
                              cwd=work,capture_output=True,text=True,timeout=90)
        message=result.stdout+result.stderr
        path=work/f'negative_fft_{name}.log';path.write_text(message);artifacts.append(path)
        if not result.returncode or not re.search(r'\*\* Fatal:.*\[SATURATION\]',message) or re.search(final_pass,message):
            raise RuntimeError(f'Negative embedded FFT control {name} not rejected: {message[-1500:]}')
