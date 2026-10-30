#!/usr/bin/env python3
"""Typed source catalog and per-model execution entry points."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
from research_cases import cases,ROOT


def write_readme(path, text):
    """README ведутся вручную: генератор создаёт только отсутствующий файл."""
    if not path.exists():
        path.write_text(text)

PACKAGES={
 'modems/ofdm_awgn':('OFDM over AWGN',['research/electronix_20260930/support/ofdm'],
   'Independent complete block-OFDM analogue. Missing historical helpers are replaced by an explicit FFT/IFFT and cyclic-prefix contract; pilot placement and the original 48/64 carrier map are not reproduced.'),
 'modems/fsk_text':('Frequency-coded communication',['research/dsp_global_20260930/sources/iran_tehran'],
   'Orthogonal four-FSK complex-baseband analogue. Source text/alphabet conventions, amplitude-coding and plotting exercises are preserved as references, not claimed equivalent.'),
 'synchronization/symbol_timing':('Carrier and symbol synchronization',['research/dsp_global_20260930/sources/timing'],
   'Explicit Gardner PI timing loop and decision-directed QPSK Costas loop. The five original TED modes, all interpolators and MATLAB System Objects are not reproduced by this smaller contract.'),
 'channelizers/pfb_wola':('PFB and WOLA analysis banks',['research/dsp_global_20260930/sources/channelizer'],
   'Two kernel names expose the same defined FIR/DFT analysis-bank transform, with decimation equal to or smaller than the channel count. Source startup indexing and optional FFTW MEX are not reproduced.'),
 'filters/windowed_sinc':('FIR design and filtering',['research/dsp_global_20260930/sources/wsinc'],
   'Hamming-window low-pass design plus complex FIR filtering. The original automatic tap-search and full window family are outside the analogue contract.'),
 'adaptive/lms_nlms_rls':('Adaptive filters',['research/dsp_global_20260930/sources/china_adaptive'],
   'Complex LMS, NLMS and RLS system identification. Outputs include estimates, errors and final coefficients; real source-function comparisons are recorded separately.'),
 'coding/ldpc':('LDPC coding',['research/dsp_global_20260930/sources/china_ldpc'],
   'Generic systematic GF(2) encoder and SP/MS/NMS/OMS decoders. Portable regression uses an explicit short sparse code; the original (2016,1008) matrix is retained and original-length checks are reported separately.'),
 'filters/oset':('Generic noise and interference filters',['research/dsp_global_20260930/sources/iran_oset'],
   'Portable notch and scalar Kalman filtering examples. Full OSET biomedical/ARMA models and every selected helper are preserved for reference; these examples do not establish equivalence to all 13 source functions.'),
 'mimo/dsplog':('MIMO and diversity',['research/dsp_global_20260930/sources/india_dsplog'],
   'Complex zero-forcing/MMSE spatial detection and Alamouti combining. Historical large Monte Carlo sweeps, SIC ordering and ISI/ZF demo parameters are not reproduced.'),
 'audio/stft':('STFT analysis and reconstruction',['research/dsp_global_20260930/sources/israel_stft'],
   'Complex full-spectrum STFT with sqrt-Hann window and normalized overlap-add. Original dual-window and frequency-decimation conventions differ; exact finite-frame reconstruction is tested.'),
 'audio/omlsa':('Speech-preserving spectral gain',['research/dsp_global_20260930/sources/israel_omlsa'],
   'OM-LSA gain with decision-directed prior SNR and estimated speech presence. Noise is calibrated from a stated noise-only prefix; historical IMCRA noise tracking is not reproduced.'),
 'arrays/beamforming':('Array beamforming',['research/dsp_global_20260930/sources/israel_beamforming'],
   'Delay-and-sum complex steering and spatial null test. The 188 book figure/helper files are catalogued together; this analogue does not reproduce every chapter or figure.'),
 'teaching/harger':('DSP teaching examples',['research/electronix_20260930/support/harger'],
   'Analytic DFT/inverse-DFT and FIR impulse exercises. Other historical examples and Mathcad worksheets remain preserved source material, not separately converted modem models.'),
}


def destination(key):return ROOT/key if key.startswith('modems/') else ROOT/'algorithms'/key


def main():
    all_cases=cases();catalog=[];coverage={}
    for key,(title,sources,limits) in PACKAGES.items():
        dest=destination(key)
        for folder in ('original','python','octave','matlab','sv','tb','tests'):(dest/folder).mkdir(parents=True,exist_ok=True)
        records=[]
        for source_dir in sources:
            base=ROOT/source_dir
            for source in sorted(base.rglob('*')):
                if not source.is_file():continue
                relative=source.relative_to(base);target=dest/'original'/relative
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                record={'source':str(source.relative_to(ROOT)),'original':str(target.relative_to(ROOT)),
                    'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':source.stat().st_size}
                records.append(record)
                if source.suffix.lower() in ('.m','.mlx','.mdl'):coverage[record['source']]={'workspace':key,'source_status':'preserved','verification_scope':'group algorithm analogue; not individual source equivalence',**record}
        selected=[c for c in all_cases if c['workspace']==key]
        entry={'id':key,'title':title,'category':key.split('/')[0],'path':str(dest.relative_to(ROOT)),
            'operations':sorted({c['operation'] for c in selected}),'cases':[c['name'] for c in selected],
            'limits':limits,'sources':records,'implementations':['Python','Octave','MATLAB','SystemVerilog'],'verification':'UVM and numeric/analytic checks'}
        (dest/'model.json').write_text(json.dumps(entry,indent=2)+'\n');catalog.append(entry)
        (dest/'python/model.py').write_text('''from pathlib import Path
import sys
# Находим корень по общей библиотеке, независимо от глубины категории.
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'common/python/research_core.py').is_file())
sys.path.insert(0,str(ROOT/'common/python'))
from research_core import run
''')
        (dest/'tests/test_model.py').write_text(f'''from pathlib import Path
import subprocess
import sys
import unittest
# Тест запускает все сценарии только этой модели.
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/run_research.py').is_file())
class ModelTests(unittest.TestCase):
    def test_numeric_contract(self):
        subprocess.run([sys.executable,str(ROOT/'tools/run_research.py'),'--suite','python','--workspace','{key}'],check=True)

if __name__=='__main__': unittest.main()
''')
        for language in ('octave','matlab'):
            (dest/language/'run_model.m').write_text('''function y=run_model(operation,parameters,signal,auxiliary)
% Одна M-реализация выполняется в MATLAB и в Octave без toolbox.
if nargin<4, auxiliary=[]; end
here=fileparts(mfilename('fullpath'));root=here;
while ~isfolder(fullfile(root,'common','octave'))
  parent=fileparts(root);
  if strcmp(parent,root), error('Project root not found'); end
  root=parent;
end
addpath(fullfile(root,'common','octave'));
y=research_core(operation,parameters,signal,auxiliary);
end
''')
        (dest/'sv/model.sv').write_text('// Обёртка выбранной модели над общей поведенческой реализацией.\nmodule dsp_variant(research_if bus);\n  research_model core(bus);\nendmodule\n')
        (dest/'tb/testbench.sv').write_text('// UVM sequence, driver, monitor и scoreboard находятся в общем testbench.\n`include "research_tb.sv"\n')
        (dest/'tb/run.sh').write_text(f'''#!/usr/bin/env bash
set -euo pipefail
# Находим корень, не завися от текущего рабочего каталога.
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
while [[ ! -f "$root/tools/run_research.py" ]]; do
  [[ "$root" != / ]] || {{ printf 'Project root not found\\n' >&2; exit 1; }}
  root="$(dirname -- "$root")"
done
exec python3 "$root/tools/run_research.py" --suite hdl --workspace '{key}' "$@"
''');(dest/'tb/run.sh').chmod(0o755)
        rel='../'*(len(dest.relative_to(ROOT).parts))
        write_readme(dest / 'README.md', f'''# {title}

Generated workspace: rerunning `research_layout.py` overwrites configuration and execution entry points; an existing README is kept.

Category: **{entry['category']}**. Implementations: Python, Octave/MATLAB and behavioral SystemVerilog with an actual UVM sequence, driver, monitor and scoreboard.

{limits}

## Operations

{', '.join('`'+op+'`' for op in entry['operations'])}

The original files are preserved under [original](original/). Every source path, size and SHA-256 is in [model.json](model.json). New code comments are Russian; diagnostics and figures are English.

## Run from the project root

```bash
python3 tools/run_research.py --suite python --workspace {key}
python3 tools/run_research.py --suite octave --workspace {key}
python3 tools/run_research.py --suite matlab --workspace {key}
python3 tools/run_research.py --suite hdl --workspace {key}
```

MATLAB should run in a terminal on this host. The Python model exposes `run(operation, parameters, signal, auxiliary)`. The Octave/MATLAB entry point is `run_model` with the same four arguments. Flat numeric array layouts and units are defined in [the contract]({rel}docs/TYPED_MODELS.md).

[Visual report]({rel}docs/typed_visual/index.html#{key}) · [Python entry point](python/model.py) · [Octave entry point](octave/run_model.m) · [UVM launcher](tb/run.sh)

The SystemVerilog model uses real arithmetic and block transactions; it is not synthesizable fixed-point RTL. Cross-language agreement checks this stated portable contract and does not prove full equivalence to each historical source file.

## Test preview

![Verified test scenario]({rel}docs/typed_visual/algorithms/{key.replace('/', '__')}/{selected[0]['name']}.png)
''')
    for key in ('oqpsk_2_sps_timing_recovery_2019_12_05','qpsk_8_sps_fb_sync_2020_11_25','qpsk_script_basic','qpsk_script_costas'):
        cfg=json.loads((ROOT/'modems'/key/'config.json').read_text());sources=[]
        p=ROOT/cfg['source'];paths=sorted(p.parent.glob('*.m')) if p.suffix=='.m' else [p]
        for source in paths:
            record={'source':str(source.relative_to(ROOT)),'original':str(Path('modems')/key/'original'/source.name),
                    'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':source.stat().st_size}
            sources.append(record);coverage.setdefault(record['source'],{'workspace':'modems/'+key,'source_status':'preserved','verification_scope':'portable modem analogue; original evidence separate',**record})
        catalog.append({'id':'modems/'+key,'category':'modems','title':key.replace('_',' '),'path':'modems/'+key,'sources':sources,
                        'operations':[cfg['family']],'limits':cfg['abstraction'],'cases':['clean','impaired','stress']})
    expected={str(p.relative_to(ROOT)) for p in (ROOT/'research').rglob('*') if p.suffix.lower() in ('.m','.mlx','.mdl')}
    assert set(coverage)==expected,expected-set(coverage)
    (ROOT/'docs/typed_model_catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    with (ROOT/'docs/typed_source_coverage.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(next(iter(coverage.values())).keys()));writer.writeheader();writer.writerows(coverage.values())
    print(f'PASS {len(catalog)} typed workspaces; all {len(coverage)} MATLAB/Simulink source files assigned and preserved')

if __name__=='__main__':main()
