#!/usr/bin/env python3
"""Persist current typed verification evidence and source integrity checks."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import csv
from regression_evidence import require_pass, write_json
ROOT=Path(__file__).resolve().parents[1]


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    inputs=['build/all_results.json','build/typed/all_results.json','build/typed/matlab_results.json',
            'build/typed/originals/matlab_results.json','build/typed/originals/python_results.json',
            'build/contracts/all_results.json','build/contracts/matlab_results.json',
            'build/typed_browser/results.json','docs/typed_model_catalog.json','docs/typed_visual/report_data.json']
    values={name:json.loads((ROOT/name).read_text()) for name in inputs}
    for name, value in values.items():
        if name.startswith('build/'):
            require_pass(value, ROOT)
    catalog=values['docs/typed_model_catalog.json'];sources={}
    for model in catalog:
        for rec in model['sources']:
            assert sha(ROOT/rec['source'])==rec['sha256'],rec['source']
            assert sha(ROOT/rec['original'])==rec['sha256'],rec['original']
            sources[rec['source']]=rec['sha256']
    for lang in ['all','matlab']:
        evidence=values[f'build/typed/{lang}_results.json']
        require_pass(evidence, ROOT)
        assert sha(ROOT/'build/typed/vectors.txt')==evidence['vectors_sha256']
        for name in ['common/python/research_core.py','common/octave/research_core.m','common/sv/research_dsp_pkg.sv']:
            assert sha(ROOT/name)==evidence['source_hashes'][name],name
    report={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS','new_workspaces':len(catalog),
            'preserved_source_hashes':sources,'evidence':values,'evidence_hashes':{name:sha(ROOT/name) for name in inputs},
            'scope':'Group algorithm analogues and explicitly named original-reference checks; not every historical script or figure has been reproduced.'}
    write_json(ROOT/'docs/typed_verification_results.json', report)
    print(f'PASS durable report: {len(catalog)} workspaces, {len(sources)} preserved source files')

if __name__=='__main__':main()
