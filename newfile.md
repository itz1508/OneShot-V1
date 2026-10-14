# Useful downloaded ideas not installed in OneShot-V1

Reviewed 2026-10-12 (America/Los_Angeles). This file consolidates the small amount of potentially useful, uninstalled material from the downloaded Markdown files. It is a review note, not an approved build plan or evidence that a feature exists.

## 1. Optional objective templates in System Chat

Source: `OneShot_System_Implementation_Plan.md`, optional additions table ("TextMate-inspired snippets").

Current V1: System Chat has objective binding and a read-only scope preview, but no dedicated picker that inserts an editable Objective / Expected Output / Constraints template. Such a picker could help operators state bounded tasks consistently. Keep the inserted text inert and editable; it must not submit a message, attach a source, start a job, or grant authority. Before implementing, confirm that operators need this workflow and specify the exact UI behavior. Then verify keyboard/focus behavior, no unintended POST, and the existing browser journey.

Status: potentially useful, **not installed or approved**. No package dependency follows from this idea.

## 2. External execution sandbox, only if OneShot gains an execution handoff

Source: `OneShot_v1.3.0_SANDBOX_DEPLOYMENT_CORRECTED.md`.

Current V1: the downloaded guide describes a separate, older confirmed-package and hash handoff. The installed v6.0.11 workflow does not establish that same handoff contract. If a future approved feature executes user-supplied code, the useful boundary is to verify the immutable package and hash before execution and run it in an isolated process/container with scoped secrets, network access, filesystem access, and resource limits. Reconcile the handoff schema with current V1 before selecting any sandbox runtime.

Status: conditional architecture reference, **not installed or approved**. Do not deploy the older guide as-is.

## No direct import

The remaining downloaded files either describe older candidates, duplicate current documentation, or target other repositories. The v6.0.11 evaluation references are already installed in `OneShot/docs/evaluation/`; all eight named diagrams are already in `OneShot/docs/WORKFLOWS.md`. Current P11 semantic and real-model blockers remain owned by the existing V1 documents and are not rewritten here.
