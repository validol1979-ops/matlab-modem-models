#!/usr/bin/env python3
"""Exercise every typed-report view in Firefox through Marionette."""
import json
from check_visual_browser import Browser,ROOT


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    from regression_evidence import begin, finish, write_json
    run_evidence=begin()
    atlas=ROOT/'docs'/'typed_visual'
    from regression_evidence import digest
    atlas_hashes={str(p.relative_to(ROOT)):digest(p) for p in atlas.rglob('*') if p.is_file()}
    output=ROOT/'build/typed_browser';output.mkdir(parents=True,exist_ok=True)
    write_json(output/'results.json',dict(run_evidence,status='RUNNING'))
    browser=Browser(2841)
    data=json.loads((ROOT/'docs/typed_visual/report_data.json').read_text());views=0
    browser.call('WebDriver:SetWindowRect',{'width':1500,'height':1050})
    browser.call('WebDriver:Navigate',{'url':(ROOT/'docs/typed_visual/index.html').as_uri()})
    assert browser.js("return Array.isArray(window.__reportErrors)"), "Missing startup error collector"
    def ready():
        result=browser.js("const done=arguments[arguments.length-1];const img=document.getElementById('figure');const deadline=Date.now()+10000;function check(){if(img.complete&&img.naturalWidth>0){done({width:img.naturalWidth,src:img.getAttribute('src')});}else if(Date.now()>deadline){done({error:'Image load timeout',src:img.src});}else{setTimeout(check,20);}}check();",asynchronous=True)
        assert result.get('width',0)>0,result
        return result['src']
    assert browser.js("return document.querySelectorAll('#model-list button').length")==len(data['models'])
    for model in data['models']:
        browser.js("document.querySelector('#model-list [data-id=\"'+arguments[0]+'\"]').click();",[model['id']])
        for i,view in enumerate(model['views']):
            browser.js("const s=document.getElementById('case');s.value=arguments[0];s.dispatchEvent(new Event('change'));",[str(i)])
            assert ready()==view['png'];views+=1
            assert browser.js("return document.getElementById('png').getAttribute('href')")==view['png']
            assert browser.js("return document.getElementById('svg').getAttribute('href')")==view['svg']
    for category in sorted({m['category'] for m in data['models']}):
        browser.js("const c=document.getElementById('category');c.value=arguments[0];c.dispatchEvent(new Event('change'));",[category])
        assert browser.js("return document.querySelectorAll('#model-list button').length")==sum(m['category']==category for m in data['models'])
    browser.js("const c=document.getElementById('category');c.value='';c.dispatchEvent(new Event('change'));const s=document.getElementById('search');s.value='ldpc';s.dispatchEvent(new Event('input'));")
    assert browser.js("return document.querySelectorAll('#model-list button').length")==1
    browser.js("document.querySelector('#model-list button').click();document.getElementById('case').value='2';document.getElementById('case').dispatchEvent(new Event('change'));")
    ready();browser.screenshot(output/'desktop_ldpc.png')
    browser.js("const s=document.getElementById('search');s.value='missing-xyz';s.dispatchEvent(new Event('input'));")
    assert browser.js("return !document.getElementById('empty').hidden")
    browser.js("const s=document.getElementById('search');s.value='';s.dispatchEvent(new Event('input'));")
    browser.call('WebDriver:SetWindowRect',{'width':390,'height':844});width=browser.js('return innerWidth')
    assert width<=700
    assert browser.js('return document.documentElement.scrollWidth<=innerWidth')
    browser.js("document.getElementById('title').scrollIntoView();");browser.screenshot(output/'mobile_ldpc.png')
    errors=browser.js('return window.__reportErrors');assert not errors,errors
    result={'status':'PASS','models':len(data['models']),'image_views':views,'categories':len({m['category'] for m in data['models']}),'viewport_width':width,'javascript_errors':errors,'horizontal_overflow':False}
    if atlas_hashes!={str(p.relative_to(ROOT)):digest(p) for p in atlas.rglob('*') if p.is_file()}:
        raise RuntimeError('Atlas changed during browser checks')
    result.update(finish(run_evidence,[ROOT/p for p in atlas_hashes]))
    write_json(output/'results.json',result)
    browser.call('WebDriver:DeleteSession');browser.socket.close()

if __name__=='__main__':main()
