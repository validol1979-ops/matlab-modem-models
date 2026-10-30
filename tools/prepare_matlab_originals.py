#!/usr/bin/env python3
"""Готовим воспроизводимые копии старых MDL для MATLAB R2020b."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    for source in sorted((ROOT / 'modems').glob('*/original/*.mdl')):
        workspace = source.parent.parent
        raw = source.read_bytes()
        configuration = json.loads((workspace / 'config.json').read_text())
        if configuration.get('research_addition'):
            continue
        assert hashlib.sha256(raw).hexdigest() == configuration['source_sha256']
        parameters = json.loads((workspace / 'source_parameters.json').read_text())
        # В новом PSK-блоке нет numSamp; для всех наших схем он равен единице.
        for block in parameters:
            if block.get('SourceBlock', '').startswith('commdigbbndpm2/'):
                assert block.get('numSamp', '1') == '1', block
        changes = []
        data = raw
        for old, new in ((b'commchan2/', b'commchan3/'),
                         (b'commdigbbndpm2/', b'commdigbbndpm3/')):
            pattern = rb'(SourceBlock\s+")' + re.escape(old)
            data, count = re.subn(pattern, lambda m: m[1] + new, data)
            if count:
                changes.append(dict(old=old.decode(), new=new.decode(), count=count))
        target_dir = workspace / 'matlab'
        target_dir.mkdir(exist_ok=True)
        (target_dir / source.name).write_bytes(data)
        manifest = dict(source=str(source.relative_to(ROOT)),
                        original_sha256=hashlib.sha256(raw).hexdigest(),
                        prepared_sha256=hashlib.sha256(data).hexdigest(),
                        changes=changes,
                        caveat='Library migration is not proof of equivalence to the historical MATLAB release.')
        (target_dir / 'migration.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (target_dir / 'test_original.m').write_text("""function result = test_original()
% Проверяем только исходную схему текущего каталога с указанными адаптациями.
here = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(fileparts(here)));
addpath(fullfile(root, 'tools'));
[~, name] = fileparts(fileparts(here));
results = matlab_check_originals('compatible', name);
result = results{1};
assert(strcmp(result.status, 'PASS'), '%s', result.error_report);
end
""")
        print(f'PREPARED {workspace.name} library_replacements={sum(x["count"] for x in changes)}')


if __name__ == '__main__':
    main()
