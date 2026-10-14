# OneShot System — Input Context Preparation (candidate)

## Responsibility

The existing System controls the `Scan -> Read -> Prepare -> Systems.generate -> Validate` workflow. `systems/input_context.py` belongs **inside Prepare**, not to a new Agent, endpoint, provider, worker, or streaming subsystem. No new database columns or wire shape are required.

## Physical changes

- A job already selects a *saved* System message by immutable `prompt_message_id` and source versions/hashes.
- During `Worker.execute()`, after Scanner has inspected the chosen originals, `build_input_context()` assembles a deterministic context snapshot from the selected objective, earlier saved messages in the **same conversation**, and inspected source identity.
- The snapshot includes the exact current objective; explicit `Objective`, `Goal`, `Task`, `Expected output`, `Constraints`, or `Scope` labels are copied verbatim if authored. The parser **does not infer an unlabeled intent, semantic constraints, or meaning**.
- At most four immediately prior messages, within a 6,000-character ceiling, are supplied as **untrusted supporting context**. The count of omitted earlier messages is explicit. A message saved after the job's selected objective is never included, even when the job executes later.
- The existing `input_context_prepared` event records **only IDs, selected labels and omission counts**, never message content. The frontend continues displaying observed events only.
- In evidence mode the output includes a grounded, explicitly **nonsemantic** context brief. In configured model mode an `input_context` object is sent as untrusted data alongside the already-scoped original sources. `Systems.generate` remains the sole generation stage, accepting only prepared context.
- The frontend shows a lightweight, read-only **scope preview** of the saved request, checked originals, excluded unselected sources and historical-context boundary. It is not a semantic model summary and does not fetch sources.

## Core boundaries

- **System**, not Agent Chat, owns context assembly and validation.
- Pasted text must be attached as a selected `INPUT_SOURCE` to enter source inspection. Pasting it into the chat message alone sets an objective, **not a file/source**. Automatically promoting messages to source attachments would require separate product approval.
- Context items are **information**. Tool availability or named tools in the text do not grant execution or mutation privileges.
- No external VS Code `#` mention implementation, workspace index, semantic embedding, model invocation, web fetch or context-retrieval service is introduced.
- Historical conversation may inform an explicitly configured model but never overrides the current objective or trusted instructions.
- No change to artifact schema, `output.json` decision, source operations, or background evaluation scheduler.

## Tests and acceptance criteria

- Explicit labeled fields preserve user text exactly; freeform text is not misrepresented as a parsed summary.
- The selected request stays frozen when later messages are saved; no cross-conversation message leaks.
- History is bounded; omitted count remains visible; no silent truncation of prior messages.
- Metadata events never include raw historical content.
- The selected source list has stable identity, original version and SHA-256.
- Frontend preview displays actual selected source count and safe text nodes (no innerHTML).
- Python regressions, Node tests, static build and real HTTP integration pass in the supported environment.
- A configured model can use prior context; however **semantic summarization, long-conversation coherence and factual correctness are not established by the deterministic tests**. These require labeled evaluation fixtures and target environment model E2E.

## Official reference mapping (patterns only)

1. [Add context to chat](https://code.visualstudio.com/docs/chat/copilot-chat-context#_add-files-as-context): preserve explicit selected source scope and distinguish sources from prompt text. Do not copy VS Code UI commands or automatic indexing.
2. [Prompt examples](https://code.visualstudio.com/docs/agents/guides/prompt-examples): encourage clear objective, expected output and constraints. Do not invent missing instructions.
3. [Context engineering](https://code.visualstudio.com/docs/agents/guides/context-engineering-guide): progressive, bounded context and freshness. Do not install custom agents or massive instruction bundles.
4. [Tools and context reference](https://code.visualstudio.com/docs/agents/reference/tools-reference): tools take actions, context items provide information. Do not create tools just because they exist in VS Code.
5. [Add a feature](https://code.visualstudio.com/docs/agents/guides/add-a-feature): inspect baseline, narrow change, test and review. Do not assume its issue-filter example belongs in OneShot.
6. [Use tools](https://code.visualstudio.com/docs/agents/run/tools): verify work through existing means and respect permissions. No automatic autonomous agent chain or new provider.

## Deferred decisions

- Product approval for *message-only* processing with no selected source; current `JobCreate` requires at least one selected source.
- Separate actual semantic summary schema and `output.json` persistence/delivery contract. Existing evidence packet is not a verified semantic answer.
- Larger history retrieval/semantic ranking, references to specific prior messages and long-context compaction. These need explicit consumers, evaluation, retention and data-governance decisions.
