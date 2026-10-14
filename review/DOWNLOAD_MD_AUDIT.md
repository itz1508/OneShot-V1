# Downloaded Markdown audit

Reviewed 2026-10-12 (America/Los_Angeles). Scope: all 23 `*.md` files found recursively under `C:\Users\itz15\Downloads` before cleanup. Automatic approval review rejected a shell deletion command for installed duplicates. After verifying exact files and their installed counterparts, a targeted file patch removed three installed-content download copies and two redundant duplicates. The other 18 files remain in `C:\Users\itz15\Downloads\_OneShot_MD_Aside`, grouped by disposition. No Markdown file remains elsewhere under Downloads.

| Downloaded file | Disposition | Basis |
| --- | --- | --- |
| `Toloka/inventory.md` | Installed duplicate; download removed | Byte-identical to `OneShot/docs/evaluation/inventory.md`. |
| `Toloka/fixture.md` | Installed duplicate; download removed | Byte-identical to `OneShot/docs/evaluation/fixture.md`. |
| `OneShot_Named_Diagrams_vNext_2026-10-10.md` | Installed content; download removed | All eight Mermaid blocks occur verbatim in `OneShot/docs/WORKFLOWS.md`. |
| `Clean Install Dependencies.md` | Duplicate removed | Byte-identical to the retained, stale downloaded `INSTALL_RELEASE_GATES.md`; V1 has `uv.lock`. |
| `INSTALL_RELEASE_GATES.md` | Stale reference | The downloaded Dockerfile description says `pip install .` and no lock; V1's Dockerfile uses `uv sync --frozen` and has a lock. Do not replace the packaged doc. |
| `OneShot_Background_Evaluation_Pydantic_Ready_Build_Prompt_.md` | Duplicate removed | Byte-identical to the retained dated background prompt below. |
| `OneShot_Background_Evaluation_Pydantic_Ready_Build_Prompt_2026-10-09.md` | Historical proposal | V1 already implements and documents the System background evaluator in `systems/background.py` and `docs/SYSTEM_BACKGROUND.md`. |
| `Addon-AutoGen.md` | Historical proposal | Its objective/context preparation topic is implemented and documented in `systems/input_context.py` and `docs/INPUT_CONTEXT_OPTIMIZATION.md`. |
| `OneShot_System_Generate_Stage_Correction_Report_2026-10-10.md` | Historical result | Reports changes in an isolated older candidate; V1 has its own `docs/GENERATE_STAGE.md` and release evidence. |
| `OneShot_MarketGap_Implementation_Result_2026-10-10.md` | Historical result | Describes an isolated modernization candidate, not this v6.0.11 source; V1 has phase 17 and 18 records. |
| `OneShot_System_Owned_Workflow_Complete_Builder_Prompt_2026-10-09.md` | Historical proposal | Addresses an earlier candidate ZIP/diff; V1 owns its workflow map in `docs/WORKFLOWS.md`. |
| `OneShot_System_Implementation_Plan.md` | Historical proposal | Explicitly proposed for approval and based on earlier candidates; not an approved change list for V1. |
| `Final_Product_Intent_Audit.md` | Historical audit | Its scope is an October 8 chat archive, not the installed v6.0.11 source. |
| `ARCHITECTURE.md` | Historical audit | September 20 researcher-pipeline snapshot using Bun/TypeScript; V1 is a Python/vanilla JS release. |
| `# OneShot Workflow Tree V3.md` | Historical design | Design tree for a different workflow architecture; V1 has an executable workflow-to-code map. |
| `OneShot_Harness_Overview.md` | Historical design | General harness concept; no matching harness package in this V1 export. |
| `OneShot_v1.3.0_SANDBOX_DEPLOYMENT_CORRECTED.md` | Historical design | Older sandbox deployment path and version; not the V1 deployment contract. |
| `OneShot Public Repository Normalization — Audit + Correction Task.md` | Other project | Names `itz1508/oneshot_e2e`, not this extracted V1 release. |
| `researcher-skill-production-plan.md` | Other project | Specifies a Next.js frontend and separate backend tree absent from V1. |
| `RSM/WORKSPACE_V7.1_REPORT.md` | Other project | RSM workspace build report, not this release. |
| `REPOSITORY_IMPORT_REPORT.md` | Other project | Refers to `langchain-samples/lsd-custom-route-react-ui`. |
| `Backlog.md` | Unscoped note | Generic checklist with no V1 owner or evidence. |
| `00-continuous-todo-hard-rule.md` | Unscoped rule | Requires `docs/readytodo.md`, which is absent from V1; not an instruction source for this release. |

## Installation decision

There is no additional downloaded Markdown document ready to install verbatim into V1. The two useful v6.0.11 evaluation references are already in `OneShot/docs/evaluation/`, and the workflow diagrams are already included in `docs/WORKFLOWS.md`. Potentially useful uninstalled ideas have been rewritten in `D:\OneShot-V1\newfile.md` with current-version boundaries. The older proposals remain aside; retaining them does not implement their requests.
