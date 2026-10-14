/** Same-origin API only. Never embeds a bearer credential in browser code. */
let csrf = null;
async function authRequest(path, method='GET', body=null) {
  const headers = new Headers();
  if (body) headers.set('Content-Type','application/json');
  if (csrf && method !== 'GET') headers.set('X-Oneshot-CSRF',csrf);
  const response = await fetch('/auth/'+path, {method,credentials:'same-origin',cache:'no-store',headers,body:body?JSON.stringify(body):undefined});
  if (!response.ok) throw new ApiError(response.status, `Authentication failed (${response.status})`);
  const data = await response.json();
  if (data.csrf) csrf = data.csrf;
  return data;
}
export class ApiError extends Error {
  constructor(status, message) { super(message); this.name = 'ApiError'; this.status = status; }
}
export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (csrf && options.method && !['GET','HEAD','OPTIONS'].includes(options.method)) headers.set('X-Oneshot-CSRF',csrf);
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const payload = await response.json(); message = typeof payload.detail === 'string' ? payload.detail : message; } catch { /* no readable error body */ }
    throw new ApiError(response.status, message);
  }
  if (options.raw) return response.arrayBuffer();
  return response.json();
}
export const api = {
  login: password => authRequest('login','POST',{password}),
  session: () => authRequest('session'),
  logout: async () => { const r=await authRequest('logout','POST'); csrf=null; return r; },
  createConversation: () => request('/conversations', { method:'POST', body:JSON.stringify({title:'OneShot System'}) }),
  conversation: id => request(`/conversations/${id}`),
  capabilities: () => request('/capabilities'),
  agentSession: (id,active) => request(`/conversations/${id}/session`,{method:'PATCH',body:JSON.stringify({agent_active:active})}),
  agentReply: (id,body) => request(`/conversations/${id}/agent/replies`,{method:'POST',body:JSON.stringify(body)}),
  message: (id, content, idempotencyKey=null) => request(`/conversations/${id}/messages`, {method:'POST',body:JSON.stringify({channel:'system',content,...(idempotencyKey?{idempotency_key:idempotencyKey}:{})})}),
  sources: id => request(`/conversations/${id}/sources`),
  availableSources: id => request(`/conversations/${id}/sources/available`),
  sourceContent: (id,sid) => request(`/conversations/${id}/sources/${sid}/content`, {raw:true}),
  attach: (id,body) => request(`/conversations/${id}/sources/actions`, {method:'POST',body:JSON.stringify(body)}),
  job: (id,body) => request(`/conversations/${id}/jobs`, {method:'POST',body:JSON.stringify(body)}),
  jobStatus: (id,jid) => request(`/conversations/${id}/jobs/${jid}`),

  // Prompt lifecycle
  listPrompts: (id) => request(`/conversations/${id}/prompts`),
  readPrompt: (id, pid) => request(`/conversations/${id}/prompts/${pid}`),
  createPrompt: (id, body) => request(`/conversations/${id}/prompts`,
    {method:'POST', body:JSON.stringify(body)}),
  updatePromptDraft: (id, pid, body) => request(`/conversations/${id}/prompts/${pid}/draft`,
    {method:'PATCH', body:JSON.stringify(body)}),
  publishPrompt: (id, pid, body={}) => request(`/conversations/${id}/prompts/${pid}/publish`,
    {method:'POST', body:JSON.stringify(body)}),
  listPromptVersions: (id, pid) => request(`/conversations/${id}/prompts/${pid}/versions`),
  readPromptVersion: (id, pid, vref) =>
    request(`/conversations/${id}/prompts/${pid}/versions/${vref}`),
  resolvePrompt: (id, pid, body) => request(`/conversations/${id}/prompts/${pid}/resolve`,
    {method:'POST', body:JSON.stringify(body)}),
  restorePromptVersion: (id, pid, body) => request(`/conversations/${id}/prompts/${pid}/restore`,
    {method:'POST', body:JSON.stringify(body)}),
  comparePromptVersions: (id, pid, left, right) => {
    const params=new URLSearchParams({left:String(left), right:String(right)});
    return request(`/conversations/${id}/prompts/${pid}/compare?${params}`);
  },
  createPromptEvaluation: (id, pid, body) =>
    request(`/conversations/${id}/prompts/${pid}/evaluations`,
      {method:'POST', body:JSON.stringify(body)}),
  runPromptEvaluation: (id, pid, eid) =>
    request(`/conversations/${id}/prompts/${pid}/evaluations/${eid}/run`,
      {method:'POST'}),
  listPromptEvaluations: (id, pid) =>
    request(`/conversations/${id}/prompts/${pid}/evaluations`),
  proposePromptOptimization: (id, pid, body={}) =>
    request(`/conversations/${id}/prompts/${pid}/optimizations`,
      {method:'POST', body:JSON.stringify(body)}),
  listPromptOptimizations: (id, pid) =>
    request(`/conversations/${id}/prompts/${pid}/optimizations`),
  acceptPromptOptimization: (id, pid, oid) =>
    request(`/conversations/${id}/prompts/${pid}/optimizations/${oid}/accept`,
      {method:'POST'}),
  rejectPromptOptimization: (id, pid, oid) =>
    request(`/conversations/${id}/prompts/${pid}/optimizations/${oid}/reject`,
      {method:'POST'}),
  sourceDraft: (id,sid) => request(`/conversations/${id}/sources/${sid}/draft`),
  exportJobsCsv: async (id,{query='',status=''}={}) => {
    const params=new URLSearchParams({query,status,limit:'10000'});
    const response=await fetch('/api'+`/conversations/${id}/jobs/export?${params}`,
      {credentials:'same-origin',cache:'no-store',headers:{Accept:'text/csv'}});
    if(!response.ok){
      let message=`Export failed (${response.status})`;
      try{const payload=await response.json();if(typeof payload.detail==='string')message=payload.detail;}catch{}
      throw new ApiError(response.status, message);
    }
    const blob=await response.blob();
    const disposition=response.headers.get('content-disposition')||'';
    const m=/filename="([^"]+)"/.exec(disposition);
    const filename=m?m[1]:`oneshot-run-history-${id}.csv`;
    return {blob, filename, total:parseInt(response.headers.get('x-total')||'0',10),
            rowCount:parseInt(response.headers.get('x-row-count')||'0',10)};
  },
  jobs: (id,{query='',status='',limit=20,offset=0}={}) => {
    const params=new URLSearchParams({query,status,limit:String(limit),offset:String(offset)});
    return request(`/conversations/${id}/jobs?${params}`);
  },
  traceEvents: (id,jid) => request(`/conversations/${id}/jobs/${jid}/trace?include_events=true`),
  trace: (id,jid) => request(`/conversations/${id}/jobs/${jid}/trace?include_events=false`),
  background: id => request(`/conversations/${id}/background?limit=5`),
  events: (id,after) => request(`/conversations/${id}/events?after=${after}&limit=500`),
  artifact: (id,aid) => request(`/conversations/${id}/artifacts/${aid}`),
  artifactEvidence: (id,aid) => request(`/conversations/${id}/artifacts/${aid}/evidence`),
  artifactEvidenceContent: (id,aid,sid) => request(`/conversations/${id}/artifacts/${aid}/evidence/${sid}/content`, {raw:true}),
  artifactExport: (id,aid) => request(`/conversations/${id}/artifacts/${aid}/export`, {raw:true}),
  summaryExport: (id,aid) => request(`/conversations/${id}/artifacts/${aid}/summary`, {raw:true}),
  applyTarget: (id,destination) => request(`/conversations/${id}/apply/target?destination=${encodeURIComponent(destination)}`),
  applyPrepare: (id,body) => request(`/conversations/${id}/apply/prepare`, {method:'POST',body:JSON.stringify(body)}),
  applyConfirm: (id,body) => request(`/conversations/${id}/apply/confirm`, {method:'POST',body:JSON.stringify(body)}),
  appliedReadback: (id,aid) => request(`/conversations/${id}/applied/${aid}`),
  createDraft: (id,body) => request(`/conversations/${id}/drafts`, {method:'POST',body:JSON.stringify(body)}),
  updateDraft: (id,did,body) => request(`/conversations/${id}/drafts/${did}`, {method:'PATCH',body:JSON.stringify(body)}),

  // v6 Improvement Loop
  readJobReview: (id, jid) => request(`/conversations/${id}/jobs/${jid}/review`),
  upsertJobReview: (id, jid, body) =>
    request(`/conversations/${id}/jobs/${jid}/review`,
      {method:'PUT', body:JSON.stringify(body)}),
  listJobReviews: id => request(`/conversations/${id}/reviews`),
  createJobEvaluation: (id, jid, body) =>
    request(`/conversations/${id}/jobs/${jid}/evaluations`,
      {method:'POST', body:JSON.stringify(body)}),
  approveJobEvaluation: (id, eid) =>
    request(`/conversations/${id}/job-evaluations/${eid}/approve`, {method:'POST'}),
  rejectJobEvaluation: (id, eid) =>
    request(`/conversations/${id}/job-evaluations/${eid}/reject`, {method:'POST'}),
  runJobEvaluation: (id, eid) =>
    request(`/conversations/${id}/job-evaluations/${eid}/run`, {method:'POST'}),
  listJobEvaluations: (id, {jobId=''}={}) => {
    const params = new URLSearchParams(jobId?{job_id:jobId}:{});
    const q = params.toString();
    return request(`/conversations/${id}/job-evaluations${q?'?'+q:''}`);
  },
  readJobEvaluation: (id, eid) =>
    request(`/conversations/${id}/job-evaluations/${eid}`),
  createImprovementProposal: (id, body) =>
    request(`/conversations/${id}/improvement-proposals`,
      {method:'POST', body:JSON.stringify(body)}),
  listImprovementProposals: id =>
    request(`/conversations/${id}/improvement-proposals`),
  readImprovementProposal: (id, pid) =>
    request(`/conversations/${id}/improvement-proposals/${pid}`),
  acceptImprovementProposal: (id, pid) =>
    request(`/conversations/${id}/improvement-proposals/${pid}/accept`, {method:'POST'}),
  rejectImprovementProposal: (id, pid) =>
    request(`/conversations/${id}/improvement-proposals/${pid}/reject`, {method:'POST'}),
  markImprovementProposalImplemented: (id, pid) =>
    request(`/conversations/${id}/improvement-proposals/${pid}/implemented`, {method:'POST'}),
  recurringDefects: (id, {minCount=1}={}) =>
    request(`/conversations/${id}/recurring-defects?min_count=${encodeURIComponent(String(minCount))}`)
};
