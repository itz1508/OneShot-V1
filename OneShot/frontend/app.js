import { api } from './api/client.js';
import { startBlocker, shouldShowProcess, isTerminal, replayEventPages } from './workspace.js';
import { createPreSendController } from './presend.js';

const state = {
  connected: false, authenticated:false, conversationId: null, agentActive: false, messages: [],
  sources: [], selected: new Set(), opened: null, contents: new Map(), drafts: new Map(), dirty: new Set(),
  jobId: null, jobStatus: null, artifactId: null, cursor: 0, jobEvents: [], trace: null,
  accepted: false, userChangedDetail: false, view: 'review', displayArtifact: false,
  polling: null, foregroundScheduled: null, backgroundTimer: null, backgroundStream: null,
  backgroundScheduled: null, backgroundBusy: false, busy: false,
  agentOptions: [], agentSelected: null, agentPending: false
};
const $ = id => document.getElementById(id);
const show = (id, visible) => { $(id).hidden = !visible; };
function notify(message, error=false) { const el=$('notice'); el.textContent=message; el.dataset.error=String(error); }
function err(e) { notify(e instanceof Error ? e.message : String(e), true); }
function toggle(id,button) { const isOpen=$(id).hidden; show(id,isOpen); $(button).setAttribute('aria-expanded',String(isOpen)); }
function getDraft(id) { return state.drafts.get(id); }
function activeJob() { return state.accepted && ['queued','running'].includes(state.jobStatus); }
function currentObjective() { return [...state.messages].reverse().find(m=>m.channel==='system' && m.id && m.content?.trim()); }
function showObjective() {
  const message=currentObjective();
  $('processing-objective').textContent=message ? message.content : 'Send a System message to set the objective.';
  drawContextPreview();
}
function drawContextPreview() {
  const items=$('context-preview-items');items.replaceChildren();
  const objective=currentObjective();
  const selected=state.sources.filter(s=>state.selected.has(s.id));
  const lines=[
    objective ? `Current saved request: ${objective.id.slice(0,8)} (verbatim)` : 'Current saved request: none',
    `Selected originals: ${selected.length}${selected.length ? ' · '+selected.map(s=>s.name).join(', ') : ''}`,
    `Unselected sources excluded: ${state.sources.length-selected.length}`,
    'Earlier conversation: bounded reference only; never replaces current request',
  ];
  for(const text of lines){const item=document.createElement('li');item.textContent=text;items.append(item);}
}
function processingBlocker(selected=[...state.selected]) {
  return startBlocker({connected:state.connected,selected,dirty:state.dirty,
    pending:activeJob() || state.busy,sessionActive:state.agentActive,
    promptMessageId:currentObjective()?.id,unsentPrompt:!!$('system-input').value.trim()});
}
function refreshStart() {
  const reason=processingBlocker();
  $('start-button').disabled=!!reason;
  $('start-button').title=reason || 'Run with selected original source versions';
}
function updateConnection() {
  $('connection-state').textContent=state.connected?'System connected':'System unavailable';
  $('connection-state').classList.toggle('offline',!state.connected);
  $('session-state').textContent=!state.connected?'Unavailable':(state.agentActive?'Read-only':'System active');
  $('system-input').disabled=!state.connected || state.agentActive;
  $('send-system').disabled=!state.connected || state.agentActive;
  $('agent-selector').disabled=!state.connected || !state.agentOptions.length || state.agentPending;
  $('agent-deactivate').disabled=!state.connected || !state.agentActive || state.agentPending;
  $('agent-input').disabled=!state.connected || !state.agentActive || !state.agentSelected || state.agentPending;
  $('agent-send').disabled=$('agent-input').disabled;
  refreshStart();
}
const runHistory = { page:0, size:10, sequence:0, timer:null, loading:false };
function renderRunHistory(data){
  const list=$('run-history-list');list.replaceChildren();
  const total=data.total;
  $('run-history-count').textContent=total ? `${total} matching recorded run${total===1?'':'s'}` : 'No matching recorded runs';
  $('run-history-page').textContent=`Page ${runHistory.page+1}`;
  $('run-history-previous').disabled=runHistory.page===0;
  $('run-history-next').disabled=(runHistory.page+1)*runHistory.size>=total;
  for(const job of data.items){
    const item=document.createElement('li');item.dataset.status=job.status;
    const open=document.createElement('button');open.type='button';open.className='run-history-open';
    open.textContent=`${job.operation.replaceAll('_',' ')} · ${job.id.slice(0,8)}`;
    open.setAttribute('aria-label',`Review ${job.operation.replaceAll('_',' ')} job ${job.id}`);
    open.addEventListener('click',()=>openHistoryJob(job.id));
    const status=document.createElement('span');status.className='run-history-meta run-history-status';
    status.textContent=`${job.status==='blocked'?'Unable to process':job.status} · ${job.created_at}`;
    const objective=document.createElement('span');objective.className='run-history-meta';
    objective.textContent=job.objective_preview || 'No recorded objective';
    const sources=document.createElement('span');sources.className='run-history-meta';
    sources.textContent=(job.sources||[]).map(x=>`${x.name} (v${x.version})`).join(', ') || 'No scoped sources';
    item.append(open,status,objective,sources);
    if(job.reason){const failure=document.createElement('span');failure.className='run-history-meta';failure.textContent=`Reason: ${job.reason}`;item.append(failure);}
    list.append(item);
  }
}
async function refreshRunHistory(){
  if(!state.connected||!state.conversationId)return;
  const cid=state.conversationId,sequence=++runHistory.sequence;
  const query=$('run-history-search').value.trim(),status=$('run-history-status').value;
  const offset=runHistory.page*runHistory.size;
  $('run-history-count').textContent='Searching recorded runs…';
  try{
    const result=await api.jobs(cid,{query,status,limit:runHistory.size,offset});
    if(sequence!==runHistory.sequence||cid!==state.conversationId)return;
    if(offset && offset>=result.total){runHistory.page=Math.max(0,Math.ceil(result.total/runHistory.size)-1);return refreshRunHistory();}
    renderRunHistory(result);
  }catch(error){
    if(sequence!==runHistory.sequence||cid!==state.conversationId)return;
    $('run-history-count').textContent=`Cannot retrieve run history: ${error.message}`;
    $('run-history-list').replaceChildren();
    $('run-history-next').disabled=true;$('run-history-previous').disabled=true;
  }
}
async function openHistoryJob(id){
  if(activeJob() && state.jobId!==id){notify('Current processing is active. Wait for its actual terminal outcome before switching the review.',true);return;}
  const cid=state.conversationId;
  try{
    const [job,history]=await Promise.all([api.jobStatus(cid,id),api.traceEvents(cid,id)]);
    if(cid!==state.conversationId || (activeJob() && state.jobId!==id))return;
    if(state.polling){clearInterval(state.polling);state.polling=null;}
    state.jobId=id;state.jobStatus=job.status;state.artifactId=job.artifact_id;
    state.accepted=true;state.activeScopeCount=job.scope.length;
    state.trace={...history,events:[]};state.jobEvents=history.events.slice(-500);
    state.cursor=history.events.at(-1)?.seq || 0;
    state.userChangedDetail=true;state.displayArtifact=false;
    $('job-summary').textContent=`Job ${id.slice(0,8)} · ${job.status}${job.error?': '+job.error:''}`;
    show('open-result',!!job.artifact_id);
    show('improvement-loop',true);
    await renderImprovementLoopForJob(id);
    processView();drawProcess();refreshStart();
    if(!isTerminal(job.status)){await pollJob();if(activeJob())state.polling=setInterval(pollJob,850);}
  }catch(error){err(error);}
}

