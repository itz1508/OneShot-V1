const { test, expect } = require('@playwright/test');
const path = require('node:path');
const { readFile } = require('node:fs/promises');
const { pathToFileURL } = require('node:url');

async function openSource(page, source = 'context') {
  if (!await page.locator('#summary-panel').isVisible()) {
    const trigger = page.viewportSize().width <= 900
      ? page.locator('#mobile-sources-toggle')
      : page.locator('#rail-sources-toggle');
    await trigger.click();
  }
  await page.locator(`[data-source="${source}"]`).click();
  await expect(page.locator('#preview')).toHaveAttribute('data-detail', 'review');
  await expect(page.locator('#detail-stage')).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('Agent ownership changes authority while both desktop panes remain present', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'system');
  await page.locator('#rail-sources-toggle').click();
  await expect(page.locator('.scope-box[value="context"]')).toBeEnabled();
  await page.locator('#rail-agent-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'agent');
  await expect(page.locator('.agent-card')).toBeVisible();
  await expect(page.locator('.system-card')).toBeVisible();
  await expect(page.locator('#system-access')).toContainText('Read-only');
  await expect(page.locator('.scope-box[value="context"]')).toBeDisabled();
  await page.locator('#rail-system-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'system');
  await expect(page.locator('.scope-box[value="context"]')).toBeEnabled();
  await expect(page.locator('.scope-box[value="image"]')).toBeDisabled();
  await expect(page.locator('.scope-box[value="url"]')).toBeDisabled();
});

test('source row toggles review; selecting another source switches it', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page, 'context');
  await expect(page.locator('[data-source="context"]')).toHaveAttribute('aria-expanded', 'true');
  await page.locator('[data-source="context"]').click();
  await expect(page.locator('#detail-stage')).toBeHidden();
  await expect(page.locator('[data-source="context"]')).toHaveAttribute('aria-expanded', 'false');
  await page.locator('[data-source="brief"]').click();
  await expect(page.locator('#source-name')).toHaveText('brief.md');
  await page.locator('[data-source="context"]').click();
  await expect(page.locator('#source-name')).toHaveText('context.txt');
});

test('unsaved source drafts survive review closing and owner changes', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page);
  await page.locator('#edit-tab').click();
  const draft = 'Unsaved review note for this source';
  await page.locator('#source-draft').fill(draft);
  await expect(page.locator('#revision-state')).toContainText('Unsaved');
  await page.locator('#detail-close').click();
  await expect(page.locator('#detail-stage')).toBeHidden();
  await openSource(page);
  await page.locator('#edit-tab').click();
  await expect(page.locator('#source-draft')).toHaveValue(draft);
  await page.locator('#rail-agent-toggle').click();
  await expect(page.locator('#edit-tab')).toBeDisabled();
  await expect(page.locator('#revision-state')).toContainText('Unsaved');
  await page.locator('#rail-system-toggle').click();
  await page.locator('#edit-tab').click();
  await expect(page.locator('#source-draft')).toHaveValue(draft);
});

test('source search filters inventory and close restores useful focus', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page);
  await page.locator('#source-search').fill('brief');
  await expect(page.locator('[data-source-row="context"]')).toBeHidden();
  await expect(page.locator('[data-source-row="brief"]')).toBeVisible();
  await page.locator('#detail-close').click();
  await expect(page.locator('#source-search')).toBeFocused();
  await page.locator('#source-search').fill('no match');
  await expect(page.locator('#source-empty')).toBeVisible();
  await page.locator('#source-search').fill('');
  await expect(page.locator('[data-source-row]')).toHaveCount(4);
});

test('review tabs support arrows and compare an immutable original with a draft', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page);
  const original = await page.locator('#source-content').textContent();
  await page.locator('#read-tab').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#edit-tab')).toBeFocused();
  await expect(page.locator('#edit-tab')).toHaveAttribute('aria-selected', 'true');
  const draft = `${original}\n\nReviewer note.`;
  await page.locator('#source-draft').fill(draft);
  await page.locator('#compare-changes').click();
  await expect(page.locator('#diff-tab')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#diff-original')).toHaveText(original);
  await expect(page.locator('#diff-current')).toHaveText(draft);
  await page.locator('#diff-tab').focus();
  await page.keyboard.press('Home');
  await expect(page.locator('#read-tab')).toBeFocused();
  await expect(page.locator('#source-content')).toHaveText(original);
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('#diff-tab')).toBeFocused();
});

test('visible Escape closes review and returns focus to its source', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page);
  await page.locator('#read-tab').focus();
  await page.keyboard.press('Escape');
  await expect(page.locator('#detail-stage')).toBeHidden();
  await expect(page.locator('[data-source="context"]')).toBeFocused();
});

test('review focus expands the System context without hiding Agent Chat', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page);
  await page.locator('#review-focus').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-review-focus', 'on');
  await expect(page.locator('.agent-card')).toBeVisible();
  await expect(page.locator('.system-card')).toBeVisible();
  await page.locator('#review-focus').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-review-focus', 'off');
});

