"""Diagnostic foreground latency comparison with/without System Background.

Synthetic input; isolated temporary SQLite and source files. This is NOT a
production performance SLO or browser benchmark.
Run: python -m scripts.benchmark_background --jobs 50
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from statistics import median
import tempfile
import time
import threading

from systems.background import BackgroundWorker
from systems.contracts import InputSource, MessageCreate, JobCreate
from systems.operations import Worker, source_action, create_conversation, add_message, admit
from systems.settings import Settings
from systems.store import Store
from systems.contracts import ConversationCreate


def _p95(values: list[float]) -> float:
    ordered=sorted(values)
    return ordered[max(0,int(0.95*(len(values)-1)))]


def measure(base: Path, total: int, with_background: bool) -> dict:
    store=Store(base)
    cfg=Settings(base,'bench-token-long-and-private-123456')
    cid=create_conversation(store,ConversationCreate(title='Background diagnostic'))['id']
    source=source_action(store,cid,InputSource(action='INPUT_SOURCE',name='requirements.md',
                        content='Evidence must preserve source scope.\n'*30))
    mid=add_message(store,cid,MessageCreate(channel='system',content='Produce source evidence packet.'))['id']
    for i in range(total):
        admit(store,cid,JobCreate(operation='auto_generate',prompt_message_id=mid,
            source_ids=[source['source_id']],expected_versions={source['source_id']:1},
            idempotency_key=f'benchmark-{i:06d}'))
    foreground=Worker(store,cfg)
    background=BackgroundWorker(store)
    stop=threading.Event()
    counter={'evaluated':0}
    def background_loop():
        while not stop.is_set():
            result=background.step()
            if result:counter['evaluated']+=1
            else:stop.wait(.004)
    thread=None
    if with_background:
        thread=threading.Thread(target=background_loop,daemon=True,name='benchmark-background')
        thread.start()
    durations=[]
    for i in range(total):
        started=time.perf_counter()
        job=foreground.step()
        durations.append((time.perf_counter()-started)*1000)
        assert job is not None
    stop.set()
    if thread:
        thread.join(timeout=10)
        if thread.is_alive():raise RuntimeError('Background benchmark thread did not stop')
    from collections import Counter
    jobs=Counter(x['status'] for x in store.all('SELECT status FROM jobs'))
    assert jobs=={'completed':total},jobs
    return {'jobs':total,'background_active':with_background,
            'foreground_latency_ms':{'p50':round(median(durations),3),'p95':round(_p95(durations),3),
                                     'max':round(max(durations),3)},
            'background_evaluations_during_load':counter['evaluated']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--jobs',type=int,default=50)
    args=parser.parse_args()
    if not 2<=args.jobs<=1000:parser.error('Jobs must be between 2 and 1000')
    with tempfile.TemporaryDirectory(prefix='oneshot-background-benchmark-') as tmp:
        root=Path(tmp)
        baseline=measure(root/'baseline',args.jobs,False)
        concurrent=measure(root/'concurrent',args.jobs,True)
    print(json.dumps({'test':'synthetic_foreground_contention_diagnostic',
                      'baseline':baseline,'background':concurrent,
                      'performance_slo':'not_specified',
                      'conclusion':'comparative measurement only; no production latency guarantee'},indent=2))


if __name__=='__main__':main()
