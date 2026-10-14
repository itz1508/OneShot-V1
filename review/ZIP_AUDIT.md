# OneShot ZIP cleanup and comparison

Reviewed 2026-10-12 (America/Los_Angeles). Scope: 48 ZIP files found under Downloads outside `C:\Users\itz15\Downloads\Toloka`. Toloka was not changed. `ZIP_INVENTORY.csv` records every archive's original path, SHA-256, member counts, Markdown overlap with V1, and `OneShot/` source overlap. `ZIP_MARKDOWN_INVENTORY.csv` records Markdown inside the 37 OneShot-named ZIPs, including nested ZIPs, with content hashes and titles. No archive was extracted into V1.

## Cleanup result

- Moved 37 OneShot-named ZIPs to `C:\Users\itz15\Downloads\_OneShot_ZIP_Aside`. Every moved archive's SHA-256 still matches the pre-move inventory.
- Left 11 other ZIPs in place. They have different or ambiguous names, including RSM, ChatAgents, Benchmark Console, researcher, and `v3.zip`; their contents were inventoried but not treated as V1 downloads.
- The aside area separates 8 older `OneShot/` source candidates, 23 distinct design/export archives, 5 standalone archives also present byte-for-byte inside another ZIP, and 1 exact duplicate ZIP.
- The exact duplicate is `OneShot_Production_E2E_v1.3.0 (1).zip`, matching `OneShot_Production_E2E_v1.3.0.zip`. Automatic approval review rejected direct binary deletion, and the text patch tool cannot read ZIP bytes, so the duplicate remains clearly labeled in the aside area. Storage was not reclaimed.

## What the ZIPs contain

- The 37 OneShot-named archives contain 297 direct Markdown members. Including nested ZIPs yields 392 Markdown instances representing 193 distinct byte sequences. Of those instances, 49 match installed V1 Markdown byte-for-byte, representing 7 distinct installed documents. A different hash alone does not prove a document is a current V1 requirement.
- No whole OneShot ZIP was proven byte-identical to the installed v6.0.11 source. Older `OneShot/` candidates contain both identical and changed paths; none was merged.
- `OneShot_Active_Scoped_Gap_Fix_NOT_VALID_2026-10-11.zip` has 17 files absent from V1, including deployment/workflow documents, scripts, fixtures, and tests. It is explicitly a `NOT_VALID` candidate. Its Apply path-scope test overlaps current `tests/test_apply_security.py`; do not import the candidate wholesale.
- `OneShot_Run_History_Candidate_2026-10-11.zip` has two test files absent from V1. The current V1 UI already has run-history search/status controls and `tests/e2e_improvement_loop.py` exercises history navigation. The candidate remains a reference for any later test-gap review.
- `OneShot_Single_Builder_Package_System_WinML_2026-10-10.zip` contains an exact copy of the standalone `OneShot_Active_Project_Integrated_Fixes_2026-10-10.zip`. The chat exports similarly embed exact copies of five standalone archives, including the October 8 chat archive, final intent audit, workspace source, and ready-to-build package. These are download-level redundancy, not proof that their designs were installed in V1.
- The remaining design/workflow, hackathon, frontend, IDE, researcher, and v1.3 archives describe other architectures or older milestones. Their Markdown is preserved for reference and was not promoted as current source authority.

## Installation decision

No ZIP or nested Markdown file was installed into `D:\OneShot-V1`. This audit establishes archive identity and overlap; it does not prove that every differing design was functionally superseded. The current V1 release source and its 174 original checksum entries remain the review baseline. Any specific candidate file proposed for promotion needs a separate path-level gap, compatibility review, and target-side verification.