function drawBackground(report) {
  const status=$('background-state');
  const summary=report.summary || {total:0,states:{}};
  const states=summary.states || {};
  const stages=['queued','running','completed','skipped','failed'].filter(key=>states[key]);
  status.textContent=!report.execution_enabled ? 'Background disabled' : summary.total ? stages.map(key=>`${states[key]} ${key}`).join(' · ') : 'No recorded evaluations';
  const history=$('background-history');history.replaceChildren();
  for(const evaluation of report.evaluations || []) {
    const item=document.createElement('li');item.dataset.status=evaluation.status;
    const outcome=evaluation.result?.outcome || evaluation.result?.reason || evaluation.error_code || 'pending';
    item.textContent=`Job ${evaluation.job_id.slice(0,8)} · ${evaluation.status} · ${outcome}`;
    history.append(item);
  }
  const patterns=report.patterns || [];
  $('background-patterns').textContent=patterns.length
    ? patterns.map(p=>`${p.count} × ${p.code} (proposal only)`).join(' · ')
    : 'No verified recurring patterns. No automatic policy changes.';
}
async function refreshBackground() {
  if(!state.connected || !state.conversationId || state.backgroundBusy)return;
  state.backgroundBusy=true;
  try { drawBackground(await api.background(state.conversationId)); }
  catch (error) { $('background-state').textContent='Evaluation status unavailable'; }
  finally { state.backgroundBusy=false; }
}
function backgroundFallback(){
  const indicator=$('process-connection-status');
  if(indicator)indicator.textContent='Event stream reconnecting; status checks remain active';
  if(!state.backgroundTimer)state.backgroundTimer=setInterval(refreshBackground,5000);
}
function stopBackgroundRefresh(){
  if(state.backgroundTimer){clearInterval(state.backgroundTimer);state.backgroundTimer=null;}
  if(state.backgroundScheduled){clearTimeout(state.backgroundScheduled);state.backgroundScheduled=null;}
  if(state.foregroundScheduled){clearTimeout(state.foregroundScheduled);state.foregroundScheduled=null;}
  if(state.backgroundStream){state.backgroundStream.close();state.backgroundStream=null;}
}
function startBackgroundRefresh(){
  stopBackgroundRefresh();refreshBackground();
  // Observed SSE events provide prompt status changes; reconnect is native to
  // EventSource. The read-only polling fallback remains for unavailable SSE.
  if(typeof EventSource==='undefined'){backgroundFallback();return;}
  const connection=new EventSource(`/api/conversations/${state.conversationId}/events/stream?after=${state.cursor}`);
  state.backgroundStream=connection;
  connection.addEventListener('activity',message=>{
    let event;
    try{event=JSON.parse(message.data);}catch{return;}
    if(event.job_id===state.jobId && activeJob() && !state.foregroundScheduled){
      state.foregroundScheduled=setTimeout(()=>{
        state.foregroundScheduled=null;
        pollJob(); // fetch the committed status + paginated journal; never trust SSE alone
      },125);
    }
    if(!event.kind?.startsWith('background_'))return;
    if(state.backgroundScheduled)return;
    state.backgroundScheduled=setTimeout(()=>{
      state.backgroundScheduled=null;
      refreshBackground();
    },150);
  });
  connection.onopen=()=>{
    const indicator=$('process-connection-status');
    if(indicator)indicator.textContent='Event stream connected';
    if(state.backgroundTimer){clearInterval(state.backgroundTimer);state.backgroundTimer=null;}
  };
  connection.onerror=backgroundFallback;
}
function messageUI() {
  const pane=$('system-messages');pane.replaceChildren();
  if(!state.messages.some(x=>x.channel==='system')){const p=document.createElement('p');p.className='empty';p.textContent='No System messages yet.';pane.append(p);showObjective();refreshStart();return;}
  for(const m of state.messages.filter(x=>x.channel==='system')) {
    const article=document.createElement('article');article.className='message';
    const p=document.createElement('p');p.textContent=m.content;article.append(p);pane.append(article);
  }
  pane.scrollTop=pane.scrollHeight;
  showObjective();refreshStart();
}
function renderAgents() {
  const select=$('agent-selector'), inventory=$('integration-inventory');
  select.replaceChildren();inventory.replaceChildren();
  if(!state.agentOptions.length) {
    const option=document.createElement('option');option.value='';option.textContent='No configured Agents';select.append(option);
    inventory.textContent='No optional Agent provider configured.';
  } else {
    for(const provider of state.agentOptions) {
      const option=document.createElement('option');option.value=provider.id;
      option.textContent=`${provider.id} · ${provider.model}`;select.append(option);
      const info=document.createElement('p');info.textContent=`${provider.id}: ${provider.model} · configured on server`;
      info.className='small';inventory.append(info);
    }
    if(!state.agentSelected || !state.agentOptions.some(x=>x.id===state.agentSelected)){
      state.agentSelected=state.agentOptions[0].id;
    }
    select.value=state.agentSelected;
  }
  drawAgentMessages();updateConnection();
}
function drawAgentMessages() {
  const pane=$('agent-messages');pane.replaceChildren();
  const messages=state.messages.filter(x=>x.channel==='agent');
  if(!messages.length){const text=document.createElement('p');text.className='empty';
    text.textContent=state.agentOptions.length?'Agent chat is ready. Your sources and System context are not sent automatically.':'No configured Agent. System Chat remains available.';
    pane.append(text);return;}
  for(const message of messages) {
    const item=document.createElement('article');item.className='message agent-message';
    item.dataset.role=message.role||'user';
    const header=document.createElement('strong');header.textContent=item.dataset.role==='assistant'?'Agent':'You';
    const content=document.createElement('p');content.textContent=message.content;
    item.append(header,content);pane.append(item);
  }
  pane.scrollTop=pane.scrollHeight;
}
async function activateAgent(){
  if(!state.agentOptions.length||!state.connected)return;
  try{const response=await api.agentSession(state.conversationId,true);
    state.agentActive=response.agent_active;renderAgents();notify('Agent session active. System Chat is read-only.');}
  catch(error){err(error);renderAgents();}
}
async function deactivateAgent(){
  if(!state.connected)return;
  try{const response=await api.agentSession(state.conversationId,false);
    state.agentActive=response.agent_active;renderAgents();notify('Agent deactivated. System Chat has full access.');}
  catch(error){err(error);}
}
let agentRequestIdentity=null;
async function sendAgent(e){
  e.preventDefault();if(!state.connected||!state.agentActive||!state.agentSelected||state.agentPending)return;
  const editor=$('agent-input'), content=editor.value;if(!content.trim())return;
  if(!agentRequestIdentity || agentRequestIdentity.content!==content || agentRequestIdentity.provider!==state.agentSelected){
    agentRequestIdentity={content,provider:state.agentSelected,key:crypto.randomUUID()};
  }
  state.agentPending=true;updateConnection();$('agent-status').textContent='Waiting for the configured provider…';
  try{const result=await api.agentReply(state.conversationId,{
    provider:agentRequestIdentity.provider,content,idempotency_key:agentRequestIdentity.key});
    const loaded=await api.conversation(state.conversationId);state.messages=loaded.messages;
    agentRequestIdentity=null;if(editor.value===content)editor.value='';drawAgentMessages();
    $('agent-status').textContent=`Reply retained · ${result.provider}`;
  }catch(error){$('agent-status').textContent='Reply not confirmed. Retrying the same message reconciles server state.';err(error);}
  finally{state.agentPending=false;updateConnection();}
}
function drawSources() {
  const list=$('source-items');list.replaceChildren();
  $('source-count').textContent=`${state.selected.size} of ${state.sources.length}`;
  if(!state.sources.length){const p=document.createElement('p');p.className='empty';p.textContent='No sources attached.';list.append(p);drawContextPreview();refreshStart();return;}
  for(const src of state.sources){
    const row=document.createElement('div');row.className='source-row';if(state.opened===src.id && !state.displayArtifact)row.classList.add('is-open');
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=state.selected.has(src.id);
    checkbox.setAttribute('aria-label',`Select ${src.name} for processing`);checkbox.addEventListener('change',()=>{if(checkbox.checked)state.selected.add(src.id);else state.selected.delete(src.id);drawSources();});
    const name=document.createElement('button');name.type='button';name.className='source-name';name.textContent=src.name;
    name.title=src.kind==='reference'?'Reference not yet fetched':'Review original source';name.addEventListener('click',()=>openSource(src));
    const status=document.createElement('span');status.className='source-kind';status.textContent=src.sha256?'v'+src.version:'unfetched';
    const remove=document.createElement('button');remove.type='button';remove.className='source-remove secondary';
    remove.textContent='Remove';remove.setAttribute('aria-label',`Remove ${src.name} from current scope`);
    remove.disabled=!state.connected||state.agentActive;
    remove.addEventListener('click',()=>removeSourceFromScope(src));
    row.append(checkbox,name,status,remove);list.append(row);
  }
  drawContextPreview();
  refreshStart();
}
function reviewView(){state.view='review';show('process-view',false);show('review-view',true);}
function processView(){state.view='process';show('process-view',true);show('review-view',false);}
function resetReview(){state.opened=null;state.displayArtifact=false;show('editor-wrapper',false);show('artifact-view',false);show('review-empty',true);$('review-label').textContent='No file open';drawSources();}
function _formatAutosaveTime(ms){
  if(!ms)return '';
  const d=new Date(ms);
  const hh=String(d.getHours()).padStart(2,'0'),mm=String(d.getMinutes()).padStart(2,'0'),ss=String(d.getSeconds()).padStart(2,'0');
  return `${hh}:${mm}:${ss}`;
}
function refreshDraftUI(){
  const d=getDraft(state.opened);if(!d)return;
  if(document.activeElement!==$('editor-input'))$('editor-input').value=d.text;
  const dirty=state.dirty.has(state.opened);
  let label;
  if(d.autosaveState==='saving')label='Autosaving…';
  else if(d.autosaveState==='failed')label='Autosave failed — will retry';
  else if(d.autosaveState==='conflict')label='Draft conflict — reload the source to sync';
  else if(dirty)label='Unsaved draft changes';
  else if(d.revision)label=`Draft revision ${d.revision} saved${d.autosavedAt?` · autosaved ${_formatAutosaveTime(d.autosavedAt)}`:''}`;
  else label='Original source · unchanged';
  $('draft-state').textContent=label;
  $('save-draft').disabled=!dirty || !state.connected;
  refreshStart();
}
async function openSource(src){
  state.userChangedDetail=!!activeJob();
  if(state.opened===src.id && !state.displayArtifact){resetReview();reviewView();return;}
  state.opened=src.id;state.displayArtifact=false;reviewView();show('artifact-view',false);
  $('review-label').textContent=src.name;show('review-empty',false);
  if(!src.sha256){show('editor-wrapper',false);$('review-empty').replaceChildren();$('review-empty').textContent='Reference was not fetched and cannot be reviewed.';show('review-empty',true);drawSources();return;}
  show('editor-wrapper',false);
  try {
    let d=getDraft(src.id);
    if(!d){const raw=await api.sourceContent(state.conversationId,src.id);const text=new TextDecoder('utf-8',{fatal:true}).decode(raw);
      d={text,original:text,revision:null,draftId:null};state.drafts.set(src.id,d);}
    if(state.opened!==src.id)return;
    show('editor-wrapper',true);$('editor-file').textContent=src.name;
    $('editor-integrity').textContent='Verified original';refreshDraftUI();
  }catch(e){if(state.opened===src.id){show('review-empty',true);$('review-empty').textContent='This source cannot be displayed as UTF-8 text.';}err(e);}
  drawSources();
}
function setProcessPanel(){
  if(shouldShowProcess({accepted:state.accepted,status:state.jobStatus,userChangedDetail:state.userChangedDetail})) processView();
  else reviewView();
}
function drawProcess(){
  $('process-job').textContent=`Job ${state.jobId || '—'} · ${state.jobStatus || '—'}`;
  const observations=new Map();
  for(const event of state.jobEvents){
    if(event.kind==='source_inspected' && event.payload?.source_id)observations.set(event.payload.source_id,event.payload.coverage);
  }
  const selected=state.activeScopeCount ?? state.selected.size;
  const blocked=[...observations.values()].filter(v=>v==='blocked').length;
  $('process-coverage').textContent=`Source coverage: ${observations.size} / ${selected} inspected${blocked?` · ${blocked} blocked`:''}`;
  const coverage=[...state.jobEvents].reverse().find(e=>e.kind==='coverage_assessed');
  if(coverage?.payload){
    const info=coverage.payload;
    $('process-coverage').textContent+=` · ${info.structural_state} (${info.readable_source_count}/${info.selected_source_count} readable; semantic sufficiency not evaluated)`;
    if(info.missing?.length)$('process-coverage').textContent+=` · ${info.missing.length} unavailable`;
  }
  const latest=state.jobEvents.at(-1);
  $('process-last-update').textContent=latest?.created_at?`Last confirmed update: ${latest.created_at}`:'Last confirmed update: awaiting events';
  const area=$('process-nodes');area.replaceChildren();
  if(state.trace?.nodes?.length){for(const node of state.trace.nodes){const item=document.createElement('div');item.className='node';item.dataset.status=node.status;const title=document.createElement('strong');title.textContent=node.id.replaceAll('_',' ');const status=document.createElement('span');status.textContent=node.status;item.append(title,status);area.append(item);}}
  const history=$('process-events');history.replaceChildren();
  for(const e of state.jobEvents.slice(-35)){
    const li=document.createElement('li');const label=document.createElement('b');label.textContent=e.kind.replaceAll('_',' ');
    li.append(label,document.createTextNode(` · ${e.node_id || e.edge_id || 'job'} · #${e.seq}`));history.append(li);
  }
}
async function removeSourceFromScope(src){
  if(!state.connected||state.agentActive)return;
  try{const result=await api.attach(state.conversationId,{action:'REMOVE_SOURCE',source_id:src.id});
    if(!result.detached||result.deleted)throw new Error('Source detachment was not confirmed');
    if(state.opened===src.id){resetReview();reviewView();}
    await refreshSources();notify(`${src.name} removed from this scope. Original retained.`);
    if(!$('library-items').hidden)await refreshLibrary();
  }catch(error){err(error);}
}
async function refreshLibrary(){
  if(!state.connected)return;
  const available=await api.availableSources(state.conversationId);
  const parent=$('library-items');parent.replaceChildren();
  if(!available.length){const p=document.createElement('p');p.className='small';p.textContent='No detached sources available.';parent.append(p);return;}
  for(const item of available){
    const row=document.createElement('div');row.className='source-row';
    const label=document.createElement('span');label.textContent=`${item.name} · v${item.version}`;
    const add=document.createElement('button');add.className='secondary';add.type='button';add.textContent='Add';
    add.disabled=state.agentActive;
    add.addEventListener('click',async()=>{add.disabled=true;
      try{await api.attach(state.conversationId,{action:'ADD_SOURCE',source_id:item.id});
        await refreshSources();await refreshLibrary();notify('Existing original reattached to source scope.');}
      catch(error){err(error);add.disabled=false;}});
    row.append(label,add);parent.append(row);
  }
}
async function refreshSources(){state.sources=await api.sources(state.conversationId);const valid=new Set(state.sources.map(x=>x.id));for(const id of state.selected)if(!valid.has(id))state.selected.delete(id);drawSources();}
async function boot(){
  try{
    await api.session();
    state.authenticated=true;
    show('login-view',false);show('workspace',true);
    let cid=sessionStorage.getItem('oneshot_conversation_id');let data;
    if(cid){try{data=await api.conversation(cid);}catch(e){if(e.status!==404)throw e;sessionStorage.removeItem('oneshot_conversation_id');cid=null;}}
    if(!cid){const created=await api.createConversation();cid=created.id;sessionStorage.setItem('oneshot_conversation_id',cid);data=await api.conversation(cid);}
    state.conversationId=cid;state.connected=true;state.agentActive=data.agent_active;state.messages=data.messages;
    const caps=await api.capabilities();state.agentOptions=caps.agent_integrations || [];state.capabilities=caps;
    const summaryOption=$('requested-operation').querySelector('option[value="summarize"]');
    summaryOption.disabled=caps.auto_generator?.provider==='evidence';
    summaryOption.title=summaryOption.disabled?'Configure a System model to enable semantic summarization':'';
    renderAgents();messageUI();await refreshSources();updateConnection();startBackgroundRefresh();await refreshRunHistory();await loadPrompts();notify('System connected. No Agent integration is required.');
  }catch(e){
    state.connected=false;stopBackgroundRefresh();updateConnection();
    if(e.status===401){state.authenticated=false;show('workspace',false);show('login-view',true);$('connection-state').textContent='Sign in required';$('login-error').textContent='';}
    else {notify('System connection failed: '+e.message,true);if(!state.authenticated){show('workspace',false);show('login-view',true);}}
  }
}
// The review is a frontend-only approval boundary. OneShot System remains the sole
// owner of saved messages; no Agent or backend summarization endpoint is introduced.
let previousReviewFocus=null;
let directSendIdentity=null;
function renderPreSendReview(review){
  const visible=!!review;
  const dialog=$('presend-dialog');
  if(!visible){
    if(dialog.open)dialog.close();
    $('presend-error').textContent='';
    if(previousReviewFocus?.isConnected)previousReviewFocus.focus();
    $('presend-status').textContent='';
    previousReviewFocus=null;
    return;
  }
  if(!dialog.open)dialog.showModal();
  dialog.setAttribute('aria-busy',review.pending?'true':'false');
  $('presend-status').textContent=review.pending?'Saving the approved message…':'';
  const summary=$('presend-summary');
  if(summary.value!==review.summary)summary.value=review.summary;
  $('presend-original').textContent=review.original;
  $('presend-payload').textContent=review.payload;
  summary.disabled=review.pending;
  $('presend-cancel').disabled=review.pending;
  // Keep the approval control focusable while pending; a disabled last control
  // leaves no tabbable content in the dialog, causing focus escape.
  $('presend-approve').setAttribute('aria-disabled',review.pending?'true':'false');
  $('presend-approve').textContent=review.pending?'Sending…':'Approve and send';
}
const preSend=createPreSendController({
  send:(conversationId,payload,requestKey)=>api.message(conversationId,payload,requestKey),
  onSaved:(saved,approved)=>{
    if(state.conversationId!==approved.conversationId){
      notify('Message saved in the previous conversation; reopen that conversation to review it.',true);return;
    }
    state.messages.push(saved);
    // Original composer contents are untouched until the approved response is saved.
    if($('system-input').value===approved.original)$('system-input').value='';
    messageUI();
    notify('Reviewed System message saved. Processing has not started.');
  },
  onError:error=>{$('presend-error').textContent=error.message;err(error);},
  onChange:renderPreSendReview
});
function cancelPreSendReview(){preSend.cancel();}
async function sendSystem(e){
  e.preventDefault();
  if(!state.connected||state.agentActive||preSend.review)return;
  const editor=$('system-input');
  const content=editor.value;
  if(!content.trim())return;
  if($('presend-enabled').checked){
    try{
      previousReviewFocus=document.activeElement;
      preSend.open({original:content,conversationId:state.conversationId});
      $('presend-error').textContent='';
      $('presend-summary').focus();
    }catch(error){err(error);}
    return;
  }
  // Existing direct-send behavior, preserving exact input whitespace.
  const button=$('send-system');editor.disabled=true;button.disabled=true;
  if(!directSendIdentity || directSendIdentity.content!==content || directSendIdentity.cid!==state.conversationId){
    directSendIdentity={cid:state.conversationId,content,key:crypto.randomUUID()};
  }
  try{
    const saved=await api.message(state.conversationId,content,directSendIdentity.key);
    if(saved.content!==content)throw new Error('Saved message differs from submitted input; verify server state.');
    state.messages.push(saved);directSendIdentity=null;if(editor.value===content)editor.value='';messageUI();
  }catch(error){err(error);}
  finally{editor.disabled=!state.connected||state.agentActive;button.disabled=editor.disabled;refreshStart();}
}
async function attachPaste(e){e.preventDefault();if(!state.connected)return notify('System unavailable',true);
  const name=$('paste-name').value.trim();const content=$('paste-content').value;
  if(!name||!content.trim())return notify('Provide source name and content',true);
  try{await api.attach(state.conversationId,{action:'INPUT_SOURCE',name,content});show('paste-form',false);$('paste-content').value='';await refreshSources();notify('Source attached. No processing has started.');}catch(e){err(e);}
}
function base64(bytes){let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.slice(i,i+8192));return btoa(s);}
async function attachFile(){if(!state.connected)return notify('System unavailable',true);
  const file=$('file-input').files?.[0];if(!file)return;
  const textRe=/\.(txt|md|py|ts|tsx|js|jsx|json|toml|yaml|yml|csv|html|css|xml|log)$/i;
  const imageRe=/\.(png|jpe?g|webp)$/i;
  const isText=textRe.test(file.name), isImage=imageRe.test(file.name);
  if(!(isText||isImage)||file.size>8_000_000){$('file-input').value='';return notify('Only supported text (≤1 MB) or image (≤8 MB, PNG/JPEG/WebP) files can be attached.',true);}
  if(isImage && !state.capabilities?.vision?.configured){
    $('file-input').value='';return notify('Image attached but no local Visual provider is configured. Set ONESHOT_VISION_PROVIDER=llama and restart to enable.',true);
  }
  try{const bytes=new Uint8Array(await file.arrayBuffer());
    if(isText){ new TextDecoder('utf-8',{fatal:true}).decode(bytes); }
    await api.attach(state.conversationId,{action:'IMPORT_SOURCE',name:file.name,content_base64:base64(bytes)});
    await refreshSources();notify(`${isImage?'Image':'File'} attached. No processing has started.`);}
  catch(e){err(e);}finally{$('file-input').value='';}
}
const AUTOSAVE_DEBOUNCE_MS = 900;
async function _persistDraft(id, draft){
  const response=draft.draftId
    ?await api.updateDraft(state.conversationId,draft.draftId,{expected_revision:draft.revision,content:draft.text})
    :await api.createDraft(state.conversationId,{source_id:id,content:draft.text});
  draft.draftId=response.id;draft.revision=response.revision;draft.autosavedAt=Date.now();
  state.dirty.delete(id);
  return response;
}
async function autosaveNow(id){
  if(id==null)return;
  const draft=getDraft(id);if(!draft)return;
  if(!state.dirty.has(id))return;
  if(draft._autosaveTimer){clearTimeout(draft._autosaveTimer);draft._autosaveTimer=null;}
  draft.autosaveState='saving';refreshDraftUI();
  try{await _persistDraft(id,draft);draft.autosaveState='saved';}
  catch(error){
    if(error?.status===409){draft.autosaveState='conflict';notify('Draft revision conflict — reload the source to pick up the latest server copy.',true);}
    else{draft.autosaveState='failed';}
  }
  if(state.opened===id)refreshDraftUI();
}
function scheduleAutosave(id){
  const draft=getDraft(id);if(!draft)return;
  if(draft._autosaveTimer)clearTimeout(draft._autosaveTimer);
  draft.autosaveState='pending';
  draft._autosaveTimer=setTimeout(()=>{draft._autosaveTimer=null;autosaveNow(id);},AUTOSAVE_DEBOUNCE_MS);
}
async function saveDraft(){
  const id=state.opened;if(id==null)return;
  const draft=getDraft(id);if(!draft||!state.dirty.has(id))return;
  if(draft._autosaveTimer){clearTimeout(draft._autosaveTimer);draft._autosaveTimer=null;}
  draft.autosaveState='saving';refreshDraftUI();
  try{await _persistDraft(id,draft);draft.autosaveState='saved';refreshDraftUI();notify('Draft saved separately. Original unchanged.');}
  catch(error){
    if(error?.status===409){draft.autosaveState='conflict';refreshDraftUI();notify('Draft revision conflict — reload the source.',true);}
    else{draft.autosaveState='failed';refreshDraftUI();err(error);}
  }
}
function autosaveAllPending(){
  // Called on blur / visibilitychange / beforeunload to minimise lost edits.
  for(const [id] of state.drafts){ if(state.dirty.has(id))autosaveNow(id); }
}
let startReviewSnapshot=null;
let pendingJobSubmission=null;
function closeStartReview(){
  const dialog=$('start-review-dialog');
  if(dialog.open)dialog.close();
  startReviewSnapshot=null;
  $('start-button').focus();
}
async function startJob(){const selected=[...state.selected];const reason=processingBlocker(selected);if(reason)return notify(reason,true);
  const items=selected.map(id=>state.sources.find(x=>x.id===id));
  if(items.some(x=>!x?.sha256))return notify('A selected reference has not been fetched',true);
  startReviewSnapshot={cid:state.conversationId,objectiveId:currentObjective().id,
    operation:$('requested-operation').value,
    items:items.map(x=>({id:x.id,name:x.name,version:x.version,sha256:x.sha256}))};
  $('start-review-objective').textContent=currentObjective().content;
  const list=$('start-review-sources');list.replaceChildren();
  for(const src of startReviewSnapshot.items){const item=document.createElement('li');
    item.textContent=`${src.name} · version ${src.version} · SHA-256 ${src.sha256}`;list.append(item);}
  $('start-review-status').textContent='Confirm to admit exactly these selected original versions.';
  $('start-review-dialog').showModal();$('start-review-confirm').focus();
}
async function admitReviewedJob(){
  const snapshot=startReviewSnapshot;
  if(!snapshot)return;
  const selected=[...state.selected];
  const reason=processingBlocker(selected);
  const sources=selected.map(id=>state.sources.find(x=>x.id===id));
  const same=state.conversationId===snapshot.cid && currentObjective()?.id===snapshot.objectiveId
    && $('requested-operation').value===snapshot.operation
    && selected.length===snapshot.items.length
    && snapshot.items.every((x,i)=>x.id===selected[i] && sources[i]?.version===x.version && sources[i]?.sha256===x.sha256);
  if(reason || !same){closeStartReview();return notify(reason || 'Input scope changed since review. Review the current scope again.',true);}
  closeStartReview();
  state.busy=true;refreshStart();
  try{
    const sources=selected.map(id=>state.sources.find(x=>x.id===id));
    if(sources.some(x=>!x?.sha256))throw new Error('A selected reference has not been fetched');
    const requestScope={operation:snapshot.operation,prompt_message_id:currentObjective().id,source_ids:selected,
      expected_versions:Object.fromEntries(sources.map(x=>[x.id,x.version]))};
    // A lost HTTP response must not create a second job for the same scope.
    const signature=JSON.stringify({conversation:state.conversationId,...requestScope,
      hashes:sources.map(x=>x.sha256)});
    if(pendingJobSubmission?.signature!==signature){
      pendingJobSubmission={signature,key:crypto.randomUUID()};
    }
    const body={...requestScope,idempotency_key:pendingJobSubmission.key};
    const accepted=await api.job(state.conversationId,body);
    pendingJobSubmission=null;
    state.activeScopeCount=selected.length;state.jobId=accepted.id;state.jobStatus=accepted.status;state.accepted=true;state.artifactId=null;state.cursor=0;state.jobEvents=[];state.trace=null;state.userChangedDetail=false;
    $('job-summary').textContent=`Job accepted: ${state.jobStatus}`;show('open-result',false);
    setProcessPanel();drawProcess();refreshRunHistory();notify('Job accepted by System. Waiting for real events.');
    if(state.polling)clearInterval(state.polling);
    await pollJob();if(activeJob())state.polling=setInterval(pollJob,850);
  }catch(e){err(e);}finally{state.busy=false;refreshStart();}
}
let pollBusy=false;
async function pollJob(){if(!state.jobId||pollBusy)return;pollBusy=true;
  try{
    const cid=state.conversationId,jid=state.jobId;
    const [replay,job,trace]=await Promise.all([
      replayEventPages(async after=>(await api.events(cid,after)).events,state.cursor),
      api.jobStatus(cid,jid),api.trace(cid,jid)]);
    // An earlier asynchronous poll must never replace another job's state.
    if(cid!==state.conversationId || jid!==state.jobId)return;
    state.cursor=replay.cursor;
    // Retain only the recent client display window. Full event history remains
    // queryable from the persisted server journal.
    state.jobEvents=[...state.jobEvents,...replay.events.filter(e=>e.job_id===jid)].slice(-500);
    state.jobStatus=job.status;state.trace=trace;
    $('job-summary').textContent=`Job ${state.jobId.slice(0,8)} · ${job.status}${job.error?': '+job.error:''}`;
    drawProcess();refreshStart();
    if(isTerminal(job.status) && replay.complete){
      clearInterval(state.polling);state.polling=null;state.artifactId=job.artifact_id;
      show('open-result',!!job.artifact_id);setProcessPanel();
      refreshBackground();refreshRunHistory();
      notify(`System job ${job.status}. Open the recorded result to review it.`,job.status==='failed');
    }
  }catch(e){clearInterval(state.polling);state.polling=null;notify('Event/status retrieval failed. Actual job outcome unknown; reconnect to verify. '+e.message,true);}
  finally{pollBusy=false;}
}
async function openEvidenceSource(item, artifactId){
  const preview=$('evidence-preview');
  $('evidence-status').textContent=`Opening original version ${item.version} of ${item.name}…`;
  show('evidence-preview',false);
  try{
    const raw=await api.artifactEvidenceContent(state.conversationId,artifactId,item.source_id);
    if(state.artifactId!==artifactId || !state.displayArtifact)return;
    let text;
    try{text=new TextDecoder('utf-8',{fatal:true}).decode(raw);}
    catch{throw new Error('Original bytes are retained but cannot be displayed as UTF-8 text.');}
    preview.textContent=text;
    show('evidence-preview',true);
    $('evidence-status').textContent=`Verified original: ${item.name} · version ${item.version} · SHA-256 ${item.sha256}`;
  }catch(error){$('evidence-status').textContent=`Cannot display source: ${error.message}`;}
}
async function downloadArtifact(){
  if(!state.artifactId)return;
  const aid=state.artifactId;
  try{
    const raw=await api.artifactExport(state.conversationId,aid);
    const url=URL.createObjectURL(new Blob([raw],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=`oneshot-artifact-${aid}.json`;
    link.click();URL.revokeObjectURL(url);
    notify('Downloaded typed artifact and recorded source provenance. This is not a summary-only output.json.');
  }catch(error){err(error);}
}
async function downloadSummary(){
  if(!state.artifactId)return;
  try{
    const raw=await api.summaryExport(state.conversationId,state.artifactId);
    const url=URL.createObjectURL(new Blob([raw],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='output.json';
    link.click();URL.revokeObjectURL(url);
    notify('Downloaded model-generated summary. Semantic accuracy remains subject to review.');
  }catch(error){err(error);}
}
async function openResult(){if(!state.artifactId)return;
  const aid=state.artifactId;
  try {
    const [result,evidence]=await Promise.all([api.artifact(state.conversationId,aid),api.artifactEvidence(state.conversationId,aid)]);
    if(state.artifactId!==aid)return;
    state.userChangedDetail=true;state.displayArtifact=true;reviewView();
    show('review-empty',false);show('editor-wrapper',false);show('artifact-view',true);$('review-label').textContent=result.kind;
    show('apply-controls',true);$('apply-status').textContent='';show('apply-diff',false);
    show('summary-export',result.kind==='summary');
    $('artifact-meta').textContent=`${result.kind} · provider: ${result.provider} · ${result.limitations.join('; ')}`;
    $('artifact-content').textContent=result.content;
    show('evidence-preview',false);$('evidence-preview').textContent='';
    const list=$('artifact-evidence-list');list.replaceChildren();
    for(const item of evidence.sources){
      const row=document.createElement('li');const button=document.createElement('button');
      button.type='button';button.className='secondary';button.disabled=!item.available;
      button.textContent=`${item.name} · v${item.version} · ${item.available?'Open original':'Original unavailable'}`;
      button.addEventListener('click',()=>openEvidenceSource(item,aid));row.append(button);list.append(row);
    }
    $('evidence-status').textContent=`${evidence.sources.filter(x=>x.available).length} / ${evidence.sources.length} original sources verified.`;
    drawSources();
  }catch(error){err(error);}
}
let preparedApply = null;
async function reviewApply(){
  if(!state.connected || state.agentActive || !state.displayArtifact || !state.artifactId)return;
  const destination=$('apply-destination').value.trim();
  if(!destination){$('apply-status').textContent='Enter a destination under managed output.';return;}
  const button=$('apply-prepare');button.disabled=true;
  try {
    const target=await api.applyTarget(state.conversationId,destination);
    const prepared=await api.applyPrepare(state.conversationId,{
      artifact_id:state.artifactId,destination,expected_target_sha256:target.sha256});
    preparedApply={...prepared,artifactId:state.artifactId,conversationId:state.conversationId};
    $('apply-confirm-details').textContent=`Destination: ${destination} · Baseline: ${target.sha256||'new file'} · Artifact: ${state.artifactId}`;
    $('apply-dialog').showModal();$('apply-cancel').focus();
  }catch(error){$('apply-status').textContent=`Apply preparation rejected: ${error.message}`;err(error);}
  finally{button.disabled=false;}
}
function closeApply(){if($('apply-dialog').open)$('apply-dialog').close();preparedApply=null;}
async function confirmReviewedApply(){
  const prepared=preparedApply;
  if(!prepared)return;
  if(prepared.artifactId!==state.artifactId || prepared.conversationId!==state.conversationId){
    $('apply-status').textContent='Artifact or conversation changed; prepare Apply again.';closeApply();return;
  }
  $('apply-confirm').disabled=true;$('apply-cancel').disabled=true;
  try{
    const result=await api.applyConfirm(prepared.conversationId,{
      confirmation_token:prepared.confirmation_token,confirm_apply:true});
    const readback=await api.appliedReadback(prepared.conversationId,result.id);
    if(!result.verified || !readback.verified || readback.result_sha256!==result.result_sha256)
      throw new Error('Apply readback does not match the recorded output');
    $('apply-status').textContent=`Verified applied result: ${readback.destination} · SHA-256 ${readback.result_sha256}`;
    $('apply-diff').textContent=readback.final_applied_diff||'No byte differences';
    show('apply-diff',true);closeApply();
  }catch(error){$('apply-status').textContent=`Apply not verified: ${error.message}`;err(error);closeApply();}
  finally{$('apply-confirm').disabled=false;$('apply-cancel').disabled=false;}
}
function closeMenu() {
  show('workspace-menu',false);
  $('menu-toggle').setAttribute('aria-expanded','false');
}
function closeSettings() {
  show('settings-panel',false);
  $('settings-toggle').setAttribute('aria-expanded','false');
}
function init(){
  $('login-form').onsubmit=async e=>{
    e.preventDefault();$('login-submit').disabled=true;$('login-error').textContent='';
    try{await api.login($('browser-password').value);$('browser-password').value='';await boot();}
    catch(error){$('login-error').textContent=error.message;}
    finally{$('login-submit').disabled=false;}
  };
    $('run-history-search').addEventListener('input',()=>{
    runHistory.page=0;
    if(runHistory.timer)clearTimeout(runHistory.timer);
    runHistory.sequence++;
    runHistory.timer=setTimeout(()=>{runHistory.timer=null;refreshRunHistory();},260);
  });
  $('run-history-status').addEventListener('change',()=>{runHistory.page=0;refreshRunHistory();});
  $('run-history-refresh').onclick=refreshRunHistory;
  initPromptWorkspace();
  $('run-history-export').onclick=async()=>{
    if(!state.connected||!state.conversationId)return notify('System unavailable',true);
    const cid=state.conversationId;
    const query=$('run-history-search').value.trim(),status=$('run-history-status').value;
    const button=$('run-history-export');button.disabled=true;button.textContent='Exporting…';
    try{
      const {blob,filename,total,rowCount}=await api.exportJobsCsv(cid,{query,status});
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.rel='noopener';
      document.body.appendChild(anchor);anchor.click();anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),30_000);
      notify(`Exported ${rowCount}/${total} recorded runs to ${filename}`);
    }catch(error){err(error);}
    finally{button.disabled=false;button.textContent='Export CSV';}
  };
  $('run-history-previous').onclick=()=>{if(runHistory.page>0){runHistory.page--;refreshRunHistory();}};
  $('run-history-next').onclick=()=>{if(!$('run-history-next').disabled){runHistory.page++;refreshRunHistory();}};
  $('logout-button').onclick=async()=>{
    $('run-history-list').replaceChildren();$('run-history-count').textContent='Sign in to view recorded runs';$('run-history-search').value='';$('run-history-status').value='';runHistory.page=0;
    try{await api.logout();}catch(error){err(error);return;}
    cancelPreSendReview();stopBackgroundRefresh();state.authenticated=false;state.connected=false;state.conversationId=null;state.messages=[];
    $('background-state').textContent='No recorded evaluations';$('background-history').replaceChildren();
    state.agentOptions=[];state.agentSelected=null;state.agentActive=false;agentRequestIdentity=null;
    sessionStorage.removeItem('oneshot_conversation_id');
    show('workspace',false);show('login-view',true);closeMenu();updateConnection();
  };
  $('menu-toggle').onclick=()=>toggle('workspace-menu','menu-toggle');
  $('agent-toggle').onclick=()=>toggle('agent-drawer','agent-toggle');
  $('agent-selector').onchange=async event=>{state.agentSelected=event.target.value;await activateAgent();};
  $('agent-deactivate').onclick=deactivateAgent;
  $('agent-form').onsubmit=sendAgent;
  $('settings-toggle').onclick=()=>{toggle('settings-panel','settings-toggle');closeMenu();};
  $('settings-close').onclick=closeSettings;
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){
      if(preSend.review && !preSend.review.pending){cancelPreSendReview();return;}
      closeMenu();closeSettings();
    }
  });
  $('attach-toggle').onclick=()=>toggle('attach-menu','attach-toggle');
  $('paste-toggle').onclick=()=>{show('attach-menu',false);$('attach-toggle').setAttribute('aria-expanded','false');show('paste-form',true);};
  $('paste-cancel').onclick=()=>show('paste-form',false);
  $('file-toggle').onclick=()=>{show('attach-menu',false);$('attach-toggle').setAttribute('aria-expanded','false');$('file-input').click();};
  $('reference-toggle').onclick=()=>{show('attach-menu',false);show('paste-form',false);show('reference-form',true);};
  $('reference-cancel').onclick=()=>show('reference-form',false);
  $('reference-form').onsubmit=async event=>{
    event.preventDefault();
    if(!state.connected||state.agentActive)return;
    try{await api.attach(state.conversationId,{action:'REFERENCE_SOURCE',
      name:$('reference-name').value.trim(),url:$('reference-url').value.trim()});
      show('reference-form',false);$('reference-form').reset();await refreshSources();
      notify('URL recorded as an unfetched reference; no external retrieval was performed.');}
    catch(error){err(error);}
  };
  $('library-toggle').onclick=async()=>{const showNow=$('library-items').hidden;
    show('library-items',showNow);$('library-toggle').setAttribute('aria-expanded',String(showNow));
    if(showNow)try{await refreshLibrary();}catch(error){err(error);}};
  $('presend-cancel').onclick=cancelPreSendReview;
  $('presend-summary').addEventListener('input',event=>{
    try{preSend.editSummary(event.target.value);$('presend-error').textContent='';}
    catch(error){$('presend-error').textContent=error.message;}
  });
  $('presend-approve').onclick=()=>preSend.approve({currentOriginal:$('system-input').value,conversationId:state.conversationId});
  $('presend-dialog').addEventListener('cancel',event=>{
    event.preventDefault();
    if(!preSend.review?.pending)cancelPreSendReview();
  });
  // Native modal makes the page inert. Explicit wrapping also avoids focus
  // moving to BODY in Chromium when tabbing past the last modal control.
  $('presend-dialog').addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=[$('presend-summary'),$('presend-cancel'),$('presend-approve')].filter(el=>!el.disabled);
    const first=controls[0],last=controls.at(-1);
    if(!first){event.preventDefault();$('presend-dialog').focus();return;}
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
  });
  $('requested-operation').addEventListener('change',refreshStart);
  $('system-input').addEventListener('input',refreshStart);
  $('file-input').onchange=attachFile;$('paste-form').onsubmit=attachPaste;$('system-form').onsubmit=sendSystem;
  $('editor-input').oninput=e=>{
    const d=getDraft(state.opened);if(!d)return;
    d.text=e.target.value;state.dirty.add(state.opened);
    d.autosaveState='pending';
    refreshDraftUI();scheduleAutosave(state.opened);
  };
  $('editor-input').addEventListener('blur',()=>{ if(state.opened!=null && state.dirty.has(state.opened)) autosaveNow(state.opened); });
  document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='hidden') autosaveAllPending(); });
  window.addEventListener('beforeunload',autosaveAllPending);
  $('save-draft').onclick=saveDraft;$('start-button').onclick=startJob;$('open-result').onclick=openResult;
  $('start-review-cancel').onclick=closeStartReview;
  $('start-review-confirm').onclick=admitReviewedJob;
  $('start-review-dialog').addEventListener('cancel',event=>{event.preventDefault();closeStartReview();});
  $('start-review-dialog').addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const first=$('start-review-cancel'),last=$('start-review-confirm');
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
  });
  $('artifact-export').onclick=downloadArtifact;
  $('summary-export').onclick=downloadSummary;
  $('apply-prepare').onclick=reviewApply;
  $('apply-cancel').onclick=closeApply;
  $('apply-confirm').onclick=confirmReviewedApply;
  $('apply-dialog').addEventListener('cancel',event=>{event.preventDefault();if(!$('apply-confirm').disabled)closeApply();});
  $('process-review').onclick=()=>{state.userChangedDetail=true;reviewView();};
  updateConnection();boot();
}
if(typeof document!=='undefined')init();

