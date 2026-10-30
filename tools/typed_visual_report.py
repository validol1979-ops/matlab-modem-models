#!/usr/bin/env python3
"""Render actual typed-model captures, scientific figures and an offline explorer."""
from pathlib import Path
import csv
import hashlib
import html
import json
import sys
import textwrap
import numpy as np
from scipy.io import loadmat
from scipy.signal import freqz,welch
from visual_report import ROOT,Report,figure,portable_chart,original_chart,vector,metrics,BLUE,TEAL,ORANGE,INK,MUTED
from research_cases import cases
from research_core import run
from modem_core import transmit,receive
import matplotlib.pyplot as plt


def compact(value):
    if isinstance(value,float):return f'{value:.5g}'
    return str(value)


def plot_wave(ax,z,title,limit=240):
    z=np.asarray(z).ravel()[:limit];ax.plot(z.real,lw=1,color=BLUE,label='Real')
    if np.any(z.imag):ax.plot(z.imag,lw=1,color=TEAL,label='Imaginary')
    ax.set(title=title,xlabel='Sample / element index',ylabel='Value');ax.legend(fontsize=8)


def plot_spectrum(ax,x,y):
    for data,label,color in [(x,'Input',MUTED),(y,'Output',TEAL)]:
        f,s=welch(data,fs=1,nperseg=min(128,len(data)),return_onesided=False)
        idx=np.argsort(f);ax.plot(f[idx],10*np.log10(np.maximum(s[idx],1e-18)),color=color,label=label,lw=1)
    ax.set(title='Power spectra',xlabel='Cycles per sample',ylabel='PSD (dB / normalized Hz)');ax.legend(fontsize=8)


