#!/usr/bin/env python3
"""Проверяем локальный отчёт в уже запущенном Firefox с Marionette."""
from pathlib import Path
import argparse
import base64
import json
import socket

ROOT = Path(__file__).resolve().parents[1]


class Browser:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=30)
        self.sequence = 0
        self.read()
        self.call('WebDriver:NewSession', {'capabilities': {'alwaysMatch': {'acceptInsecureCerts': False}}})

    def read(self):
        length = b''
        while not length.endswith(b':'):
            data = self.socket.recv(1)
            if not data: raise RuntimeError('Browser connection closed')
            length += data
        remaining = int(length[:-1]); chunks = []
        while remaining:
            data = self.socket.recv(remaining)
            if not data: raise RuntimeError('Truncated browser response')
            chunks.append(data); remaining -= len(data)
        return json.loads(b''.join(chunks))

    def call(self, method, arguments=None):
        self.sequence += 1
        payload = json.dumps([0, self.sequence, method, arguments or {}]).encode()
        self.socket.sendall(str(len(payload)).encode()+b':'+payload)
        response = self.read()
        assert response[1] == self.sequence
        if response[2]: raise RuntimeError(response[2])
        result = response[3]
        return result.get('value', result) if isinstance(result, dict) else result

    def js(self, script, args=None, asynchronous=False):
        return self.call('WebDriver:ExecuteAsyncScript' if asynchronous else 'WebDriver:ExecuteScript',
                         dict(script=script, args=args or [], newSandbox=False, sandbox=None))

    def image_ready(self):
        result = self.js("""const done=arguments[arguments.length-1];
            const img=document.getElementById('modem-figure');
            const deadline=Date.now()+10000;
            function check(){
              const expected=new URL(img.getAttribute('src'),document.baseURI).href;
              if(img.complete && img.naturalWidth>0 && img.currentSrc===expected){
                done({width:img.naturalWidth,src:img.getAttribute('src')});
              }else if(Date.now()>deadline){done({error:'Image load timeout',src:img.src});}
              else{setTimeout(check,20);}
            }
            check();""", asynchronous=True)
        assert result.get('width', 0) > 0, result
        return result['src']

    def screenshot(self, path):
        result = self.call('WebDriver:TakeScreenshot', {'id': None, 'highlights': [], 'full': False})
        path.write_bytes(base64.b64decode(result))


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=2841)
    args = parser.parse_args()
    from regression_evidence import begin, finish, write_json
    run_evidence=begin()
    atlas=ROOT/'docs'/'visual'
    from regression_evidence import digest
    atlas_hashes={str(p.relative_to(ROOT)):digest(p) for p in atlas.rglob('*') if p.is_file()}
    evidence=ROOT/'build/visual_browser';evidence.mkdir(exist_ok=True)
    write_json(evidence/'results.json',dict(run_evidence,status='RUNNING'))
    browser = Browser(args.port)
    browser.call('WebDriver:SetWindowRect', {'width': 1440, 'height': 1100})
    browser.call('WebDriver:Navigate', {'url': (ROOT/'docs/visual/index.html').as_uri()})
    assert browser.js("return document.querySelectorAll('#model-table tr').length") == 20
    assert browser.js("return Array.isArray(window.__reportErrors)"), "Missing startup error collector"
    browser.js("""const done=arguments[arguments.length-1];
        document.querySelector('#overview img').decode().then(()=>done(true));""", asynchronous=True)
    browser.screenshot(evidence/'desktop_overview.png')
    models = json.loads((ROOT/'docs/visual/report_data.json').read_text())['models']
    checked = 0
    for model in models:
        browser.js("document.querySelector('#model-list [data-model=\"'+arguments[0]+'\"]').click();", [model['name']])
        browser.js("document.querySelector('[data-view=portable]').click();")
        for case in range(3):
            browser.js("const s=document.getElementById('case-select');s.value=arguments[0];s.dispatchEvent(new Event('change'));", [str(case)])
            assert browser.image_ready() == model['cases'][case]['png']
            checked += 1
        browser.js("document.querySelector('[data-view=matlab]').click();")
        assert browser.image_ready() == model['matlab']['png']
        assert browser.js("return document.getElementById('case-control').hidden")
        checked += 1
    browser.js("const s=document.getElementById('model-search');s.value='simo';s.dispatchEvent(new Event('input'));")
    assert browser.js("return document.querySelectorAll('#model-list button').length") == 1
    browser.js("const s=document.getElementById('model-search');s.value='no-such-modem';s.dispatchEvent(new Event('input'));")
    assert browser.js("return document.querySelectorAll('#model-list button').length") == 0
    browser.js("const s=document.getElementById('model-search');s.value='';s.dispatchEvent(new Event('input'));const f=document.getElementById('family-filter');f.value='QAM';f.dispatchEvent(new Event('change'));")
    assert browser.js("return document.querySelectorAll('#model-list button').length") == 5
    browser.js("const f=document.getElementById('family-filter');f.value='';f.dispatchEvent(new Event('change'));document.querySelector('[data-model=bpsk_costas_2008_08_25]').click();document.querySelector('[data-view=portable]').click();document.querySelector('.main-tabs').scrollIntoView();")
    browser.image_ready()
    browser.screenshot(evidence/'desktop_explorer.png')
    browser.call('WebDriver:SetWindowRect', {'width': 390, 'height': 844})
    viewport_width = browser.js('return window.innerWidth')
    assert viewport_width <= 700, 'Browser did not enter the mobile layout'
    assert browser.js("return document.documentElement.scrollWidth <= window.innerWidth"), 'Mobile horizontal overflow'
    browser.js("document.getElementById('model-title').scrollIntoView();")
    browser.screenshot(evidence/'mobile_explorer.png')
    browser.js("document.querySelector('[data-section=findings]').click();")
    assert browser.js("return !document.getElementById('findings').hidden")
    assert browser.js("return document.documentElement.scrollWidth <= window.innerWidth"), 'Findings mobile overflow'
    errors = browser.js("return window.__reportErrors")
    assert not errors, errors
    result = dict(status='PASS', browser='Firefox / Marionette', checked_image_views=checked,
                  filters=['name', 'no results', 'QAM family'], mobile_width=viewport_width,
                  horizontal_overflow=False, javascript_errors=errors)
    if atlas_hashes!={str(p.relative_to(ROOT)):digest(p) for p in atlas.rglob('*') if p.is_file()}:
        raise RuntimeError('Atlas changed during browser checks')
    result.update(finish(run_evidence,[ROOT/p for p in atlas_hashes]))
    write_json(evidence/'results.json',result)
    browser.call('WebDriver:DeleteSession')
    browser.socket.close()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
