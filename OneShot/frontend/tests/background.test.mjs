import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
const api=readFileSync(new URL('../api/client.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');

test('System Background report has an accessible separate panel',()=>{
  for(const id of ['background-summary','background-state','background-history','background-patterns']){
    assert.ok(html.includes(`id="${id}"`),id);
  }
  assert.match(html,/aria-label="System Background evaluation"/);
  assert.match(html,/Does not control active work/);
});
test('background reporting is read-only, authenticated through existing same-origin transport',()=>{
  assert.match(api,/background: id => request\(`\/conversations\/\$\{id\}\/background\?limit=5`\)/);
  assert.match(app,/async function refreshBackground/);
  assert.match(app,/stopBackgroundRefresh\(\)/);
  assert.match(app,/report\.learning|report\.patterns/);
  assert.doesNotMatch(api,/ONESHOT_API_TOKEN/);
});
test('DOM update uses textContent not HTML injection for background evidence',()=>{
  const start=app.indexOf('function drawBackground(');
  const end=app.indexOf('async function refreshBackground(',start);
  assert.ok(start>0&&end>start);
  const code=app.slice(start,end);
  assert.match(code,/\.textContent=/);
  assert.doesNotMatch(code,/\.innerHTML|insertAdjacentHTML/);
});