// -------- Prompt Workspace --------
const promptState = { assets: [], selectedId: null, detail: null, optimizations: [] };

async function loadPrompts(){
  if(!state.connected||!state.conversationId)return;
  try{
    const data=await api.listPrompts(state.conversationId);
    promptState.assets=data.items||[];
    const sel=$('prompt-select');
    const prev=sel.value;
    sel.replaceChildren();
    if(!promptState.assets.length){
      const o=document.createElement('option');o.value='';o.textContent='No prompts yet';
      sel.append(o);
      promptState.selectedId=null;$('prompt-detail').hidden=true;
      return;
    }
    for(const a of promptState.assets){
      const o=document.createElement('option');o.value=a.id;
      o.textContent=`${a.name}${a.latest_version?` (v${a.latest_version.version_number})`:' (draft only)'}`;
      sel.append(o);
    }
    const target=prev && promptState.assets.find(a=>a.id===prev)?prev:promptState.assets[0].id;
    sel.value=target;promptState.selectedId=target;
    await openPromptDetail(target);
  }catch(error){err(error);}
}

async function openPromptDetail(id){
  if(!id){ $('prompt-detail').hidden=true;promptState.detail=null;return; }
  try{
    const detail=await api.readPrompt(state.conversationId,id);
    promptState.detail=detail;
    $('prompt-detail').hidden=false;
    $('prompt-latest').textContent=detail.latest_version
      ? `Latest published: v${detail.latest_version.version_number}`
      : 'No published version yet.';
    $('prompt-latest').setAttribute('data-prompt-latest-version',
      detail.latest_version ? String(detail.latest_version.version_number) : '0');
    const d=detail.draft||{content:'',variables:[],revision:0};
    $('prompt-draft-content').value=d.content;
    $('prompt-variables').value=JSON.stringify(d.variables||[],null,2);
    $('prompt-draft-state').textContent=`Draft revision ${d.revision||0}`;
    $('prompt-draft-state').setAttribute('data-prompt-draft-rev', String(d.revision||0));
    $('prompt-save-draft').disabled=false;
    $('prompt-publish').disabled=!(d.content||'').trim();
    renderPromptVersions(detail.versions||[]);
    await loadPromptOptimizations(id);
  }catch(error){err(error);}
}

