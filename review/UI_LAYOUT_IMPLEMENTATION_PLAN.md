# OneShot-V1 UI layout: implementation plan

Status: reviewable plan; no product code has been changed.

## 1. Target and source precedence

Implement in `D:/OneShot-V1/OneShot`. Use `C:/Users/itz15/Downloads/ChatGPT/## OneShot — Full display layout.txt` for State A/B/C behavior. Use `C:/Users/itz15/Downloads/ChatGPT/## layout separates three UI resp.txt` to resolve the screen grouping: left chat navigation, center conversation, and a collapsible right **System Summarize** region. In that right region, Attachments is an independently scrolling list and Editor/Review or Process Display is contextual detail, not a separate product screen. On wide screens these may be adjacent subpanels; at smaller widths they are stacked or switched within the same region. The main chat remains the dominant surface.

`apply_oneshot_ui_refresh.py` is a historical October 10 candidate patch, not this implementation. Its four expected before/after SHA-256 values do not match any of the four corresponding installed files (`frontend/index.html`, `app.js`, `styles.css`, `tests/layout.test.mjs`). Do not run `--apply` against OneShot-V1 or copy its opaque payload blindly. Its docstring also limits its claim to a visual correction without backend E2E or Agent integration.

## 2. Exact visual and interaction contract

| State | Left navigation and chat | Center | Right System Summarize | Bottom composer |
| --- | --- | --- | --- | --- |
| A: Agent open | Agent rail and Agent Chat visible; System rail remains visible | System Chat visible and read-only while the Agent session is active | Attachment list plus Editor/Review detail | Agent composer active only after server-confirmed Agent activation |
| B: Agent closed | Compact Agent reopen control and System rail; Agent Chat hidden | System Chat expands and has full access only after server-confirmed Agent deactivation | Same attachments and detail state | System composer active |
| C: processing | A or B chat layout and message history retained | Conversation and actual status updates remain visible | Attachment list stays; Process Display temporarily occupies the Editor/Review detail slot | Composer follows the confirmed chat owner; job controls stay in the right region |

Selecting a source opens/closes its detail without changing processing selection. Checking a source changes processing selection without opening it. Closing the right region expands the center; reopening restores the selected source, scroll positions, draft, and process state. Agent collapse and right-region collapse are separate actions. A failed Agent deactivation leaves System read-only and shows the failure; it must not paint State B as if deactivation succeeded.

## 3. Boundaries to preserve

- Vanilla ES modules and the existing `node build.mjs` copy build; no framework migration.
- Same-origin cookie/CSRF API in `frontend/api/client.js`; never add provider credentials to browser code.
- Server-owned Agent session flag (`PATCH /api/conversations/{cid}/session`), persisted messages, conversation ID, and source/job IDs.
- Immutable source originals and versions, explicit Start review, idempotent job admission, draft Save distinct from Apply, and Apply baseline/hash confirmation.
- Actual event replay with sequence cursors. The illustrative progress in the second reference is a visual concept only; do not show invented milestones, percentages, or semantic summaries.

## 4. Build phases and checkpoints

### Phase 0 - baseline, isolated implementation root

Create a separately named working copy from this exact installed export, excluding `.venv`, caches, and generated `dist`; record the 174-entry release checksum result and the working-copy source hashes. Verify there are no unexpected changes. Record baseline `npm.cmd run check`, `npm.cmd test`, and `npm.cmd run build`. Inspect existing browser E2E prerequisites. **Gate:** if the source or test baseline differs unexpectedly, reconcile it before editing.

### Phase 1 - tests for the three states (red)

Extend `frontend/tests/layout.test.mjs` and add focused pure state tests for: A/B/C projection, independent Agent/right collapse, composer ownership, failure-to-deactivate behavior, source open versus check, and detail restoration after a terminal job. Add browser assertions for panel geometry and keyboard/focus behavior to `tests/e2e_browser.py` or a focused new E2E module. Confirm the new tests fail against the current drawer layout. **Deliverable:** a failure record tied to each display rule, not just DOM-string assertions.

### Phase 2 - shell and responsive layout (green, then refactor)

Edit `frontend/index.html` and `frontend/styles.css` to add a compact Agent rail, Agent Chat, System rail, center System Chat, right System Summarize shell, independent attachment scroll area, and one contextual detail slot. Keep current login, settings, improvement-loop, prompt, review, and Apply controls reachable. Use CSS grid for desktop and explicit stacked/overlay states for narrow screens; avoid a six-column minimum width that overflows a laptop. Implement the right-panel collapse independently from the Agent collapse. Re-run Phase 1 geometry and focus checks; refactor duplicate layout selectors only after the states pass.

### Phase 3 - authority and composer (red/green)

Edit `frontend/app.js` and, if necessary, a small pure helper in `frontend/workspace.js`. Use server response to set Agent active/inactive; Agent close requests deactivation and waits for success before enabling System input. Keep separate unsent Agent and System drafts while presenting a single bottom composer slot; route submit through the existing `api.agentReply` or `api.message`. On reconnect, load server authority and restore the correct owner. Test no message crosses channels, no hidden active Agent silently unlocks System, and no loss of either conversation history.

