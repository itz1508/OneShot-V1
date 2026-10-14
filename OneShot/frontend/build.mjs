import { mkdir, rm, copyFile, readFile, stat } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = dirname(fileURLToPath(import.meta.url));
const out = resolve(root, 'dist');
const assets = ['index.html', 'styles.css', 'app.js', 'workspace.js', 'presend.js', 'lifecycle.js', 'api/client.js'];
await rm(out, {recursive:true, force:true});
for(const path of assets) {
  const src = resolve(root,path);
  const target=resolve(out,path);
  if(!(await stat(src)).isFile()) throw new Error(`Missing required source: ${path}`);
  await mkdir(dirname(target), {recursive:true});
  await copyFile(src,target);
}
const html=await readFile(resolve(out,'index.html'),'utf8');
for(const item of ['styles.css','app.js','agent-selector','system-form','source-items','process-view','login-view']) {
  if(!html.includes(item)) throw new Error(`Missing frontend consumer: ${item}`);
}
console.log(`Built ${assets.length} static assets to frontend/dist`);
