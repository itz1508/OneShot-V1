import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import { replayEventPages } from '../workspace.js';

test('replays every page through a terminal job without losing 500-event boundary',async()=>{
  const records=Array.from({length:1001},(_,i)=>({seq:i+1,job_id:'job'}));
  const calls=[];
  const load=async after=>{calls.push(after);return records.filter(x=>x.seq>after).slice(0,500);};
  const result=await replayEventPages(load,0);
  assert.deepEqual(calls,[0,500,1000]);
  assert.equal(result.events.length,1001);
  assert.equal(result.cursor,1001);
  assert.equal(result.complete,true);
});

test('limits catch-up work and returns stable next cursor',async()=>{
  const records=Array.from({length:25},(_,i)=>({seq:i+1}));
  const load=async after=>records.filter(x=>x.seq>after).slice(0,5);
  const first=await replayEventPages(load,0,{pageSize:5,maxPages:2});
  assert.equal(first.complete,false);
  assert.equal(first.cursor,10);
  const second=await replayEventPages(load,first.cursor,{pageSize:5,maxPages:10});
  assert.equal(second.complete,true);
  assert.equal(second.cursor,25);
});

test('rejects duplicate, unordered and invalid replay sequences',async()=>{
  await assert.rejects(()=>replayEventPages(async()=>[{seq:7},{seq:7}],6),/does not advance/);
  await assert.rejects(()=>replayEventPages(async()=>[{seq:1}],-1),/Invalid event cursor/);
});

test('live activity requests a persisted job refresh and exposes connection state',()=>{
  const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
  const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
  assert.match(app,/event\.job_id===state\.jobId && activeJob\(\)/);
  assert.match(app,/pollJob\(\); \/\/ fetch the committed status/);
  assert.match(html,/id="process-connection-status"/);
});