test('processing uses System context while the scanner remains in the chat', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page, 'brief');
  await page.locator('#process-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-scan-stage', 'processing');
  await expect(page.locator('.process-view')).toBeVisible();
  await expect(page.locator('.review-view')).toBeHidden();
  await expect(page.locator('#scan-card')).toBeVisible();
  await expect(page.locator('#markdown-result')).toBeHidden();
  await expect(page.locator('.agent-card')).toBeVisible();
  for (const value of ['waiting', 'reconnecting', 'blocked', 'completed']) {
    await page.locator('#process-state').selectOption(value);
    await expect(page.locator('#process-event-list .is-empty')).toContainText(/No live event/i);
  }
  await page.locator('#process-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-detail', 'review');
  await expect(page.locator('#source-name')).toHaveText('brief.md');
  await expect(page.locator('#markdown-result')).toBeVisible();
});

test('compact processing keeps the System conversation visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSource(page);
  await page.locator('#process-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-mobile-zone', 'system');
  await expect(page.locator('.system-conversation #scan-card')).toBeVisible();
  await expect(page.locator('.process-view')).toBeVisible();
  await page.locator('#process-toggle').click();
  await expect(page.locator('#preview')).toHaveAttribute('data-detail', 'review');
});

test('compact Sources closes and reopens inside System with review restored', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSource(page, 'brief');
  await page.locator('#summary-close').click();
  await expect(page.locator('#summary-panel')).toBeHidden();
  await expect(page.locator('#preview')).toHaveAttribute('data-mobile-zone', 'system');
  await page.locator('#mobile-sources-toggle').click();
  await expect(page.locator('#summary-panel')).toBeVisible();
  await expect(page.locator('#source-name')).toHaveText('brief.md');
  await expect(page.locator('#detail-stage')).toBeVisible();
});

test('result tabs have keyboard behavior and associated focusable panels', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const preview = page.locator('[data-result-tab="preview"]');
  const sources = page.locator('[data-result-tab="sources"]');
  const coverage = page.locator('[data-result-tab="coverage"]');
  await preview.focus();
  await page.keyboard.press('ArrowRight');
  await expect(sources).toBeFocused();
  await expect(page.locator('#result-sources-panel')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(coverage).toBeFocused();
  await expect(page.locator('#result-coverage-panel')).toBeVisible();
  await expect(page.locator('#result-coverage-panel')).toHaveAttribute('tabindex', '0');
  await expect(page.locator('#result-coverage-panel')).toHaveAttribute('aria-labelledby', 'result-coverage-tab');
  await page.keyboard.press('Home');
  await expect(preview).toBeFocused();
  await expect(page.locator('#result-preview-panel')).toBeVisible();
});

test('URL restores contextual state, normalizes invalid values, and preserves history', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openSource(page, 'brief');
  await expect(page).toHaveURL(/source=brief/);
  await page.goBack();
  await expect(page.locator('#preview')).toHaveAttribute('data-detail', 'closed');
  await page.goForward();
  await expect(page.locator('#source-name')).toHaveText('brief.md');
  await page.reload();
  await expect(page.locator('#detail-stage')).toBeVisible();
  await page.goto('/?owner=bogus&right=closed&detail=review&zone=sources&scope=context,image,bogus&scan=bogus&result=bogus');
  await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'system');
  await expect(page.locator('#preview')).toHaveAttribute('data-right', 'closed');
  await expect(page.locator('#preview')).toHaveAttribute('data-detail', 'closed');
  await expect(page.locator('#preview')).toHaveAttribute('data-mobile-zone', 'system');
  await expect(page.locator('#scope-count')).toHaveText('1');
  await expect(page.locator('#preview')).toHaveAttribute('data-scan-stage', 'result');
});

test('sample actions stay local and Markdown download equals the preview', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const errors = [];
  const backendRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (/\/(api|auth)\//.test(new URL(request.url()).pathname)) backendRequests.push(request.url());
  });
  await expect(page.getByRole('button', { name: 'Start unavailable in layout study' })).toBeDisabled();
  await expect(page.locator('#composer-sample')).toHaveAttribute('readonly', '');
  const markdown = await page.locator('#result-markdown').textContent();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#sample-download').click(),
  ]);
  expect(download.suggestedFilename()).toBe('OneShot-Context.md');
  expect(await readFile(await download.path(), 'utf8')).toBe(markdown);
  expect(backendRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test('the gallery also works when opened directly as a local file', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(path.resolve(__dirname, '..', 'index.html')).href);
  await expect(page.locator('.agent-card')).toBeVisible();
  await expect(page.locator('.system-card')).toBeVisible();
  await openSource(page);
  await expect(page.locator('#detail-stage')).toBeVisible();
  expect(errors).toEqual([]);
});