function renderPromptVersions(versions){
  const list=$('prompt-versions-list');list.replaceChildren();
  if(!versions.length){const li=document.createElement('li');li.className='small';li.textContent='No published versions';list.append(li);return;}
  for(const v of versions){
    const li=document.createElement('li');li.className='prompt-version';
    const label=document.createElement('span');label.textContent=`v${v.version_number} · ${v.content_sha256.slice(0,10)}`;
    const restoreBtn=document.createElement('button');restoreBtn.type='button';restoreBtn.className='secondary';
    restoreBtn.textContent='Restore';
    restoreBtn.addEventListener('click',async()=>{
      if(!confirm(`Restore v${v.version_number} as a new version?`))return;
      try{
        await api.restorePromptVersion(state.conversationId,promptState.selectedId,{version:v.version_number});
        notify(`Restored v${v.version_number} as a new version.`);
        await loadPrompts();
      }catch(error){err(error);}
    });
    li.append(label,restoreBtn);
    if(v.restored_from){
      const meta=document.createElement('span');meta.className='small';
      meta.textContent=` (restored from ${v.restored_from.slice(0,8)})`;
      li.append(meta);
    }
    list.append(li);
  }
}

async function savePromptDraft(){
  if(!promptState.detail)return;
  let variables;
  try{variables=JSON.parse($('prompt-variables').value||'[]');}
  catch{return notify('Variables field must be valid JSON array',true);}
  const expected=(promptState.detail.draft||{}).revision;
  try{
    const r=await api.updatePromptDraft(state.conversationId,promptState.selectedId,
      {content:$('prompt-draft-content').value, variables, expected_revision:expected});
    $('prompt-draft-state').setAttribute('data-prompt-draft-rev', String(r.revision));
    notify(`Draft saved (revision ${r.revision}).`);
    await openPromptDetail(promptState.selectedId);
  }catch(error){err(error);}
}

