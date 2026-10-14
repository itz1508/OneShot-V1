"""API transport only; System owns operations. No demo-progress paths."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import asyncio,csv,io,json,secrets,time,threading,uuid
from collections import defaultdict
from fastapi import FastAPI,Depends,Header,HTTPException,Query,Request
from fastapi.responses import Response,StreamingResponse,JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from fastapi.staticfiles import StaticFiles
from systems.settings import Settings
from systems.store import Store,uid,timestamp,emit
from systems.contracts import (SourceAction,ConversationCreate,SessionChange,MessageCreate,JobCreate,
                 DraftCreate,DraftUpdate,PrepareApply,ConfirmApply,AgentReply,
                 ArtifactEvidenceBundle,ArtifactExportRecord,SummaryOutput,
                 PromptAssetCreate,PromptDraftUpdate,PromptPublish,PromptRestore,
                 PromptResolve,PromptEvaluationCreate,PromptOptimizeRequest,
                 JobReviewBody,JobEvaluationBody,ImprovementProposalBody)
from systems.operations import (Worker,create_conversation,change_session,add_message,source_action,conv,source,admit,
                                   recover,events,trace,agent_reply,latest,list_jobs)
from systems.apply import prepare as prepare_apply,confirm as confirm_apply,target_state,applied_readback
from systems.model_transport import installed_agents
from systems.background import BackgroundWorker, recover_background, report as background_report
from systems.evidence import evidence_records, evidence_bytes, export_record
from systems import prompts
from systems import improvement_loop
from capabilities.catalog import capability_report

def create_app(settings:Settings|None=None,auto_worker:bool=True,generator=None,
               auto_background:bool|None=None)->FastAPI:
    cfg=settings or Settings.from_env();store=Store(cfg.data_dir)
    agent_connections=installed_agents(cfg)
    recover(store,agent_available=bool(agent_connections))
    worker=Worker(store,cfg,generator)
    background_worker=BackgroundWorker(store)
    # Worker liveness heartbeat (directive v6.0 §6 "Priority 4"). last_tick_at is updated on
    # every successful foreground_pump iteration; /ready reads it to detect a stalled worker.
    _pump_state={'last_tick_at':time.time(),'last_exception':None,'started_at':time.time()}
    start_background = (auto_worker and cfg.system_background) if auto_background is None else auto_background
    @asynccontextmanager
    async def lifespan(app:FastAPI):
        stopping=asyncio.Event()
        background_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='oneshot-background') if start_background else None
        async def foreground_pump():
            while not stopping.is_set():
                try:
                    await asyncio.to_thread(worker.step)
                    _pump_state['last_tick_at']=time.time()
                    _pump_state['last_exception']=None
                except Exception as _exc:
                    _pump_state['last_exception']=repr(_exc)
                    logging.getLogger('oneshot.worker').exception('Worker pump failed')
                try:await asyncio.wait_for(stopping.wait(),timeout=.1)
                except asyncio.TimeoutError:pass
        async def background_pump():
            loop=asyncio.get_running_loop()
            # Single-server restart contract: requeue interrupted background evaluations.
            await loop.run_in_executor(background_pool,recover_background,store)
            while not stopping.is_set():
                try:await loop.run_in_executor(background_pool,background_worker.step)
                except Exception:logging.getLogger('oneshot.background').error('Background scheduler error')
                try:await asyncio.wait_for(stopping.wait(),timeout=1.0)
                except asyncio.TimeoutError:pass
        foreground_task=asyncio.create_task(foreground_pump()) if auto_worker else None
        background_task=asyncio.create_task(background_pump()) if start_background else None
        try:yield
        finally:
            stopping.set()
            if foreground_task:await foreground_task
            if background_task:await background_task
            if background_pool:background_pool.shutdown(wait=True,cancel_futures=True)
    app=FastAPI(title='OneShot System',version='0.3.0',lifespan=lifespan)
    app.state.store=store;app.state.worker=worker;app.state.background_worker=background_worker
    sessions = {}  # single-process, expiring operator browser sessions
    # G1: per-key token-bucket rate limiter. Defaults 60 req / rolling 60 s per bucket.
    # Operators / E2E can raise ceiling via ONESHOT_RATE_LIMIT_MAX / ONESHOT_RATE_LIMIT_WINDOW_SECONDS.
    import os as _os
    try: _rate_window_seconds = max(1, int(_os.getenv('ONESHOT_RATE_LIMIT_WINDOW_SECONDS') or '60'))
    except ValueError: _rate_window_seconds = 60
    try: _rate_max = max(1, int(_os.getenv('ONESHOT_RATE_LIMIT_MAX') or '60'))
    except ValueError: _rate_max = 60
    _rate_buckets: dict[str, list] = defaultdict(list)
    _rate_lock = threading.Lock()
    def _rate_allow(bucket_key: str) -> bool:
        now = time.time()
        with _rate_lock:
            dq = _rate_buckets[bucket_key]
            cutoff = now - _rate_window_seconds
            # Drop timestamps older than the window.
            i = 0
            for i, ts in enumerate(dq):
                if ts >= cutoff:
                    break
            else:
                i = len(dq)
            del dq[:i]
            if len(dq) >= _rate_max:
                return False
            dq.append(now)
            return True
    # G3: Prometheus-style counters.
    _metrics_lock = threading.Lock()
    _metrics = {
        'http_requests_total': defaultdict(int),  # keyed by (status_bucket,method)
        'auth_failures_total': 0,
        'rate_limited_total': 0,
        'prompt_published_total': 0,
        'prompt_restored_total': 0,
        'jobs_admitted_total': 0,
        'jobs_completed_total': 0,
        'jobs_failed_total': 0,
    }
    def _bump(name, delta=1, label=None):
        with _metrics_lock:
            if label is not None:
                _metrics[name][label] += delta
            else:
                _metrics[name] += delta
    attempts = {}
    session_lock = threading.Lock()
    class BrowserLogin(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        password: str = Field(min_length=1, max_length=512)

    def browser_entry(request:Request):
        cookie = request.cookies.get('oneshot_session')
        with session_lock:
            entry = sessions.get(cookie) if cookie else None
            if entry and entry['expires'] <= time.time():
                sessions.pop(cookie, None); entry = None
        if not entry:raise HTTPException(401,'Browser session required')
        return entry

    def same_origin(request:Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403,'Cross-origin requests are not permitted')

    @app.post('/auth/login')
    def browser_login(body:BrowserLogin,request:Request,response:Response):
        same_origin(request)
        host=request.client.host if request.client else 'unknown'
        now=time.time()
        with session_lock:
            hits=[t for t in attempts.get(host,[]) if now-t < _rate_window_seconds]
            if len(hits)>=5:raise HTTPException(429,'Too many attempts')
            if not cfg.browser_password or not secrets.compare_digest(body.password,cfg.browser_password):
                attempts[host]=hits+[now]
                raise HTTPException(401,'Invalid browser credentials')
            attempts.pop(host,None)
            token=secrets.token_urlsafe(40)
            csrf=secrets.token_urlsafe(32)
            sessions[token]={'expires':now+8*3600,'csrf':csrf}
        response.set_cookie('oneshot_session',token,max_age=8*3600,httponly=True,samesite='strict',secure=request.url.scheme=='https',path='/')
        return {'authenticated':True,'csrf':csrf}

    @app.get('/auth/session')
    def browser_session(request:Request):
        entry=browser_entry(request)
        return {'authenticated':True,'csrf':entry['csrf']}

    @app.post('/auth/logout')
    def browser_logout(request:Request,response:Response):
        same_origin(request)
        entry=browser_entry(request)
        if not secrets.compare_digest(request.headers.get('x-oneshot-csrf',''),entry['csrf']):
            raise HTTPException(403,'CSRF verification required')
        token=request.cookies.get('oneshot_session')
        with session_lock:sessions.pop(token,None)
        response.delete_cookie('oneshot_session',path='/')
        return {'authenticated':False}

    @app.middleware('http')
    async def _correlation_and_rate_limit(request:Request,call_next):
        # G2 Request correlation id
        rid = request.headers.get('x-request-id') or uuid.uuid4().hex
        request.state.request_id = rid
        # G1 Rate limit by (ip, session_cookie). Both buckets must pass.
        ip = request.client.host if request.client else 'unknown'
        session_cookie = request.cookies.get('oneshot_session') or ''
        bucket_key = f'ip:{ip}|sess:{session_cookie[:16]}'
        if not _rate_allow(bucket_key):
            _bump('rate_limited_total')
            response = JSONResponse(
                {'detail': f'Rate limit exceeded ({_rate_max} req / {_rate_window_seconds}s per client)'},
                status_code=429)
            response.headers['Retry-After'] = str(_rate_window_seconds)
            response.headers['X-Request-Id'] = rid
            return response
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger('oneshot.http').exception(
                'request %s failed: %s %s', rid, request.method, request.url.path)
            raise
        _bump('http_requests_total', 1, label=(f'{response.status_code//100}xx', request.method))
        if response.status_code == 401:
            _bump('auth_failures_total')
        response.headers['X-Request-Id'] = rid
        return response

    @app.middleware('http')
    async def security_headers(request:Request,call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; report-uri /api/security/csp-violation"
        # G7 HSTS: only safe to send on https; harmless on http dev
        if request.url.scheme == 'https':
            response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        return response
    def auth(request:Request,authorization:str|None=Header(None)):
        if authorization and authorization.startswith('Bearer ') and secrets.compare_digest(authorization[7:],cfg.api_token):
            return
        # A wrong explicit Authorization header never falls back to cookies.
        if authorization:
            raise HTTPException(401,'Invalid bearer authentication')
        entry=browser_entry(request)
        if request.method not in ('GET','HEAD','OPTIONS'):
            same_origin(request)
            provided=request.headers.get('x-oneshot-csrf','')
            if not secrets.compare_digest(provided,entry['csrf']):
                raise HTTPException(403,'CSRF verification required')

    def writable_system(cid:str):
        record=conv(store,cid)
        if record['agent_active']:
            raise HTTPException(409,'OneShot System is read-only while Agent session has full access')

    @app.get('/metrics', include_in_schema=False)
    def metrics_endpoint():
        lines = ['# HELP oneshot_http_requests_total HTTP requests by status bucket and method',
                 '# TYPE oneshot_http_requests_total counter']
        with _metrics_lock:
            for (bucket, method), count in sorted(_metrics['http_requests_total'].items()):
                lines.append(f'oneshot_http_requests_total{{status="{bucket}",method="{method}"}} {count}')
            lines.extend([
                '# TYPE oneshot_auth_failures_total counter',
                f'oneshot_auth_failures_total {_metrics["auth_failures_total"]}',
                '# TYPE oneshot_rate_limited_total counter',
                f'oneshot_rate_limited_total {_metrics["rate_limited_total"]}',
                '# TYPE oneshot_prompt_published_total counter',
                f'oneshot_prompt_published_total {_metrics["prompt_published_total"]}',
                '# TYPE oneshot_prompt_restored_total counter',
                f'oneshot_prompt_restored_total {_metrics["prompt_restored_total"]}',
                '# TYPE oneshot_jobs_admitted_total counter',
                f'oneshot_jobs_admitted_total {_metrics["jobs_admitted_total"]}',
                '# TYPE oneshot_jobs_completed_total counter',
                f'oneshot_jobs_completed_total {_metrics["jobs_completed_total"]}',
                '# TYPE oneshot_jobs_failed_total counter',
                f'oneshot_jobs_failed_total {_metrics["jobs_failed_total"]}',
            ])
        return Response('\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4')
    @app.post('/api/security/csp-violation', include_in_schema=False, status_code=204)
    async def csp_violation(request:Request):
        try:
            body = await request.body()
        except Exception:
            body = b''
        logging.getLogger('oneshot.security').warning('CSP violation: %s', body[:4096])
        return Response(status_code=204)
    @app.get('/health')
    def health():
        # Liveness: process + SQLite handle. File-store, frontend-build, model
        # provider readiness are reported on /ready; a load balancer should route
        # on /ready and drain on /ready=503 while still answering /health.
        components={}
        try:
            store.one('SELECT 1 AS ok');components['storage']='ok'
        except Exception:
            components['storage']='unavailable'
        try:
            store.files.sanity();components['file_store']='ok'
        except Exception:
            components['file_store']='unavailable'
        dist=cfg.frontend_dir or (Path(__file__).resolve().parents[1]/'frontend'/'dist')
        components['frontend']='ok' if dist.is_dir() and (dist/'index.html').is_file() else 'not_built'
        components['vision']=('configured' if cfg.vision_provider=='llama' and cfg.vision_endpoint and cfg.vision_model else 'not_configured')
        ok=components['storage']=='ok' and components['file_store']=='ok'
        if not ok:raise HTTPException(503,{'ok':False,'components':components})
        return {'ok':True,'components':components}
    _WORKER_STALL_SECONDS = max(5, int(_os.getenv('ONESHOT_WORKER_STALL_SECONDS') or '30'))
    _QUEUED_STALL_SECONDS = max(5, int(_os.getenv('ONESHOT_QUEUED_STALL_SECONDS') or '120'))

    def _worker_status():
        """Classify the foreground worker (directive v6.0 §6).

        Returns one of: idle_healthy | active | queued_waiting | stalled | failed | disabled.
        'idle_healthy' means: pump recently ticked, no backlog.
        'queued_waiting' means: pump recently ticked, oldest queued job age < threshold.
        'stalled' means: pump has not ticked for > _WORKER_STALL_SECONDS OR a queued/running
                         job is older than _QUEUED_STALL_SECONDS without turnover.
        'failed' means: last iteration raised an exception.
        'disabled' means: the pump was never started (auto_worker=False).
        """
        if not auto_worker:
            return 'disabled', {}
        now=time.time()
        age=now-_pump_state['last_tick_at']
        detail={'last_tick_age_seconds':round(age,3),
                'last_exception':_pump_state['last_exception'],
                'stall_threshold_seconds':_WORKER_STALL_SECONDS,
                'queued_threshold_seconds':_QUEUED_STALL_SECONDS}
        if _pump_state['last_exception']:
            return 'failed', detail
        if age > _WORKER_STALL_SECONDS:
            return 'stalled', detail
        # Backlog check: oldest queued/running job age vs threshold.
        try:
            row=store.one("SELECT MIN(created_at) AS oldest FROM jobs WHERE status IN ('queued','running')")
        except Exception:
            row=None
        if row and row.get('oldest'):
            import datetime
            try:
                oldest_dt=datetime.datetime.fromisoformat(row['oldest'].replace('Z','+00:00'))
                job_age=(datetime.datetime.now(datetime.timezone.utc)-oldest_dt).total_seconds()
                detail['oldest_backlog_age_seconds']=round(job_age,3)
                if job_age > _QUEUED_STALL_SECONDS:
                    return 'stalled', detail
                return 'active', detail
            except Exception:
                pass
        return 'idle_healthy', detail

    @app.get('/ready')
    def ready():
        # Readiness: 200 only when every component required to serve a real
        # request is ok. /health stays as liveness (process + DB).
        components={}
        try:
            store.one('SELECT 1 AS ok');components['storage']='ok'
        except Exception:
            components['storage']='unavailable'
        try:
            store.files.sanity();components['file_store']='ok'
        except Exception:
            components['file_store']='unavailable'
        dist=cfg.frontend_dir or (Path(__file__).resolve().parents[1]/'frontend'/'dist')
        components['frontend']='ok' if dist.is_dir() and (dist/'index.html').is_file() else 'not_built'
        components['vision']=('configured' if cfg.vision_provider=='llama' and cfg.vision_endpoint and cfg.vision_model else 'not_configured')
        worker_state,worker_detail=_worker_status()
        components['worker']=worker_state
        # Vision is OPTIONAL for readiness: 'not_configured' must not degrade /ready.
        core_ok=all(components.get(k)=='ok' for k in ('storage','file_store','frontend'))
        worker_ok=worker_state in ('idle_healthy','active','queued_waiting','disabled')
        ready_now=core_ok and worker_ok
        if not ready_now:
            raise HTTPException(503,{'ready':False,'components':components,'worker':worker_detail})
        return {'ready':True,'components':components,'worker':worker_detail}
    @app.get('/api/capabilities',dependencies=[Depends(auth)])
    def capabilities():
        # Source scanner/researcher/advisor are now sourced from capabilities.catalog
        # (auto-discovery) so the registry stays in sync with the actual Python
        # modules. The pkg-specific keys (model, agent_integrations) are overlaid
        # on top — strict superset of the previous hand-maintained response shape.
        base=capability_report(cfg.provider)
        base['auto_generator']['model']=cfg.model_name if cfg.provider!='evidence' else None
        base['agent_integrations']=[{'id':name,'model':connection.name}
                                    for name,connection in agent_connections.items()]
        base['vision']={'provider':cfg.vision_provider,
                        'configured':bool(cfg.vision_provider=='llama' and cfg.vision_endpoint and cfg.vision_model),
                        'model':cfg.vision_model if cfg.vision_provider=='llama' else None}
        return base
    @app.post('/api/conversations',dependencies=[Depends(auth)],status_code=201)
    def conversations_create(body:ConversationCreate):return create_conversation(store,body)
    @app.get('/api/conversations/{cid}',dependencies=[Depends(auth)])
    def conversations_get(cid:str):
        c=conv(store,cid)
        return {'id':cid,'title':c['title'],'agent_active':bool(c['agent_active']),
                'messages':store.all('SELECT id,channel,role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,rowid',(cid,))}
    @app.patch('/api/conversations/{cid}/session',dependencies=[Depends(auth)])
    def session(cid:str,body:SessionChange):return change_session(store,cid,body,agent_available=bool(agent_connections))
    @app.post('/api/conversations/{cid}/messages',dependencies=[Depends(auth)],status_code=201)
    def message(cid:str,body:MessageCreate):return add_message(store,cid,body)
    @app.post('/api/conversations/{cid}/agent/replies',dependencies=[Depends(auth)],status_code=201)
    def agent_send(cid:str,body:AgentReply):
        connection=agent_connections.get(body.provider)
        if connection is None:raise HTTPException(409,'Agent integration is not configured')
        return agent_reply(store,cid,body,connection)
    @app.post('/api/conversations/{cid}/sources/actions',dependencies=[Depends(auth)],status_code=201)
    def action(cid:str,body:SourceAction):
        writable_system(cid)
        return source_action(store,cid,body)
    @app.get('/api/conversations/{cid}/sources',dependencies=[Depends(auth)])
    def sources(cid:str):
        conv(store,cid)
        return store.all('''SELECT s.id,s.name,s.kind,s.origin,s.sha256,s.version,s.created_at FROM sources s
                JOIN source_links l ON l.source_id=s.id WHERE l.conversation_id=? AND s.deleted=0 ORDER BY s.created_at''',(cid,))
    @app.get('/api/conversations/{cid}/sources/available',dependencies=[Depends(auth)])
    def available_sources(cid: str):
        """Source inventory for ADD_SOURCE, names only; originals remain immutable."""
        conv(store,cid)
        return store.all("""SELECT id,name,kind,version,sha256 FROM sources
            WHERE deleted=0 AND id NOT IN (SELECT source_id FROM source_links WHERE conversation_id=?)
            ORDER BY created_at DESC LIMIT 100""", (cid,))
    @app.get('/api/conversations/{cid}/sources/{sid}/content',dependencies=[Depends(auth)])
    def content(cid:str,sid:str):
        s=source(store,cid,sid)
        if not s['sha256']:raise HTTPException(422,'Reference is not fetched')
        try:raw=store.files.read(s['sha256'])
        except (ValueError,FileNotFoundError):raise HTTPException(500,'Original source verification failed') from None
        return Response(raw,media_type='application/octet-stream')
    @app.get('/api/conversations/{cid}/jobs',dependencies=[Depends(auth)])
    def list_conversation_jobs(cid:str,query:str=Query(default='',max_length=200),
                               status:str=Query(default='',max_length=32),
                               limit:int=Query(default=20,ge=1,le=50),
                               offset:int=Query(default=0,ge=0,le=100000)):
        return list_jobs(store,cid,query=query,status=status,limit=limit,offset=offset)
    @app.get('/api/conversations/{cid}/jobs/export',dependencies=[Depends(auth)])
    def jobs_export(cid:str,
                    query:str=Query(default='',max_length=200),
                    status:str=Query(default='',max_length=32),
                    limit:int=Query(default=1000,ge=1,le=10000)):
        """Stream a CSV of persisted jobs + their artifact summary for this conversation.

        Reuses list_jobs() SQL (same auth, same scope, same LIKE escapes). The CSV
        is RFC-4180-formatted; artifact content is bounded and sanitised (control chars
        stripped) so a cell cannot escape its quoting. Original source bytes are
        never returned; only metadata is exported.
        """
        page = list_jobs(store, cid, query=query, status=status, limit=limit, offset=0)
        columns = ['job_id','operation','status','created_at','updated_at',
                   'objective_preview','source_names','source_versions',
                   'source_sha256s','source_ids','artifact_id','artifact_sha256',
                   'artifact_kind','artifact_provider','limitations','reason',
                   'inspection_modes','vision_model_ids']
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator='\n')
        writer.writerow(columns)
        yield_rows = buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
        def _sanitise(value):
            if value is None: return ''
            s = str(value)
            # Strip control chars (except tab) to keep the CSV cell self-contained.
            return ''.join(ch for ch in s if ch == '\t' or ord(ch) >= 32)
        def _rows():
            yield yield_rows
            for item in page['items']:
                art = None; limitations=[]; modes=[]; vision_ids=[]
                aid = item.get('artifact_id')
                if aid:
                    art_row = store.one("""SELECT id,kind,provider,content,limitations_json,source_ids_json
                                         FROM artifacts WHERE id=? AND conversation_id=?""", (aid, cid))
                    if art_row:
                        art = art_row
                        import json as _json, hashlib as _hashlib
                        try: limitations = _json.loads(art_row['limitations_json'])
                        except Exception: limitations = []
                # Scanner-level inspection modes come from source_inspected events for this job.
                for ev in store.all("""SELECT payload_json FROM events
                                     WHERE conversation_id=? AND job_id=? AND kind='source_inspected'""",
                                     (cid, item['id'])):
                    import json as _json
                    try:
                        p = _json.loads(ev['payload_json'])
                        if p.get('inspection_mode'): modes.append(p['inspection_mode'])
                        vinfo = p.get('vision') or {}
                        if vinfo.get('model_id'): vision_ids.append(vinfo['model_id'])
                    except Exception: pass
                import hashlib as _hashlib
                artifact_sha = _hashlib.sha256(art['content'].encode('utf-8')).hexdigest() if art else ''
                writer.writerow([
                    item['id'], item['operation'], item['status'],
                    item['created_at'], item['updated_at'],
                    _sanitise(item.get('objective_preview')),
                    ', '.join(_sanitise(s['name']) for s in item['sources']),
                    ', '.join(str(s['version']) for s in item['sources']),
                    ', '.join(_sanitise(s.get('sha256','')) for s in item['sources']),
                    ', '.join(s['id'] for s in item['sources']),
                    aid or '',
                    artifact_sha,
                    (art['kind'] if art else ''),
                    (art['provider'] if art else ''),
                    '; '.join(_sanitise(x) for x in limitations),
                    _sanitise(item.get('reason')),
                    ', '.join(modes),
                    ', '.join(vision_ids),
                ])
                chunk = buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
                yield chunk
        headers = {
            'Content-Disposition': f'attachment; filename="oneshot-run-history-{cid}.csv"',
            'Cache-Control': 'no-store',
            'X-Row-Count': str(len(page['items'])),
            'X-Total': str(page['total']),
        }
        return StreamingResponse(_rows(), media_type='text/csv', headers=headers)
    @app.post('/api/conversations/{cid}/jobs',dependencies=[Depends(auth)],status_code=202)
    def job_create(cid:str,body:JobCreate):return admit(store,cid,body)
    @app.get('/api/conversations/{cid}/jobs/{jid}',dependencies=[Depends(auth)])
    def job_get(cid:str,jid:str):
        conv(store,cid);row=store.one('SELECT * FROM jobs WHERE id=? AND conversation_id=?',(jid,cid))
        if row is None:raise HTTPException(404,'Job not found')
        row['scope']=json.loads(row.pop('scope_json'));return row
    @app.get('/api/conversations/{cid}/runs/{rid}',dependencies=[Depends(auth)])
    def run_get(cid:str,rid:str):
        conv(store,cid);row=store.one('''SELECT r.* FROM runs r JOIN jobs j ON j.id=r.job_id WHERE r.id=? AND j.conversation_id=?''',(rid,cid))
        if row is None:raise HTTPException(404,'Run not found')
        return row
    @app.get('/api/conversations/{cid}/artifacts/{aid}',dependencies=[Depends(auth)])
    def artifact_get(cid:str,aid:str):
        conv(store,cid);row=store.one('SELECT * FROM artifacts WHERE id=? AND conversation_id=?',(aid,cid))
        if row is None:raise HTTPException(404,'Artifact not found')
        row['source_ids']=json.loads(row.pop('source_ids_json'))
        row['limitations']=json.loads(row.pop('limitations_json'))
        return row
    @app.get('/api/conversations/{cid}/artifacts/{aid}/evidence',dependencies=[Depends(auth)],response_model=ArtifactEvidenceBundle)
    def artifact_evidence(cid: str, aid: str):
        conv(store, cid)
        return {'artifact_id': aid, 'sources': evidence_records(store, cid, aid)}

    @app.get('/api/conversations/{cid}/artifacts/{aid}/evidence/{sid}/content',dependencies=[Depends(auth)])
    def artifact_evidence_source(cid: str, aid: str, sid: str):
        conv(store, cid)
        raw = evidence_bytes(store, cid, aid, sid)
        return Response(raw, media_type='application/octet-stream',
                        headers={'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/conversations/{cid}/artifacts/{aid}/summary',dependencies=[Depends(auth)],response_model=SummaryOutput)
    def summary_export(cid: str, aid: str):
        conv(store,cid)
        artifact=store.one('SELECT kind,provider,content FROM artifacts WHERE id=? AND conversation_id=?',(aid,cid))
        if artifact is None:raise HTTPException(404,'Artifact not found')
        if artifact['kind']!='summary' or artifact['provider']!='model':
            raise HTTPException(409,'Only verified-contract model summaries support output.json')
        summary=SummaryOutput.model_validate({'summary':artifact['content']})
        return JSONResponse(summary.model_dump(),headers={'Content-Disposition':'attachment; filename="output.json"'})

    @app.get('/api/conversations/{cid}/artifacts/{aid}/export',dependencies=[Depends(auth)],response_model=ArtifactExportRecord)
    def artifact_export(cid: str, aid: str):
        conv(store, cid)
        export = ArtifactExportRecord.model_validate(export_record(store, cid, aid))
        # This is an artifact export, not the accepted summary-only output.json.
        return JSONResponse(export.model_dump(), headers={
            'Content-Disposition': f'attachment; filename="oneshot-artifact-{aid}.json"'
        })

    @app.get('/api/conversations/{cid}/background',dependencies=[Depends(auth)])
    def system_background_report(cid:str,limit:int=Query(30,ge=1,le=100)):
        conv(store,cid)
        return {**background_report(store,cid,limit),'execution_enabled':start_background}
    @app.get('/api/conversations/{cid}/events',dependencies=[Depends(auth)])
    def event_get(cid:str,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500),
                  job_id:str|None=Query(None),kind:str|None=Query(None,max_length=64),
                  node_id:str|None=Query(None,max_length=64),
                  since:str|None=Query(None,max_length=40),until:str|None=Query(None,max_length=40)):
        return {'events':events(store,cid,after,limit,job_id=job_id,kind=kind,
                                node_id=node_id,since=since,until=until)}
    @app.get('/api/conversations/{cid}/events/stream',dependencies=[Depends(auth)])
    async def stream(cid:str,request:Request,after:int=Query(0,ge=0),last_event_id:str|None=Header(None,alias='Last-Event-ID')):
        conv(store,cid)
        if last_event_id:
            try:after=max(after,int(last_event_id))
            except ValueError:raise HTTPException(422,'Invalid Last-Event-ID') from None
        async def generator():
            cursor=after;last=time.monotonic()
            while not await request.is_disconnected():
                batch=await asyncio.to_thread(events,store,cid,cursor,100)
                for e in batch:
                    cursor=e['seq']
                    yield 'id: '+str(cursor)+'\nevent: activity\ndata: '+json.dumps(e,sort_keys=True)+'\n\n'
                if time.monotonic()-last>=10:
                    last=time.monotonic();yield ': keepalive\n\n'
                await asyncio.sleep(.25)
        return StreamingResponse(generator(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})
    @app.get('/api/conversations/{cid}/compare/runs',dependencies=[Depends(auth)])
    def compare_runs(cid:str,left:str=Query(...,min_length=1),right:str=Query(...,min_length=1)):
        import difflib
        def _fetch(jid):
            job = store.one(
                'SELECT id,operation,status,artifact_id,prompt_version_id,resolved_variables_json,created_at'
                ' FROM jobs WHERE id=? AND conversation_id=?', (jid, cid))
            if job is None: raise HTTPException(404, f'Job {jid!r} not found')
            artifact = None
            if job['artifact_id']:
                artifact = store.one(
                    'SELECT id,kind,provider,content,created_at FROM artifacts WHERE id=? AND conversation_id=?',
                    (job['artifact_id'], cid))
            return {
                'job_id': job['id'],
                'status': job['status'],
                'operation': job['operation'],
                'created_at': job['created_at'],
                'prompt_version_id': job['prompt_version_id'],
                'resolved_variables': (json.loads(job['resolved_variables_json']) if job['resolved_variables_json'] else None),
                'artifact': (dict(artifact) if artifact else None),
            }
        L = _fetch(left); R = _fetch(right)
        left_text = (L['artifact'] or {}).get('content') or ''
        right_text = (R['artifact'] or {}).get('content') or ''
        diff = list(difflib.unified_diff(left_text.splitlines(), right_text.splitlines(),
                   fromfile=f"job {left[:8]}", tofile=f"job {right[:8]}", lineterm=''))
        return {
            'left': L, 'right': R,
            'identical': left_text == right_text,
            'unified_diff': '\n'.join(diff),
        }
    @app.get('/api/conversations/{cid}/jobs/{jid}/trace',dependencies=[Depends(auth)])
    def job_trace(cid:str,jid:str,include_events:bool=Query(True)):
        return trace(store,cid,jid,include_events=include_events)
    @app.get('/api/conversations/{cid}/jobs/{jid}/latest',dependencies=[Depends(auth)])
    def job_latest(cid:str,jid:str):
        return {'latest':latest(store,cid,jid)}
    @app.get('/api/conversations/{cid}/sources/{sid}/draft',dependencies=[Depends(auth)])
    def source_draft_latest(cid:str,sid:str):
        conv(store,cid);source(store,cid,sid)
        row=store.one('''SELECT d.id,d.revision,r.content FROM drafts d
                         JOIN draft_revisions r ON r.draft_id=d.id AND r.revision=d.revision
                         WHERE d.conversation_id=? AND d.source_id=?''',(cid,sid))
        if row is None: raise HTTPException(404,'No draft for this source')
        return row
    @app.post('/api/conversations/{cid}/drafts',dependencies=[Depends(auth)],status_code=201)
    def draft_create(cid:str,body:DraftCreate):
        writable_system(cid)
        source(store,cid,body.source_id);did=uid()
        with store.tx() as con:
            con.execute('INSERT INTO drafts VALUES(?,?,?,1)',(did,cid,body.source_id))
            con.execute('INSERT INTO draft_revisions VALUES(?,?,?,?)',(did,1,body.content,timestamp()))
            emit(con,cid,'draft_created',payload={'draft_id':did,'revision':1})
        return {'id':did,'revision':1,'content':body.content}
    @app.patch('/api/conversations/{cid}/drafts/{did}',dependencies=[Depends(auth)])
    def draft_update(cid:str,did:str,body:DraftUpdate):
        writable_system(cid)
        with store.tx() as con:
            row=con.execute('SELECT * FROM drafts WHERE id=? AND conversation_id=?',(did,cid)).fetchone()
            if row is None:raise HTTPException(404,'Draft not found')
            if row['revision']!=body.expected_revision:raise HTTPException(409,'Draft revision conflict')
            n=row['revision']+1
            con.execute('UPDATE drafts SET revision=? WHERE id=?',(n,did))
            con.execute('INSERT INTO draft_revisions VALUES(?,?,?,?)',(did,n,body.content,timestamp()))
            emit(con,cid,'draft_revised',payload={'draft_id':did,'revision':n})
        return {'id':did,'revision':n,'content':body.content}
    @app.get('/api/conversations/{cid}/drafts/{did}',dependencies=[Depends(auth)])
    def draft_get(cid:str,did:str):
        conv(store,cid);row=store.one('''SELECT d.id,d.revision,r.content FROM drafts d JOIN draft_revisions r
            ON r.draft_id=d.id AND r.revision=d.revision WHERE d.id=? AND d.conversation_id=?''',(did,cid))
        if row is None:raise HTTPException(404,'Draft not found')
        return row
    # ---- Prompt lifecycle (feature spec §3-§11, §13) -----------------------
    @app.post('/api/conversations/{cid}/prompts',dependencies=[Depends(auth)],status_code=201)
    def prompts_create(cid:str,body:PromptAssetCreate):
        writable_system(cid)
        return prompts.create_asset(store,cid,body)
    @app.get('/api/conversations/{cid}/prompts',dependencies=[Depends(auth)])
    def prompts_list(cid:str):
        return prompts.list_assets(store,cid)
    @app.get('/api/conversations/{cid}/prompts/{aid}',dependencies=[Depends(auth)])
    def prompts_read(cid:str,aid:str):
        return prompts.read_asset(store,cid,aid)
    @app.patch('/api/conversations/{cid}/prompts/{aid}/draft',dependencies=[Depends(auth)])
    def prompts_draft(cid:str,aid:str,body:PromptDraftUpdate):
        writable_system(cid)
        return prompts.update_draft(store,cid,aid,body)
    @app.post('/api/conversations/{cid}/prompts/{aid}/publish',dependencies=[Depends(auth)],status_code=201)
    def prompts_publish(cid:str,aid:str,body:PromptPublish|None=None):
        writable_system(cid)
        return prompts.publish(store,cid,aid,body)
    @app.get('/api/conversations/{cid}/prompts/{aid}/versions',dependencies=[Depends(auth)])
    def prompts_versions(cid:str,aid:str):
        return prompts.list_versions(store,cid,aid)
    @app.get('/api/conversations/{cid}/prompts/{aid}/versions/{vref}',dependencies=[Depends(auth)])
    def prompts_version(cid:str,aid:str,vref:str):
        return prompts.read_version(store,cid,aid,vref)
    @app.post('/api/conversations/{cid}/prompts/{aid}/resolve',dependencies=[Depends(auth)])
    def prompts_resolve(cid:str,aid:str,body:PromptResolve):
        return prompts.resolve_variables(store,cid,aid,body)
    @app.post('/api/conversations/{cid}/prompts/{aid}/restore',dependencies=[Depends(auth)],status_code=201)
    def prompts_restore(cid:str,aid:str,body:PromptRestore):
        writable_system(cid)
        return prompts.restore(store,cid,aid,body)
    @app.get('/api/conversations/{cid}/prompts/{aid}/compare',dependencies=[Depends(auth)])
    def prompts_compare(cid:str,aid:str,left:str=Query(...,min_length=1),right:str=Query(...,min_length=1)):
        return prompts.compare(store,cid,aid,left,right)
    @app.post('/api/conversations/{cid}/prompts/{aid}/evaluations',dependencies=[Depends(auth)],status_code=201)
    def prompts_eval_create(cid:str,aid:str,body:PromptEvaluationCreate):
        writable_system(cid)
        return prompts.create_evaluation(store,cid,aid,body)
    @app.post('/api/conversations/{cid}/prompts/{aid}/evaluations/{eid}/run',dependencies=[Depends(auth)])
    def prompts_eval_run(cid:str,aid:str,eid:str):
        writable_system(cid)
        return prompts.run_evaluation(store,cid,aid,eid)
    @app.get('/api/conversations/{cid}/prompts/{aid}/evaluations',dependencies=[Depends(auth)])
    def prompts_eval_list(cid:str,aid:str):
        return prompts.list_evaluations(store,cid,aid)
    @app.get('/api/conversations/{cid}/prompts/{aid}/evaluations/{eid}',dependencies=[Depends(auth)])
    def prompts_eval_read(cid:str,aid:str,eid:str):
        return prompts.read_evaluation(store,cid,aid,eid)
    @app.post('/api/conversations/{cid}/prompts/{aid}/optimizations',dependencies=[Depends(auth)],status_code=201)
    def prompts_opt_propose(cid:str,aid:str,body:PromptOptimizeRequest|None=None):
        writable_system(cid)
        return prompts.propose_optimization(store,cid,aid,body or PromptOptimizeRequest(),cfg)
    @app.get('/api/conversations/{cid}/prompts/{aid}/optimizations',dependencies=[Depends(auth)])
    def prompts_opt_list(cid:str,aid:str):
        return prompts.list_optimizations(store,cid,aid)
    @app.get('/api/conversations/{cid}/prompts/{aid}/optimizations/{oid}',dependencies=[Depends(auth)])
    def prompts_opt_read(cid:str,aid:str,oid:str):
        return prompts.read_optimization(store,cid,aid,oid)
    @app.post('/api/conversations/{cid}/prompts/{aid}/optimizations/{oid}/accept',dependencies=[Depends(auth)])
    def prompts_opt_accept(cid:str,aid:str,oid:str):
        writable_system(cid)
        return prompts.accept_optimization(store,cid,aid,oid)
    @app.post('/api/conversations/{cid}/prompts/{aid}/optimizations/{oid}/reject',dependencies=[Depends(auth)])
    def prompts_opt_reject(cid:str,aid:str,oid:str):
        writable_system(cid)
        return prompts.reject_optimization(store,cid,aid,oid)
    # ---- System-owned improvement loop (directive §4-§14) ----------------
    @app.put('/api/conversations/{cid}/jobs/{jid}/review',dependencies=[Depends(auth)])
    def job_review_upsert(cid:str,jid:str,body:JobReviewBody):
        writable_system(cid)
        return improvement_loop.upsert_review(store,cid,jid,body)
    @app.get('/api/conversations/{cid}/jobs/{jid}/review',dependencies=[Depends(auth)])
    def job_review_read(cid:str,jid:str):
        return improvement_loop.read_review(store,cid,jid)
    @app.get('/api/conversations/{cid}/reviews',dependencies=[Depends(auth)])
    def job_reviews_list(cid:str,limit:int=Query(default=50,ge=1,le=200),
                          offset:int=Query(default=0,ge=0,le=100000)):
        return improvement_loop.list_reviews(store,cid,limit=limit,offset=offset)

    @app.post('/api/conversations/{cid}/jobs/{jid}/evaluations',
              dependencies=[Depends(auth)],status_code=201)
    def job_evaluation_create(cid:str,jid:str,body:JobEvaluationBody):
        writable_system(cid)
        return improvement_loop.create_evaluation(store,cid,jid,body)
    @app.post('/api/conversations/{cid}/job-evaluations/{eid}/approve',dependencies=[Depends(auth)])
    def job_evaluation_approve(cid:str,eid:str):
        writable_system(cid)
        return improvement_loop.approve_evaluation(store,cid,eid)
    @app.post('/api/conversations/{cid}/job-evaluations/{eid}/reject',dependencies=[Depends(auth)])
    def job_evaluation_reject(cid:str,eid:str):
        writable_system(cid)
        return improvement_loop.reject_evaluation(store,cid,eid)
    @app.post('/api/conversations/{cid}/job-evaluations/{eid}/run',dependencies=[Depends(auth)])
    def job_evaluation_run(cid:str,eid:str):
        writable_system(cid)
        return improvement_loop.run_evaluation(store,cid,eid)
    @app.get('/api/conversations/{cid}/job-evaluations',dependencies=[Depends(auth)])
    def job_evaluations_list(cid:str,job_id:str|None=Query(default=None),
                             limit:int=Query(default=50,ge=1,le=200),
                             offset:int=Query(default=0,ge=0,le=100000)):
        return improvement_loop.list_evaluations(store,cid,job_id=job_id,limit=limit,offset=offset)
    @app.get('/api/conversations/{cid}/job-evaluations/{eid}',dependencies=[Depends(auth)])
    def job_evaluation_read(cid:str,eid:str):
        return improvement_loop.read_evaluation(store,cid,eid)

    @app.post('/api/conversations/{cid}/improvement-proposals',
              dependencies=[Depends(auth)],status_code=201)
    def improvement_proposal_create(cid:str,body:ImprovementProposalBody):
        writable_system(cid)
        return improvement_loop.create_proposal(store,cid,body)
    @app.get('/api/conversations/{cid}/improvement-proposals',dependencies=[Depends(auth)])
    def improvement_proposals_list(cid:str,limit:int=Query(default=50,ge=1,le=200),
                                   offset:int=Query(default=0,ge=0,le=100000)):
        return improvement_loop.list_proposals(store,cid,limit=limit,offset=offset)
    @app.get('/api/conversations/{cid}/improvement-proposals/{pid}',dependencies=[Depends(auth)])
    def improvement_proposal_read(cid:str,pid:str):
        return improvement_loop.read_proposal(store,cid,pid)
    @app.post('/api/conversations/{cid}/improvement-proposals/{pid}/accept',dependencies=[Depends(auth)])
    def improvement_proposal_accept(cid:str,pid:str):
        writable_system(cid)
        return improvement_loop.accept_proposal(store,cid,pid)
    @app.post('/api/conversations/{cid}/improvement-proposals/{pid}/reject',dependencies=[Depends(auth)])
    def improvement_proposal_reject(cid:str,pid:str):
        writable_system(cid)
        return improvement_loop.reject_proposal(store,cid,pid)
    @app.post('/api/conversations/{cid}/improvement-proposals/{pid}/implemented',dependencies=[Depends(auth)])
    def improvement_proposal_implemented(cid:str,pid:str):
        writable_system(cid)
        return improvement_loop.mark_proposal_implemented(store,cid,pid)
    @app.post('/api/conversations/{cid}/jobs/{jid}/advisory-analysis',dependencies=[Depends(auth)])
    def improvement_advisory_analysis(cid:str,jid:str):
        writable_system(cid)
        return improvement_loop.request_advisory_analysis(store,cid,jid,settings)
    @app.get('/api/conversations/{cid}/recurring-defects',dependencies=[Depends(auth)])
    def recurring_defects(cid:str,min_count:int=Query(default=2,ge=1,le=50)):
        return improvement_loop.recurring_defects(store,cid,min_count=min_count)
    @app.get('/api/conversations/{cid}/apply/target',dependencies=[Depends(auth)])
    def apply_target(cid: str, destination: str = Query(..., min_length=1, max_length=240)):
        conv(store,cid)
        return target_state(store,destination)
    @app.get('/api/conversations/{cid}/applied/{apply_id}',dependencies=[Depends(auth)])
    def applied_get(cid: str, apply_id: str):
        conv(store,cid)
        return applied_readback(store,cid,apply_id)
    @app.post('/api/conversations/{cid}/apply/prepare',dependencies=[Depends(auth)])
    def apply_prepare(cid:str,body:PrepareApply):
        writable_system(cid)
        return prepare_apply(store,cid,body)
    @app.post('/api/conversations/{cid}/apply/confirm',dependencies=[Depends(auth)])
    def apply_confirm(cid:str,body:ConfirmApply):
        writable_system(cid)
        return confirm_apply(store,cid,body)
    dist = cfg.frontend_dir or (Path(__file__).resolve().parents[1] / 'frontend' / 'dist')
    if (dist / 'index.html').is_file():
        app.mount('/',StaticFiles(directory=str(dist),html=True),name='frontend')
    else:
        @app.get('/')
        def frontend_not_built():
            raise HTTPException(503,'Frontend is not built; run npm run build in frontend')
    return app
