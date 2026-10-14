# Security policy

## Threat model (single-operator, local-first)

OneShot is designed to run as a **single-operator workspace** on a trusted host (desktop, workstation, or dedicated single-tenant VM). All data lives in local SQLite under `ONESHOT_DATA_DIR`. There is no multi-user permissions model, no cross-tenant isolation, and no network-exposed management plane.

| Concern | Design |
|---|---|
| Operator authentication | Browser session cookie (`oneshot_session`, `HttpOnly`, `SameSite=Strict`, `Secure` under HTTPS); API callers may alternatively present `Authorization: Bearer <ONESHOT_API_TOKEN>`. |
| Session store | In-memory, per-process, 8-hour expiry; **not multi-host**. See `docs/API.md`. |
| CSRF | `X-Oneshot-CSRF` header required on every state-mutating request from a browser session. Bearer-token callers are exempt because an exposed bearer is already full compromise. |
| Same-origin check | Enforced on `/auth/*` and on every CSRF-protected write. |
| Content Security Policy | `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'`. |
| Other response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `Permissions-Policy` deny-list for camera/microphone/geolocation/payment/usb/interest-cohort. |
| Transport | Operator deploys behind an HTTPS reverse proxy. The `Secure` cookie flag is automatically set when `request.url.scheme == 'https'`. |
| Source bytes | Content-addressed `FileStore` under `<ONESHOT_DATA_DIR>/files/<sha256[:2]>/<sha256>` — immutable by convention; readback verifies the hash. |
| Apply boundary | Two-step (`prepare` → `confirm`) with `expected_target_sha256`, atomic `os.replace`, and SHA-256 readback. Failures record `apply_failed` and never claim verified. |
| Dependency audit | `make audit` runs `pip-audit` (resolved from `uv.lock`) and `npm audit --omit=dev --audit-level=high`. CI runs both on every PR. |

## Reporting a vulnerability

Open a private security advisory on the repository or email the operator responsible for the deployment. Do **not** file a public issue for anything that is not already a published CVE in a pinned dependency.

Please include:

- OneShot version (see `pyproject.toml:[project].version`).
- Affected endpoint or module (`systems/*`, `capabilities/*`, `frontend/*`, `scripts/*`).
- Minimal reproduction (HTTP transcript, curl command, or test case).
- Impact: data disclosure, write without Apply, authentication bypass, DoS, supply-chain.

## Hardening checklist for operators

- Deploy only behind HTTPS; do not expose port 8787 directly.
- Rotate `ONESHOT_API_TOKEN` and `ONESHOT_BROWSER_PASSWORD` on every deployment; both are enforced ≥ 24 and ≥ 16 characters respectively by `systems.settings.Settings`.
- Mount `ONESHOT_DATA_DIR` on local disk (not NFS); run `scripts/backup.py` on a schedule and keep the output off-host.
- Run `make audit` as part of the deploy pipeline; fail the deploy on high/critical findings.
- Keep `make selfcheck` green: it round-trips `FileStore` and verifies the frontend build exists.
- Enable the Docker Compose healthcheck in `compose.yaml`.

## Non-goals (intentionally out of scope)

- Multi-tenant isolation, per-user ACLs, SSO/OIDC federation.
- Horizontal scale-out (single-writer SQLite + single-process session store).
- Secrets management for third-party model providers beyond server-side environment variables.
- Any public telemetry sink.
