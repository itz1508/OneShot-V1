import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { startBlocker, shouldShowProcess, nextCursor, isTerminal } from '../workspace.js';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const html=readFileSync(resolve(root,'index.html'),'utf8');
const app=readFileSync(resolve(root,'app.js'),'utf8');
const api=readFileSync(resolve(root,'api/client.js'),'utf8');
const css=readFileSync(resolve(root,'styles.css'),'utf8');

test('layout owns four logical regions, fifth replaces review slot',()=>{
  for(const id of ['agent-drawer','system-messages','source-items','review-view','process-view'])assert.ok(html.includes(`id="${id}"`),id);
  assert.match(html,/<div id="process-view"[^>]*hidden>/);
  assert.match(app,/show\('review-view',false\)/);
  assert.match(app,/show\('process-view',true\)/);
});
test('optional Agents use server-listed integrations and independent banner control',()=>{
  assert.match(html,/<select id="agent-selector" disabled/);
  assert.match(html,/<button id="agent-toggle"[^>]*aria-controls="agent-drawer"/);
  assert.match(html,/<aside id="settings-panel"[^>]*>[\s\S]*?<h3>Integrations<\/h3>/);
  assert.match(html,/id="agent-form"/);
  assert.match(html,/id="agent-deactivate"/);
  assert.match(app,/api\.capabilities\(\)/);
  assert.match(app,/api\.agentReply\(/);
  assert.match(app,/api\.agentSession\(/);
  assert.match(app,/function closeMenu\(/);
  assert.match(app,/\$\('agent-toggle'\)\.onclick/);
  assert.doesNotMatch(api,/Bearer |ONESHOT_API_TOKEN|sk-proj/);
});
test('source selection differs from review and explicit start',()=>{
  assert.match(app,/checkbox\.addEventListener\('change'/);
  assert.match(app,/name\.addEventListener\('click'/);
  assert.match(app,/state\.opened===src\.id/);
  assert.match(app,/api\.job\(state\.conversationId,body\)/);
});
test('start is blocked without accepted selection and with unsaved drafts',()=>{
  const base={connected:true,selected:['a'],dirty:new Set(),pending:false,sessionActive:false,promptMessageId:'a'.repeat(32)};
  assert.equal(startBlocker(base),null);
  assert.match(startBlocker({...base,promptMessageId:null}),/System objective/);
  assert.match(startBlocker({...base,unsentPrompt:true}),/unsent System message/);
  assert.match(startBlocker({...base,selected:[]}),/Select/);
  assert.match(startBlocker({...base,dirty:new Set(['a'])}),/Save draft/);
  assert.match(startBlocker({...base,connected:false}),/unavailable/);
  assert.match(startBlocker({...base,sessionActive:true}),/read-only/);
  assert.match(startBlocker({...base,pending:true}),/in progress/);
});
test('process display requires accepted, active job and no manual focus switch',()=>{
  const s={accepted:true,status:'queued',userChangedDetail:false};
  assert.equal(shouldShowProcess(s),true);
  assert.equal(shouldShowProcess({...s,status:'running'}),true);
  assert.equal(shouldShowProcess({...s,accepted:false}),false);
  assert.equal(shouldShowProcess({...s,status:'completed'}),false);
  assert.equal(shouldShowProcess({...s,userChangedDetail:true}),false);
  assert.equal(isTerminal('blocked'),true);assert.equal(isTerminal('failed'),true);
});
test('event cursor uses server sequence and never regresses',()=>{
  assert.equal(nextCursor(5,[{seq:4},{seq:6},{seq:6},{seq:3}]),6);
  assert.equal(nextCursor(14,[]),14);
});
test('browser source uses same-origin API, no embedded API token or invented progress',()=>{
  assert.match(api,/fetch\('\/api' \+ path/);
  assert.doesNotMatch(api,/Bearer |ONESHOT_API_TOKEN|sk-proj/);
  assert.doesNotMatch(app,/fakeProgress|setTimeout\([^)]*progress|Math\.random\(\)/);
  assert.match(app,/replayEventPages\(/);
  assert.match(app,/api\.events\(cid,after\)/);
  assert.match(css,/prefers-reduced-motion:reduce/);
});

test('Start click rechecks saved objective and unsent text, not only disabled state',()=>{
  assert.match(app,/function processingBlocker\(/);
  assert.match(app,/function refreshStart\(\) \{\s*const reason=processingBlocker\(\)/);
  assert.match(app,/async function startJob\(\)\{[^\n]*const reason=processingBlocker\(selected\)/);
  assert.match(app,/promptMessageId:currentObjective\(\)\?\.id/);
  assert.match(app,/unsentPrompt:!!\$\('system-input'\)\.value\.trim\(\)/);
});

test('input context preview shows only saved objective and checked original scopes',()=>{
  assert.match(html,/id="context-preview-items"/);
  assert.match(html,/This is a scope preview, not a semantic summary/);
  assert.match(app,/function drawContextPreview\(\)/);
  assert.match(app,/state\.sources\.filter\(s=>state\.selected\.has\(s\.id\)\)/);
  assert.match(app,/Earlier conversation: bounded reference only/);
  assert.match(app,/item\.textContent=text/);
});