async function publishPrompt(){
  if(!promptState.detail)return;
  const expected=(promptState.detail.draft||{}).revision;
  try{
    const r=await api.publishPrompt(state.conversationId,promptState.selectedId,{expected_revision:expected});
    notify(`Published v${r.version_number}.`);
    await loadPrompts();
    // Set the deterministic marker AFTER loadPrompts resolves so observers (tests) see
    // the completed state, not an intermediate one.
    $('prompt-latest').setAttribute('data-prompt-latest-version', String(r.version_number));
  }catch(error){err(error);}
}

async function createPrompt(){
  const name=prompt('Prompt name:');
  if(!name)return;
  try{
    const r=await api.createPrompt(state.conversationId,
      {name, content:'Instructions. Use ${example} to inject a declared variable.',
       variables:[{name:'example'}]});
    promptState.selectedId=r.id;
    await loadPrompts();  // loadPrompts targets the latest prompt and calls openPromptDetail
    $('prompt-select').value=r.id;
    notify(`Created ${r.name}.`);
  }catch(error){err(error);}
}

async function comparePromptVersionsClick(){
  const l=$('prompt-compare-left').value.trim(), r=$('prompt-compare-right').value.trim();
  if(!l||!r)return;
  try{
    const data=await api.comparePromptVersions(state.conversationId,promptState.selectedId,l,r);
    $('prompt-compare-output').textContent=data.identical
      ? 'Versions are byte-identical.'
      : data.unified_diff || '(no textual diff)';
  }catch(error){err(error);}
}

