# OneShot two-pane layout review

Open `index.html` in a browser. This is one proposed, interactive layout for review, not the installed OneShot UI. It uses sample data, makes no backend requests, and does not change `D:/OneShot-V1/OneShot`.

## Layout decision

The desktop shell has four tracks in this order: **left rail | Agent Chat | System Chat | right rail**. Agent and System are the only primary panes. The left rail selects which conversation owns the preview session; it does not remove either pane. The right rail opens System-owned context, such as Sources or result Coverage. On narrow screens the two conversations become Agent and System views; Sources remains a control inside System.

System Chat keeps the prompt, attachment chips, scanner processing card, and one illustrative Markdown result in the conversation. Its composer is inside the same pane. Sources, scope, Editor / Review, and Process Display use a contextual surface inside System Chat. Selecting a source opens its review; selecting the same source again closes it. Sample drafts survive closing and reopening the review during the page session. No product file is edited.

The five scanner labels and the `OneShot-Context.md` preview are design examples. No sources were read, no model ran, and no semantic verification occurred. The sample Markdown download contains the text visible in the result card. Send, Import / Send, and Start remain unavailable without a connected System backend. Agent conversation content is also illustrative. Source readiness and authority cues are mock state, not server-enforced access control.

The supplied diagrams, screenshots, discussion notes, `D:/OneShot/ui/output`, Mobbin examples, and [Crawlscan](https://github.com/0xPunisher/crawlscan) informed the review. They were compared and synthesized; the page does not reproduce any one reference. [GAP_REVIEW.md](GAP_REVIEW.md) records the market-practice comparison, design decisions, and verification limits.

## Run the layout fixture

From this folder:

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
```

The fixture starts and stops a local gallery server. It exercises the sample UI only and makes no product API requests. Failures retain screenshots and traces under `.artifacts/test-results`; `PLAYWRIGHT_OUTPUT_DIR` redirects them. Set `PLAYWRIGHT_CHANNEL=msedge` to use an installed Edge browser instead of Playwright Chromium. Refresh review captures with `npm run capture:screenshots`; `CAPTURE_OUTPUT_DIR` can stage them for inspection before replacing gallery images.

## Product boundary

This gallery does not establish a production architecture or demonstrate backend readiness. A future React UI can project FastAPI-owned jobs over HTTP and an event stream while keeping UI selection state local. A Next.js server layer is an independent deployment decision, not a requirement created by this layout. Real source eligibility, durable drafts, revision conflicts, progress, coverage, and result claims need product contracts and connected verification.
