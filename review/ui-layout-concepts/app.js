const preview = document.querySelector('#preview');
const agentPane = document.querySelector('#agent-card');
const systemPane = document.querySelector('#system-card');
agentPane.tabIndex = -1;
systemPane.tabIndex = -1;
const mobileZoneButtons = [...document.querySelectorAll('[data-mobile-zone-choice]')];
const sourceButtons = [...document.querySelectorAll('[data-source]')];
const sourceRows = [...document.querySelectorAll('[data-source-row]')];
const scopeBoxes = [...document.querySelectorAll('.scope-box')];
const reviewTabButtons = [...document.querySelectorAll('[data-review-tab]')];
const resultTabButtons = [...document.querySelectorAll('button[data-result-tab]')];
const scanStageButtons = [...document.querySelectorAll('[data-scan-stage-choice]')];
const sourceSearch = document.querySelector('#source-search');
const draftInput = document.querySelector('#source-draft');
const processStateSelect = document.querySelector('#process-state');
const announcement = document.querySelector('#view-announcement');

const sources = {
  context: {
    name: 'context.txt',
    kind: 'Text source',
    ready: true,
    original: '# Context notes\n\nUse the selected originals as evidence.\nKeep Agent chat separate from System work.\nReview the exact scope before processing.',
  },
  brief: {
    name: 'brief.md',
    kind: 'Text source',
    ready: true,
    original: '# Brief\n\nDescribe the intended outcome.\nRecord important constraints.\nConfirm the source selection before Start.',
  },
  image: {
    name: 'screen.png',
    kind: 'Image source',
    ready: false,
    original: 'Image preview unavailable in this layout study.\nA configured vision provider is required before inspection.',
  },
  url: {
    name: 'reference.url',
    kind: 'Unfetched reference',
    ready: false,
    original: 'This reference has not been fetched.\nIt cannot be admitted as inspected source evidence.',
  },
};

const processStates = {
  waiting: {
    title: 'Waiting for committed events',
    copy: 'No job is connected to this layout study. A real run would show its first persisted event here.',
    note: 'No events yet',
  },
  reconnecting: {
    title: 'Connection interrupted',
    copy: 'The product should show the last committed event and reconnect from its saved cursor.',
    note: 'Awaiting reconnection',
  },
  blocked: {
    title: 'Job blocked',
    copy: 'The product should show the server reason and the next action without implying that work continues.',
    note: 'No progress claimed',
  },
  completed: {
    title: 'Job completed',
    copy: 'A real completed inspection would link to source observations and the evidence packet.',
    note: 'Result belongs to a real job',
  },
};

const sampleMarkdown = [
  '# OneShot-Context',
  '',
  '> Illustrative layout sample. This gallery has not scanned, read, consolidated, or semantically verified any source.',
  '',
  '## Current User Intent',
  '',
  'Consolidate related OneShot releases and discussions into one grounded Markdown context document.',
  '',
  '## Relevant Changes',
  '',
  'Pending inspection of the selected original sources. No release changes are asserted in this sample.',
  '',
  '## Conflicts and Uncertainty',
  '',
  'Potential disagreements should remain visible until the source evidence is reviewed.',
  '',
  '## Sources and Limitations',
  '',
  '- Source names and coverage in this layout are examples, not observed scanner results.',
  '- Image interpretation, archive extraction, and semantic accuracy are unverified.',
  '',
].join('\n');

const drafts = Object.fromEntries(
  Object.entries(sources).map(([key, source]) => [key, source.original])
);
const savedDrafts = { ...drafts };
let state = readStateFromUrl();
let beforeProcess = null;
let suspendedDetail = null;

function historySnapshot() {
  return { oneshotLayoutStudy: { beforeProcess, suspendedDetail } };
}

function restoreHistorySnapshot(snapshot) {
  const saved = snapshot?.oneshotLayoutStudy;
  beforeProcess = saved?.beforeProcess && typeof saved.beforeProcess === 'object'
    ? saved.beforeProcess : null;
  suspendedDetail = saved?.suspendedDetail && typeof saved.suspendedDetail === 'object'
    ? saved.suspendedDetail : null;
}

function valid(value, choices, fallback) {
  return choices.includes(value) ? value : fallback;
}

