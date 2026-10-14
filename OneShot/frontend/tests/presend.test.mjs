import test from 'node:test';
import assert from 'node:assert/strict';
import {createPreSendController, draftContextSummary, reviewedMessage, MESSAGE_LIMIT, SUMMARY_LIMIT} from '../presend.js';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';

const ORIGINAL='  Objective: Review this material.\r\nConstraints:\r\n- Preserve accepted decisions.\r\nSome unstructured context.  \r\n';
const cid='a'.repeat(32);

function controller(handler){
  const posted=[];const saved=[];const errors=[];const renders=[];
  const c=createPreSendController({
    send:async (id,text)=>{posted.push([id,text]);return handler?handler(id,text):{id:'m1',content:text};},
    onSaved:(msg,snapshot)=>saved.push([msg,snapshot]),
    onError:e=>errors.push(e.message),
    onChange:s=>renders.push(s)
  });
  return {c,posted,saved,errors,renders};
}

test('literal-only draft does not claim to infer meaning from unlabeled text',()=>{
  assert.equal(draftContextSummary(ORIGINAL), 'Objective:\nReview this material.\n\nConstraints:\n- Preserve accepted decisions.\nSome unstructured context.');
  assert.equal(draftContextSummary('Please summarize this in your own words.'),'');
});

test('cancel closes review and sends zero requests while preserving original',async()=>{
  const {c,posted}=controller();
  c.open({original:ORIGINAL,conversationId:cid});
  assert.equal(c.review.original,ORIGINAL);
  assert.equal(c.cancel(),true);
  assert.equal(c.review,null);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),false);
  assert.deepEqual(posted,[]);
});

test('approval sends exactly the preview payload once; original is verbatim',async()=>{
  const {c,posted,saved}=controller();
  c.open({original:ORIGINAL,conversationId:cid});
  c.editSummary('Reviewer-approved:\n- Keep constraints');
  const exactPreview=c.review.payload;
  assert.equal(exactPreview,reviewedMessage(ORIGINAL,'Reviewer-approved:\n- Keep constraints'));
  assert.ok(exactPreview.endsWith(`Original user input (verbatim):\n${ORIGINAL}`));
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),true);
  assert.deepEqual(posted,[[cid,exactPreview]]);
  assert.equal(saved[0][0].content,exactPreview);
  assert.equal(saved[0][1].original,ORIGINAL);
  assert.equal(c.review,null);
});

test('empty summary sends the unmodified original with no wrappers',async()=>{
  const {c,posted}=controller();
  c.open({original:ORIGINAL,conversationId:cid});c.editSummary('');
  assert.equal(c.review.payload,ORIGINAL);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),true);
  assert.equal(posted[0][1],ORIGINAL);
});

test('changed input or conversation is rejected without any API call',async()=>{
  const {c,posted,errors}=controller();
  c.open({original:ORIGINAL,conversationId:cid});
  assert.equal(await c.approve({currentOriginal:ORIGINAL+' edited',conversationId:cid}),false);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:'b'.repeat(32)}),false);
  assert.equal(posted.length,0);
  assert.equal(errors.length,2);
});

test('concurrent approval clicks cannot post twice or cancel in flight',async()=>{
  let release;
  const {c,posted}=controller((_id,text)=>new Promise(resolve=>{release=()=>resolve({id:'m1',content:text});}));
  c.open({original:ORIGINAL,conversationId:cid});
  const first=c.approve({currentOriginal:ORIGINAL,conversationId:cid});
  assert.equal(c.review.pending,true);
  assert.equal(c.cancel(),false);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),false);
  assert.equal(posted.length,1);
  release();assert.equal(await first,true);
  assert.equal(posted.length,1);
});

test('failed HTTP request retains reviewed draft and original for retry',async()=>{
  let times=0;
  const {c,posted,errors}=controller((_id,text)=>{times++;if(times===1)throw new Error('network failed');return {id:'m2',content:text};});
  c.open({original:ORIGINAL,conversationId:cid});c.editSummary('edited');
  const payload=c.review.payload;
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),false);
  assert.equal(c.review.original,ORIGINAL);
  assert.equal(c.review.payload,payload);
  assert.deepEqual(errors,['network failed']);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),true);
  assert.deepEqual(posted,[[cid,payload],[cid,payload]]);
});

test('saved-content mismatch cannot claim successful approval',async()=>{
  const {c,saved,errors}=controller(async()=>({id:'m1',content:'not the approved text'}));
  c.open({original:ORIGINAL,conversationId:cid});
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),false);
  assert.equal(saved.length,0);assert.equal(c.review.original,ORIGINAL);
  assert.match(errors[0],/differs/);
});

test('limits reject rather than truncate original or summary',()=>{
  assert.throws(()=>reviewedMessage('x'.repeat(MESSAGE_LIMIT),'y'),/exceeds/);
  assert.throws(()=>reviewedMessage('x','y'.repeat(SUMMARY_LIMIT+1)),/too long/);
  const {c}=controller();c.open({original:'x',conversationId:cid});
  assert.throws(()=>c.editSummary('a'.repeat(SUMMARY_LIMIT+1)),/too long/);
});

test('frontend uses one approved API send; accessible modal; no new endpoint',()=>{
  const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
  const html=readFileSync(resolve(root,'index.html'),'utf8');
  const app=readFileSync(resolve(root,'app.js'),'utf8');
  const build=readFileSync(resolve(root,'build.mjs'),'utf8');
  assert.match(html,/id="presend-enabled" type="checkbox"/);
  assert.match(html,/<dialog id="presend-dialog"/);
  assert.match(html,/id="presend-original"/);
  assert.match(html,/id="presend-payload"/);
  assert.match(app,/send:\(conversationId,payload,requestKey\)=>api\.message\(conversationId,payload,requestKey\)/);
  assert.match(app,/preSend\.approve\(\{currentOriginal:\$\('system-input'\)\.value/);
  assert.match(app,/preSend\.cancel\(\)/);
  assert.match(build,/'presend\.js'/);
});

test('fenced code and quoted examples do not become user instructions',()=>{
  const pasted='Objective: Explain this file.\n```yaml\nConstraints: not user requirements\n```\n> Requirements: also quoted\nConstraints:\n- Preserve original text.';
  const result=draftContextSummary(pasted);
  assert.match(result,/Objective:\nExplain this file/);
  assert.match(result,/Constraints:\n- Preserve original text/);
  assert.doesNotMatch(result,/not user requirements|also quoted/);
});

test('uncertain network retry keeps the same stable idempotency key',async()=>{
  const attempts=[];
  let count=0;
  const c=createPreSendController({
    send:async (_cid,content,key)=>{
      attempts.push({content,key});
      if(count++===0)throw new Error('network result unknown');
      return {id:'saved',content};
    }
  });
  c.open({original:ORIGINAL,conversationId:cid});
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),false);
  assert.equal(await c.approve({currentOriginal:ORIGINAL,conversationId:cid}),true);
  assert.equal(attempts.length,2);
  assert.equal(attempts[0].key,attempts[1].key);
  assert.match(attempts[0].key,/^[0-9a-f-]{36}$/);
});

test('modal is native and includes accessible live pending status',()=>{
  const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
  const html=readFileSync(resolve(root,'index.html'),'utf8');
  const js=readFileSync(resolve(root,'app.js'),'utf8');
  assert.match(html,/<dialog id="presend-dialog"/);
  assert.match(html,/id="presend-status" role="status" aria-live="polite"/);
  assert.match(js,/dialog\.showModal\(\)/);
  assert.match(js,/dialog\.addEventListener|\$\('presend-dialog'\)\.addEventListener\('cancel'/);
});
