# OneShot browser UI

No external framework. Actual `package.json` and `package-lock.json` are in this directory.

Build: `npm ci && npm run check && npm run build` (Node 22+).

FastAPI serves the resulting `dist/` assets on the same origin as `/api/*` and `/auth/*`.
Sign-in uses an operator password configured with `ONESHOT_BROWSER_PASSWORD` in the server environment; the API bearer token never appears in client code. Cookie auth requires the server-issued `X-Oneshot-CSRF` header for writes. Browser sessions expire on server restart; persisted conversations do not.

[1] Agent Chat is optional. The header Agent control toggles the drawer, while the Agent selector inside the drawer lists only integrations configured on the server. Settings displays configured provider status without accepting secrets. Agent replies are attributed, stored and replayed through the real authenticated API. Activating an Agent makes System mutation endpoints read-only until deactivation; drawer visibility alone does not change session authority. System Chat, source preparation, results and real trace do not depend on installing an Agent. In the absence of an Agent provider, its composer is disabled and the System remains available.

`npm test` and syntax checks are diagnostics. The full verification gate is `python -m tests.e2e_browser` after a clean frontend/backend build, with actual Chromium navigation and a real Uvicorn worker.

## System workspace context

Send a System message as the explicit processing objective. The Attachments panel
shows the latest **saved** message and binds its ID to the selected source IDs at
Start. An unsent message in the System composer blocks Start to avoid silently
using a stale objective. The server enforces prompt ownership and job replay
identity; no browser-supplied System privilege or automatic Apply is inferred.

## Optional pre-send context review

Tick **Review context before sending** in System Chat to inspect an editable copy-only structured draft, read-only verbatim original, and exact outbound payload. Cancel makes no message request; approval saves exactly the shown content through the existing authenticated System message endpoint. The review is browser-local and does not launch processing or invoke Agents. See `docs/PRE_SEND_CONTEXT_REVIEW.md`. Node tests: `npm test`; real Chromium check: `python -m tests.e2e_presend` from the project root.