function readStateFromUrl() {
  const params = new URL(window.location.href).searchParams;
  const scope = params.has('scope')
    ? params.get('scope').split(',').filter(key => sources[key]?.ready)
    : ['context', 'brief'];
  return normalize({
    owner: params.get('owner') || 'system',
    right: params.get('right') || 'closed',
    detail: params.get('detail') || 'closed',
    source: params.get('source') || 'context',
    tab: params.get('tab') || 'read',
    zone: params.get('zone') || 'system',
    subview: params.get('subview') || 'list',
    focus: params.get('focus') || 'off',
    processState: params.get('process') || 'waiting',
    scanStage: params.get('scan') || 'result',
    resultTab: params.get('result') || 'preview',
    filter: params.get('q') || '',
    scope,
  });
}

function normalize(candidate) {
  const next = { ...candidate };
  next.owner = valid(next.owner, ['system', 'agent'], 'system');
  next.right = valid(next.right, ['open', 'closed'], 'closed');
  next.detail = valid(next.detail, ['closed', 'review', 'process'], 'closed');
  next.source = valid(next.source, Object.keys(sources), 'context');
  next.tab = valid(next.tab, ['read', 'edit', 'diff'], 'read');
  next.zone = valid(next.zone, ['agent', 'system'], 'system');
  next.subview = valid(next.subview, ['list', 'review'], 'list');
  next.focus = valid(next.focus, ['on', 'off'], 'off');
  next.processState = valid(next.processState, Object.keys(processStates), 'waiting');
  next.scanStage = valid(next.scanStage, ['prompt', 'processing', 'result'], 'result');
  next.resultTab = valid(next.resultTab, ['preview', 'sources', 'coverage'], 'preview');
  next.filter = typeof next.filter === 'string' ? next.filter : '';
  next.scope = [...new Set(next.scope)].filter(key => sources[key]?.ready);
  if (next.right === 'closed') {
    next.detail = 'closed';
    next.focus = 'off';
    next.subview = 'list';
  }
  if (next.detail !== 'review') next.subview = 'list';
  if (next.detail !== 'review') next.focus = 'off';
  if (next.owner === 'agent' && next.tab === 'edit') next.tab = 'read';
  if (!sources[next.source].ready) next.tab = 'read';
  if (next.detail === 'process') next.scanStage = 'processing';
  return next;
}

function urlFor(current) {
  const url = new URL(window.location.href);
  const params = url.searchParams;
  params.delete('concept');
  params.delete('agent');
  const values = {
    owner: current.owner,
    right: current.right,
    detail: current.detail,
    source: current.source,
    tab: current.tab,
    zone: current.zone,
    subview: current.subview,
    focus: current.focus,
    process: current.processState,
    scan: current.scanStage,
    result: current.resultTab,
    q: current.filter,
    scope: current.scope.join(','),
  };
  const defaults = {
    owner: 'system',
    right: 'closed',
    detail: 'closed',
    source: 'context',
    tab: 'read',
    zone: 'system',
    subview: 'list',
    focus: 'off',
    process: 'waiting',
    scan: 'result',
    result: 'preview',
    q: '',
    scope: 'context,brief',
  };
  for (const [key, value] of Object.entries(values)) {
    if (value === defaults[key]) params.delete(key);
    else params.set(key, value);
  }
  return url;
}

function focusAfterRender(element, scroll = false) {
  requestAnimationFrame(() => {
    if (!element || !element.getClientRects().length) return;
    element.focus();
    if (scroll) element.scrollIntoView({ block: 'start', behavior: 'auto' });
  });
}

function commit(patch, { replace = false, announce = '', focus = null, scroll = false } = {}) {
  state = normalize({ ...state, ...patch });
  render();
  const url = urlFor(state);
  window.history[replace ? 'replaceState' : 'pushState'](historySnapshot(), '', url);
  if (announce) announcement.textContent = announce;
  if (focus) focusAfterRender(focus, scroll);
}

function renderProcess() {
  const sample = processStates[state.processState];
  document.querySelector('#process-status-label').textContent = sample.title;
  document.querySelector('#process-status-copy').textContent = sample.copy;
  processStateSelect.value = state.processState;
  const list = document.querySelector('#process-event-list');
  list.replaceChildren();

  const empty = document.createElement('li');
  empty.className = 'process-event is-empty';
  const heading = document.createElement('strong');
  heading.textContent = sample.note;
  const detail = document.createElement('p');
  detail.textContent = 'This is a design state. No live event, progress percentage, or inspection result is asserted.';
  empty.append(heading, detail);
  list.append(empty);

  for (const [name, fields] of [
    ['source_inspected', 'Source reference, inspection status, and observed coverage'],
    ['coverage_assessed', 'Inspected and unavailable source coverage'],
  ]) {
    const row = document.createElement('li');
    row.className = 'process-event is-contract';
    const label = document.createElement('span');
    label.textContent = 'SUPPORTED EVENT SHAPE';
    const title = document.createElement('strong');
    title.textContent = name;
    const body = document.createElement('p');
    body.textContent = fields + '. Values appear only after a committed System event.';
    row.append(label, title, body);
    list.append(row);
  }
}

