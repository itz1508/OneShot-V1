# ADR-002 — Selectable Visual Inspection (local llama.cpp)

**Status:** Accepted
**Supersedes:** ADR-001 D3, **for `VISUAL` only**. `FILES_AND_FOLDERS` and `RESEARCH_WHEN_NEEDED` remain frozen under ADR-001 D3.
**Date:** 2026-10-11

## Context

v2 shipped with `capabilities/scanner/tools/view.py::view()` raising
`ViewUnavailable('No image-inspection provider configured')` for every image
source. ADR-001 D3 and prd/overview.md classify `Visual` as Out of Scope.

The operator-visible outcome today: a submitted PNG/JPEG/WebP produces a
scanner `Observation(coverage='blocked', limitation='No image-inspection
provider configured')` and the job terminates with a precise reason. Nothing
in the pipeline shape has to change to admit image sources — the dispatch
anchor and the limitation taxonomy already exist.

## Decision

`Visual` becomes a System-owned, operator-selectable inspection mode under the
following fixed terms:

- **Provider: local `llama.cpp` only.** Loopback-only HTTP endpoint
  (`127.0.0.0/8`). No hosted-provider fallback is authorized. No ambient
  credential store is required.
- **Determinism: recorded non-deterministic inference.** `temperature=0` where
  the provider supports it. No guaranteed-determinism claim. Every call
  records `provider`, `model_id`, `weights_sha256`, `mmproj_sha256`
  (nullable), `source_sha256`, `source_version`, `response_sha256`,
  `temperature`, and `deterministic=False` as execution metadata on the
  resulting trace event. Replay reuses the persisted response; the model is
  NOT re-invoked.
- **Quality cap.** Vision-derived segments default to `INCOMPLETE`. Promotion
  to `SUFFICIENT` requires explicit corroboration from a non-vision source
  under the task's documented evidence criteria. `UNUSABLE` is returned when
  no meaningful text can be extracted. The empty-response path is a
  `Limitation`, not a success.
- **Image admission.** PNG, JPEG, WebP only. Enforced by magic-byte sniff +
  byte limit + bounded decode. GIF stays rejected as `Unsupported`.
- **No scope expansion.** `FILES_AND_FOLDERS` and `RESEARCH_WHEN_NEEDED`
  remain Out of Scope and are NOT superseded by this ADR.
- **No new authority.** Visual does NOT acquire ownership of workflow state,
  source management, Apply, or any security boundary. The vision provider is
  called by the Scanner capability exactly like the existing text reader.

## Consequences

- `systems/contracts.py` gains `InspectionMode` enum (`TEXT`, `VISUAL`,
  `MIXED`) and `vision_*` limitation codes.
- `systems/settings.py` gains `vision_provider: Literal['none','llama']`,
  `vision_endpoint`, `vision_model`, `vision_mmproj`, `vision_weights_sha256`
  with a loopback-only validator.
- `systems/model_transport.py` gains `request_vision()` adapter.
- `capabilities/scanner/tools/view.py` replaces `ViewUnavailable` with a real
  reader whose unconfigured path still raises `ViewUnavailable` and whose
  reachable-but-failing path raises distinct errors with precise limitation
  codes.
- `scripts/verify_release.py` gains optional gate `vision_local_e2e`:
  mandatory when `ONESHOT_VISION_PROVIDER=llama`, otherwise skipped with
  `missing_prerequisite='ONESHOT_VISION_PROVIDER != llama'`.
- The desktop UI gains a selectable Visual inspection mode that only lights
  up when `/health.vision_configured=true`.

## Non-goals

- Hosted vision providers.
- Multimodal agent chat.
- Image generation.
- Any form of OCR beyond what the configured vision model produces natively.
- Lifting the `FILES_AND_FOLDERS` or `RESEARCH_WHEN_NEEDED` freezes.
