#!/usr/bin/env python3
"""Инвентаризация и безопасная распаковка исходных архивов."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import subprocess
import os
import shutil

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {'.zip', '.rar', '.7z'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(path, destination):
    # Проверяем имена до распаковки, включая вложенные архивы.
    listing = subprocess.run(['7z', 'l', '-slt', str(path)],
                             capture_output=True, text=True, check=True).stdout
    names = listing.split('----------\n', 1)[1]
    for record in names.split('\n\n'):
        fields = dict(line.split(' = ', 1) for line in record.splitlines() if ' = ' in line)
        member = fields.get('Path', '').replace('\\', '/')
        if (PurePosixPath(member).is_absolute() or '..' in PurePosixPath(member).parts
                or ':' in member or fields.get('Symbolic Link') or fields.get('Hard Link')):
            raise ValueError(f'Unsafe archive member: {member}')
    destination.mkdir(parents=True, exist_ok=True)
    unrar = os.environ.get('UNRAR', shutil.which('unrar'))
    command = (['bsdtar', '-xf', str(path), '-C', str(destination)] if path.suffix.lower() == '.rar'
               else ['7z', 'x', '-y', f'-o{destination}', str(path)])
    if path.suffix.lower() == '.rar' and unrar:
        command = [unrar, 'x', '-o+', '-idq', str(path), str(destination) + '/']
    result = subprocess.run(command,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Extraction failed for {path}: {result.stdout} {result.stderr}')


def main():
    records, seen = [], {}
    queue = [(p, 'arxiv/' + p.name) for p in sorted((ROOT / 'arxiv').iterdir())
             if p.suffix.lower() in SUFFIXES]
    while queue:
        path, origin = queue.pop(0)
        sha = digest(path)
        if sha in seen:
            seen[sha]['aliases'].append(origin)
            continue
        destination = ROOT / 'sources' / path.stem
        if destination.exists() and any(r['directory'] == str(destination.relative_to(ROOT)) for r in records):
            destination = destination.with_name(destination.name + '_' + sha[:8])
        unpack(path, destination)
        record = dict(archive=origin, sha256=sha, aliases=[],
                      directory=str(destination.relative_to(ROOT)), files=[])
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                record['files'].append(dict(path=str(p.relative_to(ROOT)), sha256=digest(p), size=p.stat().st_size))
                if p.suffix.lower() in SUFFIXES:
                    queue.append((p, origin + '!' + str(p.relative_to(destination))))
        records.append(record)
        seen[sha] = record
    output = ROOT / 'docs' / 'archive_inventory.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(records, indent=2, ensure_ascii=False) + '\n')
    print(f'Inventoried {len(records)} unique archives; {sum(len(r["aliases"]) for r in records)} duplicate archives')
    for record in records:
        models = [p['path'] for p in record['files'] if Path(p['path']).suffix in {'.mdl', '.slx'}]
        print(f'{record["directory"]}: {len(record["files"])} files, {len(models)} models')


if __name__ == '__main__':
    main()