function renderReview() {
  const source = sources[state.source];
  const editable = source.ready && state.owner === 'system';
  document.querySelector('#source-name').textContent = source.name;
  document.querySelector('#source-status').textContent = source.kind + (source.ready ? ' / readable original' : ' / unavailable for sample scope');
  document.querySelector('#source-content').textContent = source.original;
  if (draftInput.value !== drafts[state.source]) draftInput.value = drafts[state.source];
  document.querySelector('#diff-original').textContent = source.original;
  document.querySelector('#diff-current').textContent = drafts[state.source];
  let revisionState = 'Original revision';
  if (!source.ready) revisionState = 'Original unavailable for editing';
  else if (!editable && drafts[state.source] !== savedDrafts[state.source]) revisionState = 'Unsaved sample changes; Agent active';
  else if (!editable) revisionState = 'Read-only while Agent active';
  else if (drafts[state.source] !== savedDrafts[state.source]) revisionState = 'Unsaved sample changes';
  else if (drafts[state.source] !== source.original) revisionState = 'Sample draft saved in preview';
  document.querySelector('#revision-state').textContent = revisionState;

  for (const button of reviewTabButtons) {
    const selected = button.dataset.reviewTab === state.tab;
    button.disabled = (!source.ready && button.dataset.reviewTab !== 'read')
      || (!editable && button.dataset.reviewTab === 'edit');
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    document.querySelector('#' + button.dataset.reviewTab + '-panel').hidden = !selected;
  }
  document.querySelector('#save-draft').disabled =
    !editable || drafts[state.source] === savedDrafts[state.source];
  draftInput.disabled = !editable;
  document.querySelector('#compare-changes').disabled = !source.ready;
  document.querySelector('#review-focus').setAttribute('aria-pressed', String(state.focus === 'on'));
  document.querySelector('#review-focus').textContent =
    state.focus === 'on' ? 'Exit focus' : 'Focus review';
}