async function runPromptEvaluation(){
  let criteria;
  try{criteria=JSON.parse($('prompt-eval-criteria').value||'[]');}
  catch{return notify('Criteria must be valid JSON array',true);}
  try{
    const create=await api.createPromptEvaluation(state.conversationId,promptState.selectedId,
      {version:'latest', criteria});
    const run=await api.runPromptEvaluation(state.conversationId,promptState.selectedId,create.id);
    $('prompt-eval-output').textContent=JSON.stringify(run.findings,null,2);
  }catch(error){err(error);}
}

async function loadPromptOptimizations(id){
  try{
    const data=await api.listPromptOptimizations(state.conversationId,id);
    promptState.optimizations=data.items||[];
    const list=$('prompt-opt-list');list.replaceChildren();
    if(!promptState.optimizations.length){
      const li=document.createElement('li');li.className='small';li.textContent='No proposals yet';
      list.append(li);return;
    }
    for(const o of promptState.optimizations){
      const li=document.createElement('li');
      li.textContent=`${o.status} \u00b7 ${o.provider}/${o.model||'?'} \u00b7 ${o.created_at}`;
      if(o.status==='proposed'){
        const accept=document.createElement('button');accept.type='button';accept.className='secondary';accept.textContent='Accept into draft';
        accept.addEventListener('click',async()=>{
          try{await api.acceptPromptOptimization(state.conversationId,id,o.id);notify('Optimization accepted into draft (no auto-publish).');await openPromptDetail(id);}
          catch(error){err(error);}
        });
        const reject=document.createElement('button');reject.type='button';reject.className='secondary';reject.textContent='Reject';
        reject.addEventListener('click',async()=>{
          try{await api.rejectPromptOptimization(state.conversationId,id,o.id);notify('Optimization rejected.');await loadPromptOptimizations(id);}
          catch(error){err(error);}
        });
        li.append(' ',accept,' ',reject);
      }
      list.append(li);
    }
  }catch(error){err(error);}
}

