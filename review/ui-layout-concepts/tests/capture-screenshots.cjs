const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const { createFixtureServer } = require('./serve.cjs');

const gallery = path.resolve(__dirname, '..');
const output = path.resolve(process.env.CAPTURE_OUTPUT_DIR || gallery);
const desktop = { width: 1600, height: 900 };
const mobile = { width: 390, height: 844 };
const scenarios = [
  { name: '01-two-pane-system.png', viewport: desktop },
  { name: '02-two-pane-agent-active.png', viewport: desktop, agentActive: true },
  { name: '03-system-sources.png', viewport: desktop, sources: true },
  { name: '04-system-review.png', viewport: desktop, source: 'context' },
  { name: '05-system-process.png', viewport: desktop, process: true },
  { name: '06-result-coverage.png', viewport: desktop, coverage: true },
  { name: '07-mobile-system.png', viewport: mobile },
  { name: '08-mobile-agent.png', viewport: mobile, agentActive: true },
  { name: '09-mobile-review.png', viewport: mobile, source: 'context' },
  { name: '10-mobile-process.png', viewport: mobile, source: 'context', process: true },
];

async function main() {
  await fs.mkdir(output, { recursive: true });
  const server = createFixtureServer();
  let browser;
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        server.removeListener('error', reject);
        resolve();
      });
    });
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
    for (const scenario of scenarios) {
      const page = await browser.newPage({ viewport: scenario.viewport, deviceScaleFactor: 1 });
      try {
        await page.goto(baseURL, { waitUntil: 'load' });
        await page.evaluate(() => document.fonts.ready);
        if (scenario.agentActive) {
          await page.locator(scenario.viewport.width <= 900
            ? '[data-mobile-zone-choice="agent"]'
            : '#rail-agent-toggle').click();
        }
        if (scenario.sources || scenario.source) {
          await page.locator(scenario.viewport.width <= 900
            ? '#mobile-sources-toggle'
            : '#rail-sources-toggle').click();
          if (!await page.locator('#summary-panel').isVisible()) throw new Error(`${scenario.name}: sources not visible`);
        }
        if (scenario.source) {
          await page.locator(`[data-source="${scenario.source}"]`).click();
          if (!await page.locator('#detail-stage').isVisible()) throw new Error(`${scenario.name}: review not visible`);
        }
        if (scenario.process) {
          await page.locator('#process-toggle').click();
          if (!await page.locator('.process-view').isVisible()) throw new Error(`${scenario.name}: process not visible`);
        }
        if (scenario.coverage) await page.locator('[data-result-tab="coverage"]').click();
        await page.screenshot({ path: path.join(output, scenario.name), fullPage: true, animations: 'disabled' });
        process.stdout.write(`Captured ${scenario.name}\n`);
      } finally {
        await page.close();
      }
    }
  } finally {
    if (browser) await browser.close();
    if (server.listening) await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