function render() {
  delete preview.dataset.concept;
  delete preview.dataset.agent;
  preview.dataset.owner = state.owner;
  preview.dataset.right = state.right;
  preview.dataset.detail = state.detail;
  preview.dataset.scanStage = state.scanStage;
  preview.dataset.resultTab = state.resultTab;
  preview.dataset.mobileZone = state.zone;
  preview.dataset.mobileSubview = state.subview;
  preview.dataset.reviewFocus = state.focus;

  const agentOwner = state.owner === 'agent';
  const rightOpen = state.right === 'open';
  const processing = state.detail === 'process';
  const narrowWorkspace = window.matchMedia('(max-width: 900px)').matches;
  const sourcesVisible = rightOpen && (!narrowWorkspace || state.zone === 'system');
  const processToggle = document.querySelector('#process-toggle');
  processToggle.textContent = state.scanStage === 'processing' ? 'Finish sample' : 'Show processing';
  document.querySelector('#detail-stage').hidden = state.detail === 'closed';
  document.querySelector('.review-view').hidden = state.detail !== 'review';
  document.querySelector('.process-view').hidden = !processing;
  document.querySelector('#scan-card').hidden = state.scanStage === 'prompt';
  document.querySelector('#markdown-result').hidden = state.scanStage !== 'result';
  const resultMarkdown = document.querySelector('#result-markdown');
  if (resultMarkdown.textContent !== sampleMarkdown) resultMarkdown.textContent = sampleMarkdown;

  for (const button of scanStageButtons) {
    button.setAttribute('aria-pressed', String(button.dataset.scanStageChoice === state.scanStage));
  }
  for (const button of resultTabButtons) {
    const selected = button.dataset.resultTab === state.resultTab;
    button.id = 'result-' + button.dataset.resultTab + '-tab';
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    const panel = document.querySelector('#result-' + button.dataset.resultTab + '-panel');
    panel.hidden = !selected;
    panel.setAttribute('aria-labelledby', button.id);
  }
  const railAgent = document.querySelector('#rail-agent-toggle');
  const railSystem = document.querySelector('#rail-system-toggle');
  const railSources = document.querySelector('#rail-sources-toggle');
  const railCoverage = document.querySelector('#rail-coverage-open');
  railAgent.setAttribute('aria-pressed', String(agentOwner));
  railAgent.setAttribute('aria-label', agentOwner ? 'Agent Chat active' : 'Use Agent Chat');
  railAgent.classList.toggle('is-selected', agentOwner);
  railSystem.setAttribute('aria-pressed', String(!agentOwner));
  railSystem.setAttribute('aria-label', agentOwner ? 'Use System Chat' : 'System Chat active');
  railSystem.classList.toggle('is-selected', !agentOwner);
  railSources.setAttribute('aria-pressed', String(sourcesVisible));
  railSources.setAttribute('aria-expanded', String(sourcesVisible));
  railSources.setAttribute('aria-label', sourcesVisible ? 'Collapse Sources' : 'Open Sources');
  railSources.classList.toggle('is-selected', sourcesVisible);
  const mobileSources = document.querySelector('#mobile-sources-toggle');
  mobileSources.setAttribute('aria-expanded', String(sourcesVisible));
  mobileSources.setAttribute('aria-label', sourcesVisible ? 'Close System sources' : 'Open System sources');
  const coverageVisible = state.scanStage === 'result' && state.resultTab === 'coverage'
    && (!narrowWorkspace || state.zone === 'system');
  railCoverage.setAttribute('aria-pressed', String(coverageVisible));
  railCoverage.setAttribute('aria-label', 'Show result coverage');
  railCoverage.classList.toggle('is-selected', coverageVisible);

  for (const button of mobileZoneButtons) {
    button.setAttribute('aria-pressed', String(button.dataset.mobileZoneChoice === state.zone));
  }
  for (const button of sourceButtons) {
    const selected = state.detail === 'review' && state.source === button.dataset.source;
    button.classList.toggle('is-active', selected);
    button.setAttribute('aria-expanded', String(selected));
    button.disabled = processing;
  }
  for (const box of scopeBoxes) {
    box.checked = state.scope.includes(box.value);
    box.disabled = agentOwner || !sources[box.value].ready;
  }
  document.querySelector('#scope-count').textContent = String(state.scope.length);
  document.querySelector('#scope-hint').textContent = agentOwner
    ? 'Agent active: source changes locked. Unavailable sources cannot join.'
    : 'Only ready originals can join. Start requires a real System connection.';
  document.querySelector('#system-access').textContent = agentOwner
    ? 'Read-only while Agent active' : 'System active / layout preview';
  document.querySelector('#agent-access').textContent = agentOwner
    ? 'Agent selected / layout preview' : 'Read-only while System active';
  document.querySelector('#composer-owner').textContent = 'SYSTEM INPUT';
  const composerSample = document.querySelector('#composer-sample');
  composerSample.placeholder = agentOwner
    ? 'System Chat is read-only while Agent is active (layout preview only)'
    : 'Ask a question or add sources (layout preview only)';
  composerSample.setAttribute('aria-label', 'System message input, layout preview only');
  document.querySelector('#concept-caption').textContent = processing
    ? 'Process Display uses the contextual detail area. No live job is connected.'
    : state.detail === 'review'
      ? 'Editor / Review is open for ' + sources[state.source].name + '.'
      : state.scanStage === 'result'
        ? 'Illustrative Markdown result in System Chat. Select a source to review it.'
        : 'Review drawer closed. Select a source to open it.';

  if (sourceSearch.value !== state.filter) sourceSearch.value = state.filter;
  const query = state.filter.trim().toLowerCase();
  let visible = 0;
  for (const row of sourceRows) {
    row.hidden = !sources[row.dataset.sourceRow].name.toLowerCase().includes(query);
    if (!row.hidden) visible += 1;
  }
  document.querySelector('#source-visible').textContent = String(visible);
  document.querySelector('#source-empty').hidden = visible !== 0;
  renderReview();
  renderProcess();
}

function closeReview() {
  const sourceButton = sourceButtons.find(button => button.dataset.source === state.source);
  const sourceVisible = !sourceButton.closest('.source-row').hidden;
  commit(
    { detail: 'closed', subview: 'list', focus: 'off' },
    {
      announce: 'Review closed. Back to sources.',
      focus: sourceVisible ? sourceButton : sourceSearch,
    }
  );
}

function drawerReturnFocus() {
  return [document.querySelector('#mobile-sources-toggle'), document.querySelector('#rail-sources-toggle')]
    .find(control => control.getClientRects().length) || document.querySelector('#rail-sources-toggle');
}

