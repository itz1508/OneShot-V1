# OneShot — Model integration contract and verification limits

**Status: Implemented in isolated candidate; NOT production verified.** This document is an operator guide for code that actually consumes the settings, not a new workflow approval.

## System versus Agent

- System is independent. `ONESHOT_PROVIDER=evidence` generates a truthful evidence packet with no AI call.
- `ONESHOT_PROVIDER=model` is the legacy OpenAI-compatible HTTPS transport. `openai` is a named OpenAI-compatible transport using the configured endpoint or official default. Both require `ONESHOT_MODEL_NAME` and `ONESHOT_MODEL_TOKEN`. Legacy custom HTTPS URLs remain operator-controlled.
- `ONESHOT_PROVIDER=gemini` sends native Gemini `generateContent` requests to Google's official host. Requires `ONESHOT_MODEL_NAME` (valid model ID) and `ONESHOT_MODEL_TOKEN` (Gemini API key). Output arrives through `candidates[].content.parts[].text` and is separately Pydantic-validated.
- `ONESHOT_PROVIDER=ollama` sends native nonstreaming `POST /api/chat` with `format=json` to an explicitly configured **loopback** HTTP endpoint (default `http://127.0.0.1:11434/api/chat`) and installed `ONESHOT_MODEL_NAME`. It is **not** a Docker-host auto-discovery feature. Docker Compose's loopback resolves inside the container; don't assume a host Ollama daemon is available there.
- Optional Agent Chat is separately configured using paired `ONESHOT_AGENT_OPENAI_TOKEN` and `ONESHOT_AGENT_OPENAI_MODEL`, paired `ONESHOT_AGENT_GEMINI_TOKEN` and `ONESHOT_AGENT_GEMINI_MODEL`, or `ONESHOT_AGENT_OLLAMA_MODEL` with optional loopback `ONESHOT_AGENT_OLLAMA_ENDPOINT`. The Agent's provider selection is in Agent Chat, not System dispatch. No browser API key form exists.
- Model provider calls never receive tool descriptions, never execute tool requests, never mutate sources, and never authorize Apply. Source content and user objectives are untrusted data.
- No automatic fallback between providers: a failing configured provider produces a failure, not an unannounced change in model or execution mode.

## Data limits, privacy and persistence

The configured System provider receives the current objective, selected readable source content, provenance IDs/hashes, and bounded earlier conversation context. Sending sources to a third-party provider **transfers that selected content to that provider**. Agent Chat sends only the user's Agent message and bounded prior Agent Chat history; it does not implicitly copy System sources. Operators must approve their provider/data processing policy before production activation.

Outputs are bounded by response bytes and validated by the existing strict `GeneratedDocument(document, source_ids_used)` contract. A model-generated artifact is not proof of factual equivalence, completeness, or compliance. The retained generic `provider=model` artifact kind is compatible with existing consumers; actual configured model/provider identifiers are recorded in executed model generation node event metadata. No unapproved `output.json` writer was added because a consumer and destination are not established.

**Threat boundaries:** credentials only in server environment; HTTPS required for remote providers, loopback-only HTTP for local Ollama, redirects disabled, unknown output rejected, tool calls rejected. System mutating endpoints are refused while an Agent session is active. OneShot is presently a **single-operator** deployment, not a multi-tenant public API.

## Evidence and remaining acceptance gates

- `tests/test_multi_provider.py` covers OpenAI-compatible, native Gemini, local Ollama wire shapes, negative output contracts, optional Agent session authority, idempotent persisted replies and sanitized failures using controlled transports.
- `tests/e2e_multi_provider_http.py` runs Uvicorn with a real SQLite store, browser-cookie/CSRF HTTP auth, a local protocol responder (not a model), actual Worker processing, persistent artifact/event/reply, authorization, Apply/readback and restart. It proves wiring, **not semantic intelligence**.
- Required for production acceptance: live configured models and legal credentials; a measured source-grounded semantic evaluation set; full browser-to-backend E2E with actual Chromium; Python 3.11 clean installation and lock; Docker/Compose startup and restart; completed security review and provider/data transfer policy.
- When these gates cannot run, report **NOT VERIFIED**, not `PASSED` or `VALID`.

API references for transport differences: <https://docs.ollama.com/api/chat>, <https://ai.google.dev/gemini-api/docs/structured-output>, <https://platform.openai.com/docs/api-reference/chat>.
