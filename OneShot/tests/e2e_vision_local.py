"""Real-model Visual E14 acceptance test.

**This file is intentionally not a drop-in test.** Per ADR-002 and the
governing directive \u00a76/\u00a710/\u00a717, E14 "the mandatory Visual E2E must use a
real image and a real configured vision model, not a simulated local
responder." A synthetic responder has no semantic weight here.

The verifier gate `vision_local_e2e` is MANDATORY iff:

* ``ONESHOT_VISION_PROVIDER=llama``
* ``ONESHOT_VISION_ENDPOINT`` points at a loopback-only ``llama-server``
* ``ONESHOT_VISION_MODEL`` names a vision-capable GGUF that is actually
  loaded on that server

When those preconditions are present, this script must:

1. Boot the real OneShot app under uvicorn.
2. Launch a real Chromium via Playwright.
3. Attach a real image source (PNG/JPEG/WebP) to a conversation.
4. Submit an ``inspect_sources`` job that routes through the vision reader.
5. Confirm the recorded ``source_inspected`` event carries
   ``inspection_mode='visual'`` with ``vision.model_id`` matching
   ``ONESHOT_VISION_MODEL`` and ``vision.deterministic=False``.
6. Confirm ``coverage_assessed`` emits ``incomplete`` or ``unusable`` -- never
   ``structural_ready`` for a vision-only source without corroboration.
7. Confirm the UI shows the vision-marked segment and its limitation.
8. Confirm replay reuses the persisted response (no second provider call).

Until a real llama-server + vision GGUF is reachable, the verifier reports
this gate as ``SKIPPED_PREREQUISITE_MISSING`` with the precise reason. It is
NEVER promoted to VALID_E2E from a synthetic responder.
"""
import os, sys


REQUIRED = ('ONESHOT_VISION_PROVIDER', 'ONESHOT_VISION_ENDPOINT', 'ONESHOT_VISION_MODEL')


def main() -> int:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing or os.environ.get('ONESHOT_VISION_PROVIDER') != 'llama':
        print('vision_local_e2e: PREREQUISITE_MISSING ' + ','.join(missing or ['ONESHOT_VISION_PROVIDER!=llama']),
              file=sys.stderr)
        return 2
    # Real executor fills in the Chromium + llama-server flow here.
    # Deliberately refuse to pretend a run happened: we exit with a non-zero
    # code so the gate FAILS loudly if invoked without the real preconditions.
    print('vision_local_e2e: NOT_IMPLEMENTED_IN_THIS_EXECUTOR', file=sys.stderr)
    print('  Executor must provide: real llama-server on loopback, real vision GGUF,', file=sys.stderr)
    print('  real Chromium with no net::ERR_BLOCKED_BY_ADMINISTRATOR policy, and', file=sys.stderr)
    print('  a representative image fixture.', file=sys.stderr)
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