function closeSummary(focus = drawerReturnFocus()) {
  suspendedDetail = state.detail === 'closed'
    ? null
    : { detail: state.detail, source: state.source, tab: state.tab, zone: state.zone, subview: state.subview, focus: state.focus };
  commit(
    { right: 'closed', detail: 'closed', zone: 'system', subview: 'list', focus: 'off' },
    { announce: 'System Summarize closed.', focus }
  );
}

function openSummary() {
  const restore = suspendedDetail || {};
  suspendedDetail = null;
  commit(
    { right: 'open', ...restore, zone: 'system' },
    {
      announce: 'System sources drawer open.',
      focus: restore.detail === 'review' ? document.querySelector('#review-heading')
        : restore.detail === 'process' ? document.querySelector('#process-heading') : sourceSearch,
    }
  );
}

function toggleSummary(focus) {
  if (state.right === 'open') closeSummary(focus);
  else openSummary();
}

function startProcess() {
  beforeProcess = {
    detail: state.detail,
    right: state.right,
    source: state.source,
    tab: state.tab,
    zone: state.zone,
    subview: state.subview,
    focus: state.focus,
    scanStage: state.scanStage,
  };
  commit(
    { right: 'open', detail: 'process', scanStage: 'processing', zone: 'system', subview: 'list', focus: 'off' },
    {
      announce: 'Process Display preview open.',
      focus: document.querySelector('#process-heading'),
      scroll: window.matchMedia('(max-width: 900px)').matches,
    }
  );
}

function finishProcess(scanStage = null) {
  const restore = beforeProcess || { detail: 'closed', right: 'closed', zone: 'system', subview: 'list', scanStage: 'result' };
  beforeProcess = null;
  const nextStage = scanStage || restore.scanStage;
  commit({ ...restore, scanStage: nextStage }, {
    announce: restore.detail === 'review' ? 'Review restored.' : 'Process preview closed.',
    focus: restore.detail === 'review'
      ? document.querySelector('#review-heading')
      : document.querySelector('#process-toggle'),
  });
}

function toggleProcess() {
  if (state.scanStage === 'processing') finishProcess();
  else startProcess();
}

function selectScanStage(scanStage) {
  if (scanStage === 'processing') {
    if (state.detail !== 'process') startProcess();
    return;
  }
  if (state.detail === 'process') {
    const restore = beforeProcess || { detail: 'closed', right: 'closed', subview: 'list' };
    beforeProcess = null;
    commit({ ...restore, scanStage, zone: 'system' }, { announce: scanStage + ' layout preview open.' });
    return;
  }
  commit({ scanStage, zone: 'system' }, { announce: scanStage + ' layout preview open.' });
}

