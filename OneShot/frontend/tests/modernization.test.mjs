import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
const client=readFileSync(new URL('../api/client.js',import.meta.url),'utf8');

test('Review before Start is a separate approval boundary',()=>{
  assert.match(html,/id="start-review-dialog"/);
  assert.match(html,/id="start-review-sources"/);
  assert.match(app,/function closeStartReview\(/);
  assert.match(app,/async function startJob\(\)/);
  assert.match(app,/async function admitReviewedJob\(\)/);
  assert.match(app,/currentObjective\(\)\?\.id===snapshot\.objectiveId/);
  assert.match(app,/sources\[i\]\?\.sha256===x\.sha256/);
});

test('Unknown admission response uses same idempotency key for identical scope',()=>{
  assert.match(app,/let pendingJobSubmission=null/);
  assert.match(app,/pendingJobSubmission\?\.signature!==signature/);
  assert.match(app,/idempotency_key:pendingJobSubmission\.key/);
  assert.match(app,/pendingJobSubmission=null;\s*state\.activeScopeCount/);
});

test('Evidence UI uses source hashes and recorded versions, not selected current scope',()=>{
  assert.match(client,/artifactEvidenceContent/);
  assert.match(client,/artifactExport/);
  assert.match(app,/api\.artifactEvidence\(state\.conversationId,aid\)/);
  assert.match(app,/api\.artifactEvidenceContent\(state\.conversationId,artifactId,item\.source_id\)/);
  assert.match(app,/evidence\.sources\.filter\(x=>x\.available\)/);
  assert.match(html,/Sources used by this result/);
  assert.match(html,/id="process-coverage"/);
});


test('source scope controls connect to structured API and do not delete originals',()=>{
  assert.match(html,/id="reference-form"/);
  assert.match(html,/id="library-toggle"/);
  assert.match(app,/action:'REFERENCE_SOURCE'/);
  assert.match(app,/action:'REMOVE_SOURCE'/);
  assert.match(app,/action:'ADD_SOURCE'/);
  assert.match(client,/availableSources/);
});

test('visible Apply requires server prepare confirm and verified final readback',()=>{
  assert.match(html,/id="apply-controls"/);
  assert.match(html,/id="apply-dialog"/);
  assert.match(app,/async function reviewApply\(/);
  assert.match(app,/async function confirmReviewedApply\(/);
  assert.match(app,/api\.applyPrepare\(/);
  assert.match(app,/api\.applyConfirm\(/);
  assert.match(app,/api\.appliedReadback\(/);
  assert.match(client,/appliedReadback/);
});


test('source-only requested action does not automatically invoke generation',()=>{
  assert.match(html,/id="requested-operation"/);
  assert.match(html,/value="inspect_sources"/);
  assert.match(app,/operation:snapshot.operation/);
  assert.match(app,/\$\('requested-operation'\).value===snapshot.operation/);
});


test('summary-only output is separately enabled for a real configured System model',()=>{
  assert.match(html,/value="summarize"/);
  assert.match(html,/id="summary-export"/);
  assert.match(app,/caps\.auto_generator\?\.provider==='evidence'/);
  assert.match(app,/api\.summaryExport/);
  assert.match(client,/summaryExport/);
});
