# Optional System Chat pre-send context review

## Status and ownership

The review UI is part of the **System Chat frontend** (plain JavaScript, not React). It is disabled by default and is unrelated to optional Agent Chat or System Background learning.

The implementation reuses the authenticated `POST /api/conversations/{id}/messages` endpoint. It introduces no new provider, generation endpoint, database table, or source mutation operation.

## UI behavior

1. Enter a System message. The **Review context before sending** checkbox enables the optional modal; otherwise `Send` follows the existing direct-send path.
2. A review freezes the original composer contents and conversation ID. A **deterministic copy-only draft** is assembled from explicit labels (`Objective`, `Expected output`, `Constraints`, `Scope`, etc.) using `frontend/presend.js`. It is **not** a semantic or AI summary.
3. The modal shows an editable structured summary, a read-only **verbatim original**, and the **exact outbound message**. When no summary exists or the user clears the draft, the outbound message is the original unchanged.
4. `Cancel` and `Escape` close the modal without making a save request. The composer retains the original text.
5. `Approve and send` posts one frozen payload only after confirming the original and conversation are unchanged. Concurrent approvals are guarded. The saved server response must match the approved payload; errors keep the review open.
6. In approved summary mode, the saved message includes the user-approved summary followed by `Original user input (verbatim):` and the **unaltered original content**. This is preserved in the existing messages table; it is *not* a separate source attachment.
7. Sending a message saves it as the objective; it does not automatically run Scan, Read, Prepare, or Generate. The existing Start operation still needs selected sources.

## Known limitations

- There is no installed semantic summarizer or model call in the existing System workflow. Arbitrary unlabeled text is not semantically summarized. The user may manually edit the summary, or send original text alone.
- The original is preserved **within the saved message payload**, not as a separately addressable source or dedicated original field. Adding either would require a separately approved data contract.
- The modal does not perform background jobs or tool calls.
- The client guards against immediate duplicate clicks, but the current message POST contract has no idempotency key. If the server saves a message but the response is lost, retry could save a duplicate. Do not claim exactly-once delivery across network failures without a server-side idempotency contract.
- Browser E2E must be run on a host that permits Chromium to access the app's local URL; this development environment currently blocks local browser navigation.

## Validation

```bash
cd frontend
npm ci
npm test
npm run check
npm run build
cd ..
python -m pytest -q
python -m tests.e2e_http
python -m tests.e2e_presend
```

Unit tests verify cancel=zero requests, snapshot approval equals transmitted input, source preservation with line endings, stale inputs/conversations rejected, guarded repeat clicks, failure recovery, backend persistence and limits. The final browser test requires a working Playwright/Chromium connection.
