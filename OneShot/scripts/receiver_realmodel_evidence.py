"""Generate real-model acceptance evidence for one scenario.

Run this on a host that has a reachable llama.cpp (or an authorised hosted provider) AFTER
executing the matching scenario via OneShot's HTTP surface. The resulting JSON file is
consumed by `scripts/verify_release.py` to mark the scenario `VERIFIED`.

Usage:
    uv run python -m scripts.receiver_realmodel_evidence \\
        --scenario P09 \\
        --model-endpoint http://127.0.0.1:8080/v1/chat/completions \\
        --model-name <gguf-id> \\
        --job-id <32-hex> \\
        --artifact-id <32-hex>

The HMAC key MUST come from `ONESHOT_EVIDENCE_HMAC_KEY` and MUST match whatever the
operator uses on the verifier host.

For P09 the `--job-id` is the executing job, `--artifact-id` is the resulting
`artifacts.id`.  For P12-real-model and I05-real-model the `--job-id` is the surrounding
conversation / review job (used for provenance only), `--artifact-id` is the
`prompt_optimizations.id` or `improvement_proposals.id` respectively.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import secrets
import sqlite3
import subprocess
import time
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _sha_for_scenario(root: pathlib.Path, scenario: str, aid: str, jid: str) -> str:
    db = root / 'data' / 'oneshot.sqlite3'
    if not db.is_file():
        raise SystemExit(f'OneShot SQLite not found at {db}')
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        if scenario == 'P09':
            row = con.execute('SELECT content FROM artifacts WHERE id=? AND job_id=?',
                              (aid, jid)).fetchone()
            if row is None:
                raise SystemExit(f'artifacts row not found: aid={aid} job_id={jid}')
            content = row['content']
        elif scenario == 'P12-real-model':
            row = con.execute('SELECT proposed_content FROM prompt_optimizations WHERE id=?',
                              (aid,)).fetchone()
            if row is None:
                raise SystemExit(f'prompt_optimizations row not found: id={aid}')
            content = row['proposed_content']
        elif scenario == 'I05-real-model':
            row = con.execute('SELECT issue_summary FROM improvement_proposals WHERE id=?',
                              (aid,)).fetchone()
            if row is None:
                raise SystemExit(f'improvement_proposals row not found: id={aid}')
            content = row['issue_summary']
        else:
            raise SystemExit(f'unknown scenario {scenario}')
    data = content.encode('utf-8') if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _release_identity() -> str:
    """Prefer git when available (dev host); fall back to BUILD_MANIFEST host.git_sha
    (clean release install).  The verifier mirrors this contract — directive v6.0.7 §2.
    """
    try:
        out = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                                      stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        if out:
            return out
    except Exception:
        pass
    manifest = ROOT / 'BUILD_MANIFEST.json'
    if manifest.is_file():
        try:
            rec = json.loads(manifest.read_text())
            sha = (rec.get('host') or {}).get('git_sha') or ''
            if sha:
                return sha
        except Exception:
            pass
    return ''


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument('--scenario', required=True, choices=('P09', 'P12-real-model', 'I05-real-model'))
    p.add_argument('--model-endpoint', required=True)
    p.add_argument('--model-name', required=True)
    p.add_argument('--job-id', required=True)
    p.add_argument('--artifact-id', required=True)
    p.add_argument('--data-dir', default=str(ROOT),
                   help='OneShot working directory containing data/oneshot.sqlite3')
    args = p.parse_args(argv)

    key = os.environ.get('ONESHOT_EVIDENCE_HMAC_KEY', '').strip()
    if not key:
        raise SystemExit('ONESHOT_EVIDENCE_HMAC_KEY must be set')

    parsed = urllib.parse.urlparse(args.model_endpoint)
    host = parsed.hostname or ''
    try: loopback = ipaddress.ip_address(host).is_loopback
    except ValueError: loopback = host in ('localhost',)
    if parsed.scheme not in ('http', 'https') or not loopback:
        raise SystemExit(f'model_endpoint must be loopback http(s): got {args.model_endpoint}')

    sha = _sha_for_scenario(pathlib.Path(args.data_dir), args.scenario,
                            args.artifact_id, args.job_id)
    commit = _release_identity()
    if not commit:
        raise SystemExit('release identity unavailable: no git tree and no BUILD_MANIFEST.host.git_sha')

    nonce = secrets.token_hex(16)
    body = '|'.join((args.scenario, commit, args.job_id, sha, nonce)).encode('utf-8')
    proof = hmac.new(key.encode('utf-8'), body, hashlib.sha256).hexdigest()

    rec = {
        'scenario': args.scenario,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'oneshot_commit': commit,
        'model_endpoint': args.model_endpoint,
        'model_name': args.model_name,
        'job_id': args.job_id,
        'artifact_id': args.artifact_id,
        'artifact_sha256': sha,
        'proof': proof,
        'nonce': nonce,
    }
    out_dir = ROOT / 'data' / 'realmodel_evidence'
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'{args.scenario}.json'
    out.write_text(json.dumps(rec, indent=2) + '\n')
    print(json.dumps({'wrote': str(out), 'scenario': args.scenario,
                      'oneshot_commit': commit, 'artifact_sha256': sha,
                      'nonce': nonce}))


if __name__ == '__main__':
    main()