### Phase 4 - System Summarize sources and review (red/green)

Keep `frontend/app.js` source IDs/versions and existing `frontend/api/client.js` operations. In the right region, provide Import/Send entry, independently scrolling attachment rows, expand/collapse details, Start review, latest operation, and prepared context/source observations. The current `sources` response has `name`, `kind`, `origin`, hash and version but no folder identity; plan a small optional `display_path` contract only if real folder grouping is required. Migrate `systems/store.py` and `systems/api.py` with backward compatibility, validate path segments, and keep IDs as the processing keys. Otherwise use a truthful flat list under an expandable All Sources group; do not fabricate `folder/`. Add a draft-versus-original Diff Review in the Editor detail using the recorded immutable original. Save draft and Apply remain separate actions. Test long lists, duplicate names, binary/unfetched references, and stale versions.

### Phase 5 - source-grounded output and real process state (red/green)

Reuse the existing `inspect_sources` job and `evidence_packet` artifact from `systems/operations.py` for source observations: label that output **Source observations**, not semantic Summary. Show a semantic Summary only for a verified model-produced summary artifact. Never relabel the input context scope preview as `result.md`. In `frontend/app.js`, retain the existing accepted-job/event-cursor path and `review-view`/`process-view` swap; keep Attachments and chat visible, show observed event text, coverage, last update and connection status, then restore Editor/Review on a confirmed terminal status without losing draft/selection. Test event gaps, reconnect, blocked/failed jobs, and user-opened review during a run.

### Phase 6 - Pause contract, before exposing the button

The current UI lifecycle reducer contains Pause states, but `frontend/api/client.js`, `systems/api.py`, and the worker have no pause/resume operation. Implement Pause as backend work, not a CSS control: define authenticated conversation-scoped pause/resume endpoints and strict wire contracts in `systems/contracts.py`; persist a request state; make `systems/operations.py` worker stop only at safe checkpoints, emit `pause_requested`, `pause_confirmed` or `pause_failed`, and resume from a proven checkpoint. Handle queued versus running jobs, repeat requests, restart recovery, and terminal races. Add backend tests before wiring the button in `frontend/index.html`/`app.js`. If a running operation cannot safely checkpoint, report Pause unavailable for that operation and do not show `Paused`. **Gate:** this phase needs a reviewed worker continuation design before coding; a UI-only Pause fails acceptance.

### Phase 7 - accessibility, browser proof, review

Use native buttons with synchronized `aria-expanded` and `aria-controls`; use a true tree role only if full tree keyboard behavior is implemented. Verify focus return after collapse, labeled active composer, screen-reader status messages, reduced motion, keyboard-only source/rail navigation, and contrast. Check desktop State A/B/C, narrow laptop, mobile portrait and landscape. Run `npm.cmd run check`, `npm.cmd test`, `npm.cmd run build`, relevant backend tests, then real Chromium login -> Agent activate/close -> source import/open/check -> Start -> process -> completion -> draft diff -> Save/Apply. Capture screenshots and inspect the final source/built-dist diff. Run the release verifier and report each unavailable gate precisely; do not infer product release readiness from UI tests.

## 5. Acceptance and handoff

- A, B, and C match the contract above, including right-region containment and main-chat dominance. Collapse/reopen does not erase chat, selection, draft, or job state.
- System mutation stays blocked while the server says Agent active; after confirmed Agent close, System input and Start become available according to their ordinary guards.
- Attachments scroll independently; open/check are independent; a source opens in contextual Editor detail. Diff Review compares exact original and current draft without applying it.
- Process Display comes from committed backend events; terminal completion restores review. Source observations and model Summary have distinct labels and provenance.
- Start uses the saved objective and selected immutable versions. Pause appears only after the backend contract, safe checkpoints, and tests pass.
- Red tests fail before their change and pass afterward; existing frontend/backend/E2E checks pass or have named, evidence-backed blockers. Review the working-copy diff and checksum impact before any promotion into `D:/OneShot-V1/OneShot`.

## 6. Reference use

- Mobbin: [Replit workspace](https://mobbin.com/screens/198661e0-96d5-4073-9ba7-797ee5df334b) for chat/preview adjacency and [Mintlify workspace](https://mobbin.com/screens/95876f85-2300-4ced-8c72-b2cf68955ee0) for compact navigation and content hierarchy. Study structure; do not copy their visual styling.
- Context7 W3C APG: [disclosure](https://github.com/w3c/aria-practices/blob/main/content/patterns/disclosure/examples/disclosure-image-description.html), [tree keyboard interaction](https://github.com/w3c/aria-practices/blob/main/content/patterns/treeview/treeview-pattern.html), and [ARIA role obligations](https://github.com/w3c/aria-practices/blob/main/content/practices/read-me-first/read-me-first-practice.html).
- Build Web Data Visualization: Process Display is an operational event list with observed facts, direct labels, stale/offline states, and mobile reading order; no chart renderer is needed.
- NVIDIA Skills catalog: no NVIDIA-specific UI dependency matches this task; do not install a GPU skill or add GPU requirements to the browser plan.
