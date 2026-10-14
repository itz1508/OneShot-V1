"""Trace surface tests: events filters, latest(), per-node duration_ms."""
from __future__ import annotations

from systems.operations import events, latest, trace


def _attach(c, cid, name="r.md", content="Preserve all data."):
    r = c.post(
        f"/api/conversations/{cid}/sources/actions",
        json={"action": "INPUT_SOURCE", "name": name, "content": content},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _message(c, cid, text="Objective: preserve evidence"):
    r = c.post(
        f"/api/conversations/{cid}/messages",
        json={"channel": "system", "content": text},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _admit(c, cid, source_id, prompt_id, key="trace_filter_a_123"):
    r = c.post(
        f"/api/conversations/{cid}/jobs",
        json={
            "operation": "auto_generate",
            "prompt_message_id": prompt_id,
            "source_ids": [source_id],
            "expected_versions": {source_id: 1},
            "idempotency_key": key,
        },
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _run_one_job(c, app, cid):
    src = _attach(c, cid)
    msg = _message(c, cid)
    jid = _admit(c, cid, src["source_id"], msg)
    while True:
        processed = app.state.worker.step()
        if not processed:
            break
    return jid, src["source_id"]


def test_events_filters_narrow_results(conversation):
    c, app, cid = conversation
    jid, _ = _run_one_job(c, app, cid)
    # Baseline: unfiltered returns many events.
    all_events = events(app.state.store, cid, 0, 500)
    assert len(all_events) >= 5
    # Filter by node_id — should include only events tagged with that node.
    scanner = events(app.state.store, cid, 0, 500, node_id="scanner")
    assert scanner, "scanner must have emitted at least one event"
    assert all(e["node_id"] == "scanner" for e in scanner)
    # Filter by kind — node_completed only.
    completed = events(app.state.store, cid, 0, 500, kind="node_completed")
    assert completed and all(e["kind"] == "node_completed" for e in completed)
    # Filter by job_id — all rows carry the same job.
    for_job = events(app.state.store, cid, 0, 500, job_id=jid)
    assert for_job and all(e["job_id"] == jid for e in for_job)


def test_latest_returns_most_recent_event(conversation):
    c, app, cid = conversation
    jid, _ = _run_one_job(c, app, cid)
    row = latest(app.state.store, cid, jid)
    assert row is not None
    # The latest event for a completed job should be a job terminal event.
    assert row["kind"] in {"job_completed", "job_failed"}
    assert row["job_id"] == jid


def test_latest_endpoint_returns_null_before_any_event(conversation):
    c, app, cid = conversation
    # A job id we never admit must return {"latest": null} and HTTP 200.
    r = c.get(f"/api/conversations/{cid}/jobs/" + "0" * 32 + "/latest")
    assert r.status_code == 200, r.text
    assert r.json() == {"latest": None}


def test_trace_reports_duration_for_completed_nodes(conversation):
    c, app, cid = conversation
    jid, _ = _run_one_job(c, app, cid)
    projection = trace(app.state.store, cid, jid, include_events=False)
    assert projection["job_id"] == jid
    with_duration = [n for n in projection["nodes"] if "duration_ms" in n]
    assert with_duration, "at least one completed node must report duration_ms"
    for node in with_duration:
        assert node["duration_ms"] >= 0
        assert "started_at" in node and "ended_at" in node


def test_events_endpoint_accepts_filter_query_params(conversation):
    c, app, cid = conversation
    jid, _ = _run_one_job(c, app, cid)
    r = c.get(
        f"/api/conversations/{cid}/events",
        params={"job_id": jid, "kind": "node_started", "limit": 50},
    )
    assert r.status_code == 200
    body = r.json()["events"]
    assert body and all(e["kind"] == "node_started" and e["job_id"] == jid for e in body)


def test_events_since_until_time_window_filters_real_events(conversation):
    """``since``/``until`` on the real events() query clip by the recorded
    ``created_at`` wall-clock, using real emitted events (no mocked time).
    """
    c, app, cid = conversation
    jid, _ = _run_one_job(c, app, cid)
    all_events = events(app.state.store, cid, 0, 500, job_id=jid)
    assert len(all_events) >= 3, 'need multiple events to split a window'
    # Pick a timestamp strictly between the first and the last; the window
    # ``[all[0], boundary)`` must drop every event at or after the boundary.
    all_events_sorted = sorted(all_events, key=lambda e: e['created_at'])
    boundary = all_events_sorted[-1]['created_at']
    windowed = events(app.state.store, cid, 0, 500, job_id=jid, until=boundary)
    assert windowed, 'since/until window excluded every event'
    assert all(e['created_at'] < boundary for e in windowed), (
        'until is exclusive; events at the boundary must be excluded'
    )
    assert len(windowed) < len(all_events), (
        'until must drop at least the terminal event'
    )
    # ``since`` on the terminal timestamp must return every event at or after it.
    tail = events(app.state.store, cid, 0, 500, job_id=jid,
                  since=all_events_sorted[-1]['created_at'])
    assert tail, 'since on the final event must include that event'
    assert all(e['created_at'] >= all_events_sorted[-1]['created_at'] for e in tail)