async function proposePromptOptimization(){
  try{
    const r=await api.proposePromptOptimization(state.conversationId,promptState.selectedId,{});
    notify(`Optimization proposed by ${r.provider}/${r.model}.`);
    await loadPromptOptimizations(promptState.selectedId);
  }catch(error){
    if(error?.status===503){notify(error.message || 'No optimizer provider configured.',true);}
    else err(error);
  }
}

function initPromptWorkspace(){
  $('prompt-new').onclick=createPrompt;
  $('prompt-select').addEventListener('change',e=>{
    promptState.selectedId=e.target.value;openPromptDetail(e.target.value);
  });
  $('prompt-save-draft').onclick=savePromptDraft;
  $('prompt-publish').onclick=publishPrompt;
  $('prompt-optimize').onclick=proposePromptOptimization;
  $('prompt-compare-go').onclick=comparePromptVersionsClick;
  $('prompt-eval-run').onclick=runPromptEvaluation;
}

// -------- v6 Improvement Loop (A) --------
// Wires the Improvement Loop panel to the real System routes. The panel renders only when the
// operator opens a historical job (openHistoryJob). Reviews, evaluations, and proposals are
// written exclusively through the authenticated API; the UI never alters committed job output.
const improvement = { jobId:null, reviewRevision:0 };

function improvementSummary(e) {
  if (e.status === 'completed' && e.findings_json) {
    try {
      const findings = JSON.parse(e.findings_json);
      const pass = (findings.criteria||[]).filter(c=>c.pass).length;
      const total = (findings.criteria||[]).length;
      return `${e.status} · ${pass}/${total} passed`;
    } catch { return e.status; }
  }
  return e.status || 'pending';
}

async function renderImprovementLoopForJob(jobId) {
  improvement.jobId = jobId;
  $('improvement-job-id').textContent = 'Job ' + jobId.slice(0,8);
  await Promise.all([
    renderJobReview(jobId),
    renderJobEvaluations(jobId),
    renderImprovementProposals(),
    renderRecurringDefects(),
  ]);
}

async function renderJobReview(jobId) {
  const cid = state.conversationId;
  const state_el = $('improvement-review-state');
  try {
    const review = await api.readJobReview(cid, jobId);
    improvement.reviewRevision = review.revision || 1;
    for (const r of document.getElementsByName('improvement-review-decision')) {
      r.checked = (r.value === review.decision);
    }
    $('improvement-review-required').value = review.required || '';
    $('improvement-review-prohibited').value = review.prohibited || '';
    $('improvement-review-reason').value = review.reason || '';
    $('improvement-review-limitations').value = review.limitations || '';
    state_el.textContent = `Revision ${review.revision} saved at ${review.updated_at || review.created_at}`;
  } catch (e) {
    if (e.status === 404) {
      improvement.reviewRevision = 0;
      $('improvement-review-required').value = '';
      $('improvement-review-prohibited').value = '';
      $('improvement-review-reason').value = '';
      $('improvement-review-limitations').value = '';
      state_el.textContent = 'No review recorded yet.';
    } else {
      state_el.textContent = `Review retrieval failed: ${e.message}`;
    }
  }
}

