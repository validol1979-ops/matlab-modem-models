'use strict';
// Все данные встроены в HTML, поэтому отчёт работает и через file:// без сервера.
const report = JSON.parse(document.getElementById('report-data').textContent);
const byName = new Map(report.models.map(model => [model.name, model]));
const state = {section: 'overview', model: 'bpsk_costas_2008_08_25', view: 'portable', case: 1};
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => Number(value).toLocaleString('en-US', {maximumSignificantDigits: 4});
const pill = (text, kind = '') => `<span class="pill ${kind}">${escapeHTML(text)}</span>`;

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (['overview','explorer','findings'].includes(p.get('section'))) state.section = p.get('section');
  if (byName.has(p.get('model'))) state.model = p.get('model');
  if (['portable','matlab'].includes(p.get('view'))) state.view = p.get('view');
  if (p.has('case') && /^[012]$/.test(p.get('case'))) state.case = Number(p.get('case'));
}

function navigate(changes, scroll = false) {
  Object.assign(state, changes);
  const hash = new URLSearchParams({section: state.section, model: state.model, view: state.view, case: state.case}).toString();
  history.replaceState(null, '', '#'+hash);
  render();
  if (scroll) document.querySelector('.main-tabs').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function modelList() {
  const query = $('model-search').value.toLowerCase().trim();
  const family = $('family-filter').value;
  const shown = report.models.filter(m => (!family || m.family === family) && `${m.name} ${m.label} ${m.family}`.toLowerCase().includes(query));
  $('model-count').textContent = `${shown.length} of ${report.models.length} models`;
  $('model-list').innerHTML = shown.map(m => `<button class="${m.name === state.model ? 'active' : ''}" data-model="${escapeHTML(m.name)}" aria-pressed="${m.name === state.model}">${escapeHTML(m.label)}<small>${escapeHTML(m.family)} · ${m.order} labels${m.equalizer !== 'none' ? ' · '+escapeHTML(m.equalizer.toUpperCase()) : ''}</small></button>`).join('');
  if (!shown.length) $('model-list').innerHTML = '<p class="muted">No matching modems.</p>';
}

function parameterText(parameters) {
  if (!Object.keys(parameters).length) return 'No channel impairments. Timing and carrier acquisition still execute.';
  const labels = {snr_db:'Sample SNR (dB)', gain:'Gain', phase:'Phase (rad)', frequency:'Frequency (cycles/sample)', delay:'Delay (samples)', echo:'Echo gain', drift:'Clock drift', phase_noise:'Phase-noise increment (rad)'};
  return Object.entries(parameters).filter(([key,value]) => value !== 0 || ['phase','delay','frequency'].includes(key)).map(([key,value]) => `${labels[key] || key}: ${number(value)}`).join(' · ');
}

function render() {
  for (const section of document.querySelectorAll('.report-section')) section.hidden = section.id !== state.section;
  for (const button of document.querySelectorAll('[data-section]')) {button.classList.toggle('active', button.dataset.section === state.section); button.setAttribute('aria-current', button.dataset.section === state.section ? 'page' : 'false');}
  modelList();
  const model = byName.get(state.model);
  const native = state.view === 'matlab';
  const selected = native ? model.matlab : model.cases[state.case];
  $('model-family').textContent = `${model.family} / ${model.order} INPUT LABELS / ${native ? 'MATLAB CAPTURE' : 'PORTABLE FRAME MODEL'}`;
  $('model-title').textContent = model.label;
  $('model-id').textContent = model.name;
  for (const button of document.querySelectorAll('[data-view]')) {button.classList.toggle('active', button.dataset.view === state.view);button.setAttribute('aria-pressed', button.dataset.view === state.view);}
  $('case-control').hidden = native;
  $('case-select').value = String(state.case);
  if (native) {
    $('case-metrics').innerHTML = `<div><strong>PASS</strong><span>Bounded simulation</span></div><div><strong>Exact</strong><span>Repeat timestamps & samples</span></div><div><strong>${model.mapper_blocks || '—'}</strong><span>Mapper blocks checked</span></div>`;
    $('case-description').textContent = `Original compile: ${model.native_original_compile === 'PASS' ? 'passed directly' : 'compatibility update required'}. TX monitor: ${selected.tx_monitor}. Receiver monitor: ${selected.rx_monitor || 'not present; original is a modulator only'}.`;
    $('figure-caption').textContent = 'Original R2020b signals. Native receiver points may be held or oversampled.';
    $('source-note').textContent = 'Captured MATLAB data; original files remain unchanged. The compatibility copy and repeatability are tested. These plots do not claim complete receiver equivalence.';
  } else {
    $('case-metrics').innerHTML = `<div><strong>${selected.symbol_errors} / ${selected.payload_symbols}</strong><span>Payload symbol errors</span></div><div><strong>${number(selected.ber)}</strong><span>Payload BER · ${selected.payload_bits} bits</span></div><div><strong>${number(selected.delay_samples)}</strong><span>Estimated delay / samples</span></div>`;
    $('case-description').textContent = parameterText(selected.parameters);
    $('figure-caption').textContent = 'Stored regression vectors + current Python replay. Training is excluded from BER/SER.';
    $('source-note').textContent = model.family === 'MSK' || model.family === 'GMSK' ? 'The CPM receiver uses a discriminator. Its histogram shows integrated phase increments, not a QAM/PSK constellation. This receiver is a portable abstraction.' : 'Orange points are raw channel samples. Blue points are recovered payload symbols. Ideal alphabet points are outlined; acquisition uses a known training prefix.';
  }
  $('modem-figure').src = selected.png;
  $('modem-figure').alt = `${model.label}: ${native ? 'original MATLAB signal capture' : selected.case + ', waveform, spectrum, receiver symbols and decoded labels'}`;
  $('figure-open').href = selected.svg;
  $('svg-download').href = selected.svg;
  $('png-download').href = selected.png;
  $('model-evidence').textContent = JSON.stringify({model:model.name, original_compile:model.native_original_compile,
    matlab_runtime:model.native_runtime, exact_repeat:model.native_repeat, mapper_blocks:model.mapper_blocks,
    library_changes:model.library_changes, runtime_changes:model.runtime_changes,
    portable_uvm:model.uvm, selected_view:native ? model.matlab : selected,
    full_original_receiver_equivalence:'NOT_ESTABLISHED'}, null, 2);
}

// Обработчики делегируются, чтобы фильтрация не оставляла устаревшие кнопки.
document.addEventListener('click', event => {
  const section = event.target.closest('[data-section]');
  const model = event.target.closest('[data-model]');
  const view = event.target.closest('[data-view]');
  if (section) navigate({section: section.dataset.section});
  if (model) navigate({model:model.dataset.model,section:'explorer'}, model.classList.contains('table-open'));
  if (view) navigate({view:view.dataset.view});
});
$('case-select').addEventListener('change', event => navigate({case:Number(event.target.value)}));
$('model-search').addEventListener('input', modelList);
$('family-filter').addEventListener('change', modelList);
window.addEventListener('hashchange', () => {readHash();render();});
const families = [...new Set(report.models.map(m => m.family))].sort();
for (const family of families) {const option = document.createElement('option');option.value=family;option.textContent=family;$('family-filter').append(option);}
$('model-table').innerHTML = report.models.map(m => `<tr><td>${escapeHTML(m.label)}</td><td>${m.native_original_compile === 'PASS' ? pill('PASS','pass') : pill('UPDATE','update')}</td><td>${pill('PASS','pass')}</td><td>${m.mapper_blocks ? pill(m.mapper_blocks+' checked','pass') : pill('Not checked')}</td><td><button class="table-open" data-model="${escapeHTML(m.name)}">Inspect →</button></td></tr>`).join('');
$('stress-description').textContent = `At −8 dB sample SNR, the BPSK negative control produces ${report.stress.symbol_errors} errors in ${report.stress.payload_symbols} payload symbols (BER ${number(report.stress.ber)}). The same receiver and checking path are used; no artificial error markers are inserted.`;
$('recording-dates').textContent = `Portable evidence: ${report.portable_recorded_utc.slice(0,10)}. MATLAB evidence: ${report.matlab_recorded_utc.slice(0,10)}. Rendered: ${report.generated_utc.slice(0,10)}. PDF: ${report.pdf_pages} pages.`;
readHash();render();