function selectOwner(owner) {
  const pane = owner === 'agent' ? agentPane : systemPane;
  if (state.owner === owner && state.zone === owner) {
    focusAfterRender(pane);
    return;
  }
  commit({ owner, zone: owner }, {
    announce: owner === 'agent' ? 'Agent owns this sample session; System controls are read-only.' : 'System owns this sample session.',
    focus: pane,
  });
}
document.querySelector('#summary-close').addEventListener('click', () => closeSummary());
document.querySelector('#process-toggle').addEventListener('click', toggleProcess);
document.querySelector('#rail-agent-toggle').addEventListener('click', () => selectOwner('agent'));
document.querySelector('#rail-system-toggle').addEventListener('click', () => selectOwner('system'));
document.querySelector('#rail-sources-toggle').addEventListener('click', () => {
  toggleSummary(document.querySelector('#rail-sources-toggle'));
});
document.querySelector('#mobile-sources-toggle').addEventListener('click', () => {
  toggleSummary(document.querySelector('#mobile-sources-toggle'));
});
document.querySelector('#rail-coverage-open').addEventListener('click', () => {
  const review = state.detail === 'review' ? state
    : state.detail === 'process' && beforeProcess?.detail === 'review' ? beforeProcess : null;
  if (review) {
    suspendedDetail = {
      detail: 'review', source: review.source, tab: review.tab,
      subview: review.subview, focus: review.focus,
    };
  }
  beforeProcess = null;
  commit(
    { right: 'closed', detail: 'closed', focus: 'off', subview: 'list', scanStage: 'result', resultTab: 'coverage', zone: 'system' },
    {
      announce: 'Illustrative result coverage open.',
      focus: resultTabButtons.find(button => button.dataset.resultTab === 'coverage'),
      scroll: window.matchMedia('(max-width: 900px)').matches,
    }
  );
});
for (const button of scanStageButtons) {
  button.addEventListener('click', () => selectScanStage(button.dataset.scanStageChoice));
}
for (const button of resultTabButtons) {
  button.addEventListener('click', () => {
    commit({ resultTab: button.dataset.resultTab }, { announce: button.textContent + ' result view open.' });
  });
  button.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const current = resultTabButtons.findIndex(tab => tab === document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const index = event.key === 'Home' ? 0
      : event.key === 'End' ? resultTabButtons.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + resultTabButtons.length) % resultTabButtons.length;
    const next = resultTabButtons[index];
    commit({ resultTab: next.dataset.resultTab }, { focus: next, announce: next.textContent + ' result view open.' });
  });
}
document.querySelector('#sample-download').addEventListener('click', () => {
  const blob = new Blob([sampleMarkdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'OneShot-Context.md';
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  announcement.textContent = 'Illustrative Markdown sample downloaded. No System job was run.';
});
processStateSelect.addEventListener('change', () => {
  commit(
    { processState: processStateSelect.value },
    { replace: true, announce: processStates[processStateSelect.value].title + ' preview selected.' }
  );
});

for (const button of sourceButtons) {
  button.addEventListener('click', () => {
    const source = button.dataset.source;
    if (state.detail === 'review' && state.source === source) {
      closeReview();
      return;
    }
    commit(
      { source, detail: 'review', right: 'open', tab: 'read', zone: 'system', subview: 'review', focus: 'off' },
      {
        announce: sources[source].name + ' review opened.',
        focus: document.querySelector('#review-heading'),
        scroll: window.matchMedia('(max-width: 900px)').matches,
      }
    );
  });
}

document.querySelector('#detail-close').addEventListener('click', closeReview);
document.querySelector('#review-back').addEventListener('click', closeReview);
document.querySelector('#review-focus').addEventListener('click', () => {
  const focus = state.focus === 'on' ? 'off' : 'on';
  commit(
    { focus },
    { announce: focus === 'on' ? 'Review focus opened.' : 'Review focus closed.' }
  );
});

for (const button of reviewTabButtons) {
  button.addEventListener('click', () => {
    commit({ tab: button.dataset.reviewTab }, { announce: button.textContent + ' view open.' });
  });
}
document.querySelector('.review-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const enabled = reviewTabButtons.filter(button => !button.disabled);
  const current = enabled.findIndex(button => button === document.activeElement);
  if (current < 0) return;
  event.preventDefault();
  const index = event.key === 'Home' ? 0
    : event.key === 'End' ? enabled.length - 1
      : (current + (event.key === 'ArrowRight' ? 1 : -1) + enabled.length) % enabled.length;
  const next = enabled[index];
  commit({ tab: next.dataset.reviewTab }, { focus: next, announce: next.textContent + ' view open.' });
});

draftInput.addEventListener('input', () => {
  drafts[state.source] = draftInput.value;
  renderReview();
});
document.querySelector('#save-draft').addEventListener('click', () => {
  savedDrafts[state.source] = drafts[state.source];
  renderReview();
  announcement.textContent = 'Sample draft saved in this open preview. No product file was changed.';
});
document.querySelector('#compare-changes').addEventListener('click', () => {
  commit({ tab: 'diff' }, { announce: 'Original and sample draft comparison open.' });
});

sourceSearch.addEventListener('input', () => {
  commit({ filter: sourceSearch.value }, { replace: true });
});
for (const box of scopeBoxes) {
  box.addEventListener('change', () => {
    const scope = scopeBoxes.filter(input => input.checked).map(input => input.value);
    commit(
      { scope },
      { replace: true, announce: scope.length + ' ready sources in sample scope.' }
    );
  });
}

for (const button of mobileZoneButtons) {
  button.addEventListener('click', () => selectOwner(button.dataset.mobileZoneChoice));
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (!document.querySelector('#summary-panel').getClientRects().length) return;
  if (state.detail === 'review') closeReview();
  else if (state.detail === 'process') toggleProcess();
  else closeSummary();
});
window.addEventListener('popstate', event => {
  state = readStateFromUrl();
  restoreHistorySnapshot(event.state);
  render();
  window.history.replaceState(historySnapshot(), '', urlFor(state));
  announcement.textContent = 'Shared layout state restored.';
});

restoreHistorySnapshot(window.history.state);
render();
window.history.replaceState(historySnapshot(), '', urlFor(state));