async function renderJobEvaluations(jobId) {
  const cid = state.conversationId;
  const list = $('improvement-eval-list'); list.replaceChildren();
  try {
    const result = await api.listJobEvaluations(cid, { jobId });
    const items = result.items || [];
    if (!items.length) {
      const li = document.createElement('li'); li.className = 'small';
      li.textContent = 'No evaluations yet'; list.append(li); return;
    }
    for (const ev of items) {
      const li = document.createElement('li'); li.dataset.evalId = ev.id;
      li.dataset.status = ev.status;
      const head = document.createElement('div');
      head.textContent = `${ev.id.slice(0,8)} · ${improvementSummary(ev)}`;
      li.append(head);
      const criteria = (() => { try { return JSON.parse(ev.criteria_json||'[]'); } catch { return []; } })();
      if (criteria.length) {
        const crit = document.createElement('p'); crit.className = 'small';
        crit.textContent = criteria.map(c=>`${c.kind}:${JSON.stringify(c.value)}`).join('; ');
        li.append(crit);
      }
      const actions = document.createElement('div'); actions.className = 'improvement-actions';
      if (ev.status === 'proposed') {
        const approve = document.createElement('button'); approve.type='button';
        approve.textContent = 'Approve';
        approve.addEventListener('click', async () => {
          try { await api.approveJobEvaluation(cid, ev.id); await renderJobEvaluations(jobId); }
          catch (e) { notify('Approve failed: ' + e.message, true); }
        });
        const reject = document.createElement('button'); reject.type='button'; reject.className='secondary';
        reject.textContent = 'Reject';
        reject.addEventListener('click', async () => {
          try { await api.rejectJobEvaluation(cid, ev.id); await renderJobEvaluations(jobId); }
          catch (e) { notify('Reject failed: ' + e.message, true); }
        });
        actions.append(approve, reject);
      } else if (ev.status === 'approved') {
        const run = document.createElement('button'); run.type='button';
        run.textContent = 'Run evaluation';
        run.addEventListener('click', async () => {
          try { await api.runJobEvaluation(cid, ev.id); await renderJobEvaluations(jobId); }
          catch (e) { notify('Run failed: ' + e.message, true); }
        });
        actions.append(run);
      }
      if (actions.children.length) li.append(actions);
      list.append(li);
    }
  } catch (e) {
    const li = document.createElement('li'); li.className = 'small';
    li.textContent = `Evaluations unavailable: ${e.message}`; list.append(li);
  }
}

async function renderImprovementProposals() {
  const cid = state.conversationId;
  const list = $('improvement-proposal-list'); list.replaceChildren();
  try {
    const result = await api.listImprovementProposals(cid);
    const items = result.items || [];
    if (!items.length) {
      const li = document.createElement('li'); li.className = 'small';
      li.textContent = 'No improvement proposals yet'; list.append(li); return;
    }
    for (const pr of items) {
      const li = document.createElement('li'); li.dataset.status = pr.status;
      const head = document.createElement('div');
      head.textContent = `${pr.id.slice(0,8)} · ${pr.status} · ${pr.issue_summary}`;
      li.append(head);
      const area = document.createElement('p'); area.className = 'small';
      area.textContent = `Area: ${pr.affected_responsibility}`;
      li.append(area);
      const actions = document.createElement('div'); actions.className = 'improvement-actions';
      if (pr.status === 'proposed') {
        const accept = document.createElement('button'); accept.type='button';
        accept.textContent = 'Accept';
        accept.addEventListener('click', async () => {
          try { await api.acceptImprovementProposal(cid, pr.id); await renderImprovementProposals(); }
          catch (e) { notify('Accept failed: ' + e.message, true); }
        });
        const reject = document.createElement('button'); reject.type='button'; reject.className='secondary';
        reject.textContent = 'Reject';
        reject.addEventListener('click', async () => {
          try { await api.rejectImprovementProposal(cid, pr.id); await renderImprovementProposals(); }
          catch (e) { notify('Reject failed: ' + e.message, true); }
        });
        actions.append(accept, reject);
      } else if (pr.status === 'accepted') {
        const impl = document.createElement('button'); impl.type='button';
        impl.textContent = 'Mark implemented';
        impl.addEventListener('click', async () => {
          try { await api.markImprovementProposalImplemented(cid, pr.id); await renderImprovementProposals(); }
          catch (e) { notify('Mark implemented failed: ' + e.message, true); }
        });
        actions.append(impl);
      }
      if (actions.children.length) li.append(actions);
      list.append(li);
    }
  } catch (e) {
    const li = document.createElement('li'); li.className = 'small';
    li.textContent = `Proposals unavailable: ${e.message}`; list.append(li);
  }
}

async function renderRecurringDefects() {
  const cid = state.conversationId;
  const summary = $('improvement-recurring-summary');
  const list = $('improvement-recurring-list'); list.replaceChildren();
  try {
    const report = await api.recurringDefects(cid, { minCount: 1 });
    const reviews = report.reviews || [];
    const bg = report.recurring_issue_codes || [];
    summary.textContent = (reviews.length || bg.length)
      ? `Reviews: ${reviews.length} grouping(s); Background: ${bg.length} issue code(s).`
      : 'No recurring defects detected.';
    for (const r of reviews) {
      const li = document.createElement('li'); li.className = 'small';
      li.textContent = `${r.n} × ${r.decision}`;
      list.append(li);
    }
    for (const r of bg) {
      const li = document.createElement('li'); li.className = 'small';
      li.textContent = `${r.count} × background: ${r.code}`;
      list.append(li);
    }
  } catch (e) {
    summary.textContent = `Recurring defects unavailable: ${e.message}`;
  }
}

// Review form submit
document.addEventListener('DOMContentLoaded', () => {
  const reviewForm = $('improvement-review-form');
  reviewForm && reviewForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!improvement.jobId) return;
    const cid = state.conversationId;
    const decisionEl = document.querySelector('input[name="improvement-review-decision"]:checked');
    const body = {
      decision: (decisionEl && decisionEl.value) || 'potential_defect',
      required: $('improvement-review-required').value,
      prohibited: $('improvement-review-prohibited').value,
      reason: $('improvement-review-reason').value,
      limitations: $('improvement-review-limitations').value,
      evidence_source_ids: [],
    };
    if (improvement.reviewRevision > 0) body.expected_revision = improvement.reviewRevision;
    try {
      const saved = await api.upsertJobReview(cid, improvement.jobId, body);
      improvement.reviewRevision = saved.revision;
      $('improvement-review-state').textContent =
        `Revision ${saved.revision} saved at ${saved.updated_at || saved.created_at}`;
    } catch (e) {
      $('improvement-review-state').textContent = `Save failed: ${e.message}`;
    }
  });
  const evalForm = $('improvement-eval-form');
  evalForm && evalForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!improvement.jobId) return;
    const kind = $('improvement-eval-kind').value;
    const raw = $('improvement-eval-value').value;
    let value = raw;
    if (kind === 'max_length') value = parseInt(raw || '0', 10);
    const cid = state.conversationId;
    try {
      await api.createJobEvaluation(cid, improvement.jobId, {
        criteria: [{ kind, value }], status: 'proposed',
      });
      $('improvement-eval-value').value = '';
      await renderJobEvaluations(improvement.jobId);
    } catch (e) {
      notify('Create evaluation failed: ' + e.message, true);
    }
  });
  const propForm = $('improvement-proposal-form');
  propForm && propForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const cid = state.conversationId;
    const body = {
      issue_summary: $('improvement-proposal-issue').value.trim(),
      affected_responsibility: $('improvement-proposal-area').value.trim(),
      current_behavior: $('improvement-proposal-current').value,
      required_behavior: $('improvement-proposal-required').value,
      proposed_correction: $('improvement-proposal-correction').value,
      risks: '',
      evidence: improvement.jobId ? { job_ids: [improvement.jobId] } : {},
    };
    if (!body.issue_summary || !body.affected_responsibility) {
      notify('Issue summary and affected responsibility are required.', true);
      return;
    }
    try {
      await api.createImprovementProposal(cid, body);
      $('improvement-proposal-issue').value = '';
      $('improvement-proposal-area').value = '';
      $('improvement-proposal-current').value = '';
      $('improvement-proposal-required').value = '';
      $('improvement-proposal-correction').value = '';
      await renderImprovementProposals();
    } catch (e) {
      notify('Create proposal failed: ' + e.message, true);
    }
  });
});