def algorithm_chart(c,cross):
    op=c['operation'];x,a,y,p=c['x'],c['a'],c['y'],c['parameters'];title=c['workspace'].replace('/',' / ')
    footer='Source: seeded test captures, replayed in Python. MATLAB, Octave and UVM compare the same transaction. PASS applies to the documented portable contract; original source equivalence is recorded separately.'
    fig,ax=figure(title,f"{c['name']}  /  operation: {op}  /  PASS",footer)
    plot_wave(ax[0],x,'Input');plot_wave(ax[1],y,'Output')
    # Нижние панели зависят от физического смысла выходов, а не рисуют любые массивы как I/Q.
    if op in ('lms','nlms','rls'):
        n=len(x);error=y[n:2*n];smooth=np.convolve(abs(error)**2,np.ones(16)/16,'valid')
        ax[0].cla();ax[0].plot(a.real[:100],color=MUTED,label='Desired');ax[0].plot(y.real[:100],color=BLUE,label='Estimate',lw=1);ax[0].legend();ax[0].set(title='System identification',xlabel='Sample',ylabel='Real amplitude')
        ax[1].cla();ax[1].semilogy(np.maximum(smooth,1e-30),color=TEAL);ax[1].set(title='Learning curve · 16-sample mean',xlabel='Sample',ylabel='Squared error')
        ax[2].bar(np.arange(len(y)-2*n)-.16,y[2*n:].real,.32,label='Real');ax[2].bar(np.arange(len(y)-2*n)+.16,y[2*n:].imag,.32,label='Imaginary');ax[2].set(title='Final filter coefficients',xlabel='Tap',ylabel='Weight');ax[2].legend()
    elif op in ('pfb','wola'):
        matrix=y.reshape(-1,int(p[0]));ax[1].cla();ax[1].plot(abs(matrix));ax[1].set(title='Channel envelopes',xlabel='Output block',ylabel='Magnitude')
        ax[2].bar(range(int(p[0])),10*np.log10(np.maximum(np.mean(abs(matrix[12:])**2,axis=0),1e-18)),color=TEAL);ax[2].set(title='Steady-state channel power',xlabel='Channel index',ylabel='Power (dB)')
    elif op=='ldpc':
        n=int(p[1]);ax[0].cla();ax[0].stem(x.real,linefmt=BLUE,markerfmt='o',basefmt=' ');ax[0].set(title='Channel log-likelihood ratios',xlabel='Codeword bit',ylabel='LLR')
        ax[1].cla();ax[1].step(range(n),x.real<0,where='mid',label='Initial hard decision',color=ORANGE);ax[1].step(range(n),y[:n].real,where='mid',label='Decoded',color=TEAL,ls='--');ax[1].legend();ax[1].set(title='Error correction',xlabel='Codeword bit',ylabel='Bit')
        ax[2].stem(y[n:].real,linefmt=TEAL,markerfmt='o',basefmt=' ');ax[2].set(title='Posterior confidence',xlabel='Codeword bit',ylabel='LLR')
    elif op=='gf2_encode':
        ax[2].imshow(a.real.reshape(int(p[0]),int(p[1])),cmap='Blues',vmin=0,vmax=1);ax[2].set(title='Parity generator matrix A',xlabel='Information bit',ylabel='Parity bit')
    elif op in ('stft','istft'):
        s=y if op=='stft' else x;matrix=s.reshape(-1,int(p[0]));ax[2].imshow(20*np.log10(np.maximum(abs(np.fft.fftshift(matrix,axes=1)).T,1e-8)),aspect='auto',origin='lower',extent=[0,len(matrix)*p[1],-.5,.5],cmap='magma');ax[2].set(title='STFT magnitude (dB)',xlabel='Frame start (samples)',ylabel='Cycles per sample')
    elif op=='omlsa':
        ax[0].cla();ax[0].plot(x.real,color=MUTED,lw=.7,label='Noisy');ax[0].plot(c['truth'].real,color=BLUE,lw=1,label='Clean reference');ax[0].legend();ax[0].set(title='Noise-only calibration, then signal',xlabel='Sample',ylabel='Amplitude')
        ax[1].cla();ax[1].plot(c['truth'].real,color=MUTED,label='Clean reference');ax[1].plot(y.real,color=TEAL,lw=.8,label='OM-LSA analogue');ax[1].legend();ax[1].set(title='Reconstructed signal',xlabel='Sample',ylabel='Amplitude');plot_spectrum(ax[2],x[224:],y[224:])
    elif op=='beamform':
        angles=np.linspace(-90,90,721);steering=np.exp(1j*np.pi*np.arange(len(a))[:,None]*np.sin(np.deg2rad(angles)))
        response=abs(a.conj()@steering/np.vdot(a,a));ax[2].plot(angles,20*np.log10(np.maximum(response,1e-5)),color=TEAL);ax[2].set(title='Array response · half-wavelength spacing',xlabel='Arrival angle (degrees)',ylabel='Gain (dB)',ylim=(-65,3))
    elif op in ('mimo','alamouti','ofdm_tx','ofdm_rx','costas','timing'):
        z=y[:int(p[1])] if op=='timing' else (y[:len(x)] if op=='costas' else (x if op=='ofdm_tx' else y))
        if op in ('costas','timing'):z=z[min(200,len(z)//2):]
        ax[2].scatter(z.real,z.imag,s=10,alpha=.5,color=TEAL);ax[2].set(title='Recovered symbols' if op!='ofdm_tx' else 'Input carrier symbols',xlabel='In-phase',ylabel='Quadrature',aspect='equal')
        if op=='timing':ax[1].cla();ax[1].plot(y[int(p[1]):].real-(p[2]+p[0]*np.arange(int(p[1]))),color=TEAL);ax[1].set(title='Timing correction',xlabel='Symbol',ylabel='Samples')
        if op=='costas':ax[1].cla();ax[1].plot(y[len(x):].real,color=TEAL);ax[1].set(title='Tracked carrier phase',xlabel='Symbol',ylabel='Radians')
    elif op in ('fir','wsinc','notch'):
        if op=='wsinc':b=y;den=[1]
        elif op=='notch':b=[1,-2*np.cos(2*np.pi*p[0]),1];den=[1,-2*p[1]*np.cos(2*np.pi*p[0]),p[1]**2]
        else:b=a;den=[1]
        f,h=freqz(b,den,worN=1024);ax[2].plot(f/(2*np.pi),20*np.log10(np.maximum(abs(h),1e-8)),color=TEAL);ax[2].set(title='Filter frequency response',xlabel='Cycles per sample',ylabel='Magnitude (dB)')
    elif op=='dft':
        ax[2].stem(abs(y if not p[0] else x),linefmt=TEAL,markerfmt='o',basefmt=' ');ax[2].set(title='DFT bin magnitudes',xlabel='Frequency bin',ylabel='Magnitude')
    elif op=='fsk_rx':
        ax[2].step(range(len(y)),y.real,where='mid',color=TEAL);ax[2].set(title='Recovered frequency labels',xlabel='Symbol',ylabel='Label')
    else:plot_spectrum(ax[2],x,y)
    ax[3].axis('off');rows=['NUMERIC AGREEMENT','']
    rows.extend(f'{name}: max |difference| = {value:.3g}' for name,value in cross.items())
    rows+=['','ACCEPTANCE METRICS'];rows.extend(f"{k.replace('_',' ')}: {compact(v)}" for k,v in c['metric'].items())
    if not c['metric']:rows.append('Analytic oracle / stated transform contract passed.')
    ax[3].text(0,1,'\n'.join(rows),va='top',fontsize=10,linespacing=1.6,color=INK)
    return fig


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    from regression_evidence import require_pass
    output=ROOT/'docs/typed_visual';report=Report(output);catalog=report.json(ROOT/'docs/typed_model_catalog.json')
    by_id={m['id']:m for m in catalog};data=cases();saved=report.json(ROOT/'build/typed/cases.json')
    results={lang:report.json(ROOT/f'build/typed/{lang}_results.json') for lang in ['octave','matlab','hdl']}
    for lang,value in results.items():
        require_pass(value, ROOT)
        assert value['status']=='PASS' and value['cases']==len(data),lang
        assert value['vectors_sha256']==hashlib.sha256((ROOT/'build/typed/vectors.txt').read_bytes()).hexdigest()
        kernel={'octave':'common/octave/research_core.m','matlab':'common/octave/research_core.m','hdl':'common/sv/research_dsp_pkg.sv'}[lang]
        for name in ('common/python/research_core.py',kernel):
            assert hashlib.sha256(report.source(ROOT/name).read_bytes()).hexdigest()==value['source_hashes'][name], f'Stale {lang} implementation evidence'
    report.source(ROOT/'tools/typed_visual_report.py')
    models=[];case_views={key:[] for key in by_id}
    for i,c in enumerate(data):
        path=report.source(ROOT/f'build/typed/case_{i:03}.npz');assert hashlib.sha256(path.read_bytes()).hexdigest()==saved[i]['capture_sha256']
        with np.load(path) as z:
            for key in ('x','a','y','parameters'):np.testing.assert_array_equal(c[key],z[key])
        cross={lang:results[lang][lang][i]['maximum_error'] for lang in ('octave','matlab')}
        cross['SystemVerilog (suite maximum)']=results['hdl']['hdl']['maximum_error']
        stem=f'algorithms/{c["workspace"].replace("/","__")}/{c["name"]}'
        asset=report.save(algorithm_chart(c,cross),stem,pdf=True)
        case_views[c['workspace']].append({'name':c['name'],'kind':'portable','metrics':c['metric'],**asset})
        print(f"PASS figure {c['workspace']}/{c['name']}",flush=True)
    for entry in catalog:
        key=entry['id'];views=case_views[key]
        if not views:
            name=key.split('/')[-1];cfg=report.json(ROOT/entry['path']/'config.json')
            manifest=report.json(ROOT/'build/vectors'/name/'manifest.json')
            for index in range(3):
                v=vector(report.source(ROOT/'build/vectors'/name/f'case_{index}.txt'))
                np.testing.assert_allclose(transmit(cfg,v['data'])['waveform'],v['tx'],atol=1e-12)
                replay=receive(cfg,v['wave'],v['data'][:v['training']],len(v['data']))
                np.testing.assert_array_equal(replay['data'],v['decoded'])
                fig,metric=portable_chart(cfg,v,['Clean channel','AWGN + carrier + delay','Stress channel'][index],manifest[index]['channel'])
                asset=report.save(fig,f'modems/{name}/case_{index}',pdf=True);views.append({'name':['Clean','Impaired','Stress'][index],'kind':'portable','metrics':metric,**asset})
            native=ROOT/'build/research_review'/name
            if (native/'signals.mat').exists():
                traces=loadmat(report.source(native/'signals.mat'),simplify_cells=True)['traces'];result=report.json(native/'result.json')
                fig,metric=original_chart(cfg,traces,result);asset=report.save(fig,f'modems/{name}/original_matlab',pdf=True)
                views.append({'name':'Original MATLAB capture','kind':'original','metrics':metric,**asset})
        models.append({'id':key,'title':entry['title'],'category':entry['category'],'limits':entry['limits'],'source_files':len(entry['sources']),
                       'workspace':'../../'+entry['path']+'/README.md','views':views,'operations':entry['operations']})
    fig,ax=plt.subplots(figsize=(13,8));fig.subplots_adjust(left=.37,right=.94,top=.86,bottom=.12)
    labels=[m['id'] for m in models];counts=[len(m['views']) for m in models]
    ax.barh(range(len(models)),counts,color=[TEAL if m['category']=='modems' else BLUE for m in models]);ax.set_yticks(range(len(models)),labels);ax.invert_yaxis();ax.set(xlabel='Verified visual scenarios',title='Typed verification atlas · 17 new workspaces')
    for i,n in enumerate(counts):ax.text(n+.06,i,str(n),va='center')
    fig.text(.03,.025,'Source preservation covers 295 MATLAB/Simulink files. Group analogues do not reproduce every historical script or book figure.',fontsize=9)
    overview=report.save(fig,'overview',pdf=True);report.pdf.close()
    # Локальные данные встроены в страницу: сервер и сетевые запросы не требуются.
    payload={'models':models,'overview':overview,'figures':len(report.assets)//2,'pdf_pages':report.pages,'algorithm_cases':len(data)}
    template=(ROOT/'tools/typed_visual_assets/index.html').read_text()
    (output/'index.html').write_text(template.replace('__REPORT_DATA__',json.dumps(payload).replace('</','<\\/')))
    for name in ['report.css','report.js']:shutil_copy(ROOT/'tools/typed_visual_assets'/name,output/name)
    (output/'report_data.json').write_text(json.dumps(payload,indent=2)+'\n')
    provenance={'sources':report.evidence,'assets':{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in report.assets},'pdf_pages':report.pages}
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    with (output/'metrics.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['workspace','case','metric','value'])
        for m in models:
            for v in m['views']:
                for k,value in v['metrics'].items():w.writerow([m['id'],v['name'],k,json.dumps(value)])
    print(f'PASS visual report: {len(models)} workspaces, {len(report.assets)//2} figures, {report.pages} PDF pages')


def shutil_copy(a,b):b.write_bytes(a.read_bytes())
if __name__=='__main__':main()
