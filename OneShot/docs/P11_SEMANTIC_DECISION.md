# P11-semantic: unresolved product-decision boundary

## Context

P11-structural (shipped) uses the explicit `prompt_evaluations` criteria vocabulary
(`contains`, `contains_ci`, `absent`, `max_length`, `has_source_id`,
`quality_outcome`, `declares_variable`). These are byte-level or state-level checks
over the published prompt version and are deterministic.

P11-semantic is the complement: does the published prompt produce an output that
is *task-relative correct* against defined expectations? This has remained
`REQUIRES_PRODUCT_DECISION` since v5 Phase 11 because the answer requires an
accepted answer to the following four questions, which are **product decisions**,
not implementation choices.

## The unresolved acceptance questions

Each must be answered before the implementation can wire a corresponding gate.

1. **Which evaluator?**
   Options presented, not chosen:
   - (a) An LLM-as-judge admitted via `request_text`, same transport the I05
     advisory analysis uses, with an explicit `kind='semantic_eval'` provenance
     marker so results remain advisory until an operator approves them.
   - (b) A fixed set of per-task reference artifacts (golden outputs) with
     exact-match or BLEU-style comparison; applicable only to tasks the
     operator classifies as "closed answer".
   - (c) An operator-only accepted/rejected pass-through (humans grade a
     sampled subset); the shipped `job_reviews` table already supports this,
     but it is not a scored evaluator.
   Decision required: which of (a)/(b)/(c) — or a combination — is the authorized
   evaluator for a given published prompt version?

2. **What are the success criteria?**
   Deterministic criteria (P11-structural) are boolean per-criterion.
   Semantic criteria need a scoring policy. Options:
   - A binary pass/fail label from the evaluator per output (no numeric score).
   - A per-criterion scalar score with a threshold.
   - A per-task rubric with multiple scored dimensions aggregated by an
     explicit function.
   Decision required: label vs scored (which scoring policy); and when scored,
   is a numeric threshold acceptable, or must it be defined per prompt?

3. **What evidence must be preserved?**
   Shipped structural results in `prompt_evaluations.result_json` are
   deterministic and reproducible. Semantic results need:
   - Model identity and parameters at evaluation time.
   - Input fixture + resolved variables.
   - Expected behaviour statement (operator-authored).
   - Observed output.
   - Evaluator identity + response.
   - A label indicating whether the operator agreed with the evaluator.
   Decision required: evidence envelope schema + retention policy.

4. **Where does the semantic evaluator plug in?**
   Options:
   - (α) A new mandatory gate `prompt_semantic_eval_e2e` in
     `scripts/verify_release.py`, with its own `OPTIONAL_GATES` placement and
     prerequisite checks (parallel to `live_model_browser_e2e`).
   - (β) A per-prompt-version decoration inside the existing Prompt Workspace
     UI, run on operator demand (same shape as the shipped optimizer flow,
     which is already explicitly advisory).
   - (γ) Both: (β) for operator-driven iteration and (α) as a mandatory CI
     gate before release.
   Decision required: which plug-in point(s), and whether (α) is a mandatory
   gate or an optional one.

## What is NOT being requested from the agent

Per directive §6: the agent must **not** invent a semantic score, threshold, or
acceptance rule. The three regression tests for the advisory I05 flow already
enforce the "advisory, never authoritative" contract that answers (1)(a)
depends on; semantic evaluation would reuse that contract plus one of the
labels/scoring policies named above.

## Status

Open; blocks only the P11-semantic axis of acceptance. All other P-scenarios
are either runtime-independent complete, structurally complete, or
`MODEL_RUNTIME_UNAVAILABLE`-blocked separately.
