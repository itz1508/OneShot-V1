"""Read-only artifact provenance from immutable admitted job scope.

Never rebind an artifact to current conversation selection. Historical results
keep their original source hashes even after a source is detached.
"""
import json
from fastapi import HTTPException
from systems.store import Store


def artifact_record(store: Store, conversation_id: str, artifact_id: str) -> dict:
    row = store.one('SELECT * FROM artifacts WHERE id=? AND conversation_id=?',
                    (artifact_id, conversation_id))
    if row is None:
        raise HTTPException(404, 'Artifact not found')
    return row


def evidence_records(store: Store, conversation_id: str, artifact_id: str) -> list[dict]:
    artifact = artifact_record(store, conversation_id, artifact_id)
    job = store.one('SELECT scope_json FROM jobs WHERE id=? AND conversation_id=?',
                    (artifact['job_id'], conversation_id))
    if job is None:
        raise HTTPException(409, 'Original job scope unavailable')
    admitted = json.loads(job['scope_json'])
    used = set(json.loads(artifact['source_ids_json']))
    if len(admitted) != len({x['id'] for x in admitted}) or used != {x['id'] for x in admitted}:
        raise HTTPException(409, 'Artifact provenance differs from admitted scope')
    result = []
    for item in admitted:
        row = store.one('SELECT name FROM sources WHERE id=?', (item['id'],))
        # Availability is determined from the bytes stored at the admitted hash,
        # never from a current source link or a newer revision.
        try:
            store.files.read(item['sha256'])
            available = True
        except (FileNotFoundError, ValueError):
            available = False
        result.append({'source_id': item['id'],
                       'name': row['name'] if row else '[source metadata unavailable]',
                       'version': item['version'], 'sha256': item['sha256'],
                       'available': available})
    return result


def evidence_bytes(store: Store, conversation_id: str, artifact_id: str, source_id: str) -> bytes:
    for item in evidence_records(store, conversation_id, artifact_id):
        if item['source_id'] == source_id:
            if not item['available']:
                raise HTTPException(409, 'Retained original bytes unavailable or invalid')
            return store.files.read(item['sha256'])
    raise HTTPException(404, 'Source not referenced by artifact')


def export_record(store: Store, conversation_id: str, artifact_id: str) -> dict:
    """Typed artifact export; does not impersonate summary-only output.json."""
    artifact = artifact_record(store, conversation_id, artifact_id)
    return {'artifact_id': artifact_id, 'job_id': artifact['job_id'],
            'kind': artifact['kind'], 'provider': artifact['provider'],
            'content': artifact['content'],
            'limitations': json.loads(artifact['limitations_json']),
            'sources': evidence_records(store, conversation_id, artifact_id)}
