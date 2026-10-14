const { test, expect } = require('@playwright/test');

const desktopWidths = [1600, 1024];
const compactWidths = [900, 768, 390, 320];

async function openSources(page) {
  const trigger = page.viewportSize().width <= 900
    ? page.locator('#mobile-sources-toggle')
    : page.locator('#rail-sources-toggle');
  await trigger.click();
  await expect(page.locator('#summary-panel')).toBeVisible();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
}

async function openSource(page, source = 'context') {
  if (!await page.locator('#summary-panel').isVisible()) await openSources(page);
  await page.locator(`[data-source="${source}"]`).click();
  await expect(page.locator('#detail-stage')).toBeVisible();
}

async function expectInsideSystem(page, selector) {
  await expect(page.locator(`.system-card ${selector}`)).toHaveCount(1);
  await expect.poll(() => page.evaluate(childSelector => {
    const parent = document.querySelector('.system-card').getBoundingClientRect();
    const child = document.querySelector(`.system-card ${childSelector}`).getBoundingClientRect();
    return child.left >= parent.left - 1 && child.right <= parent.right + 1;
  }, selector)).toBe(true);
}

async function expectNoHorizontalOverflow(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

for (const width of desktopWidths) {
  test(`${width}px: outer rails frame two persistent chat panes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'system');
    await expect(page.locator('#preview')).toHaveAttribute('data-right', 'closed');
    await expect(page.locator('.agent-card')).toBeVisible();
    await expect(page.locator('.system-card')).toBeVisible();
    await expect(page.locator('.conversation-rail')).toBeVisible();
    await expect(page.locator('.context-rail')).toBeVisible();
    await expect(page.locator('#summary-panel')).toBeHidden();
    await expect(page.locator('.app-shell > *')).toHaveCount(4);

    const boxes = await page.evaluate(() => {
      const selectors = ['.conversation-rail', '.agent-card', '.system-card', '.context-rail'];
      return selectors.map(selector => {
        const { left, right } = document.querySelector(selector).getBoundingClientRect();
        return { left, right };
      });
    });
    for (let index = 0; index < boxes.length - 1; index++) {
      expect(boxes[index].right).toBeLessThanOrEqual(boxes[index + 1].left + 2);
    }
    await expectNoHorizontalOverflow(page);

    await page.locator('#rail-agent-toggle').click();
    await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'agent');
    await expect(page.locator('.agent-card')).toBeVisible();
    await expect(page.locator('.system-card')).toBeVisible();
    await page.locator('#rail-system-toggle').click();
    await expect(page.locator('#preview')).toHaveAttribute('data-owner', 'system');
    await expect(page.locator('.agent-card')).toBeVisible();
  });
}

test('Sources, Editor / Review, and Process Display stay inside System Chat', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  for (const selector of ['.system-conversation', '#scan-card', '#markdown-result', '.system-composer', '#summary-panel', '.attachments', '#detail-stage', '.process-view']) {
    await expect(page.locator(`.system-card ${selector}`)).toHaveCount(1);
  }
  const originalShell = await page.locator('.app-shell').boundingBox();
  await openSources(page);
  await expectInsideSystem(page, '#summary-panel');
  await expect(page.locator('.system-conversation')).toBeVisible();
  await openSource(page);
  await expectInsideSystem(page, '#detail-stage');
  await expect(page.locator('.agent-card')).toBeVisible();
  await expect(page.locator('.app-shell > *')).toHaveCount(4);
  const openShell = await page.locator('.app-shell').boundingBox();
  expect(openShell.width).toBe(originalShell.width);
  await expectNoHorizontalOverflow(page);
});

test('chat keeps one collapsible processing card and one Markdown result', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await expect(page.locator('.system-conversation #scan-card')).toHaveCount(1);
  await expect(page.locator('.system-conversation #markdown-result')).toHaveCount(1);
  await expect(page.locator('#result-markdown')).toContainText('#');
  await expect(page.locator('#markdown-result')).toContainText(/illustrative|sample/i);
  const card = page.locator('details#scan-card');
  const wasOpen = await card.evaluate(element => element.open);
  await card.locator('summary').click();
  await expect(card).toHaveJSProperty('open', !wasOpen);
  await expect(page.locator('.system-composer')).toBeVisible();
});

test('right rail opens a contextual drawer and can show coverage in chat', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const toggle = page.locator('#rail-sources-toggle');
  await expect(toggle).toHaveAccessibleName(/.+/);
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await openSources(page);
  await toggle.click();
  await expect(page.locator('#summary-panel')).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await page.locator('#rail-coverage-open').click();
  await expect(page.locator('[data-result-tab="coverage"]')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#result-coverage-panel')).toBeVisible();
  await expect(page.locator('.system-conversation')).toBeVisible();
});

for (const width of compactWidths) {
  test(`${width}px: Agent and System are the only responsive views`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const choices = page.locator('[data-mobile-zone-choice]');
    await expect(choices).toHaveCount(2);
    await expect(page.locator('.system-card')).toBeVisible();
    await expect(page.locator('.agent-card')).toBeHidden();
    await expect(page.locator('#markdown-result')).toBeVisible();
    await page.locator('[data-mobile-zone-choice="agent"]').click();
    await expect(page.locator('.agent-card')).toBeVisible();
    await expect(page.locator('.system-card')).toBeHidden();
    await page.locator('[data-mobile-zone-choice="system"]').click();
    await expect(page.locator('.system-card')).toBeVisible();
    await openSources(page);
    await expectInsideSystem(page, '#summary-panel');
    await expect(page.locator('#preview')).toHaveAttribute('data-mobile-zone', 'system');
    await expectNoHorizontalOverflow(page);
  });
}

test('320px review reflows long content and respects reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 320, height: 800 });
  await openSource(page);
  await expect(page.locator('#review-heading')).toBeFocused();
  await page.locator('#source-name').evaluate(element => {
    element.textContent = 'long-review-filename-without-breaks-'.repeat(15) + '.txt';
  });
  await expectNoHorizontalOverflow(page);
  await page.locator('#edit-tab').click();
  await page.locator('#source-draft').fill('x'.repeat(800));
  await expectNoHorizontalOverflow(page);
  const duration = await page.locator('#detail-stage').evaluate(element => getComputedStyle(element).animationDuration);
  expect(parseFloat(duration)).toBeLessThan(0.001);
});

test('rail controls expose names and disabled destinations remain inert', async ({ page }) => {
  for (const selector of ['#rail-agent-toggle', '#rail-system-toggle', '#rail-sources-toggle', '#rail-coverage-open']) {
    await expect(page.locator(selector)).toHaveAccessibleName(/.+/);
    await expect(page.locator(selector)).toBeEnabled();
  }
  const unavailable = page.locator('.conversation-rail button:disabled, .context-rail button:disabled');
  expect(await unavailable.count()).toBeGreaterThan(0);
  const enabledUnknown = page.locator('.conversation-rail button:not(#rail-agent-toggle):not(#rail-system-toggle):not(:disabled), .context-rail button:not(#rail-sources-toggle):not(#rail-coverage-open):not(:disabled)');
  await expect(enabledUnknown).toHaveCount(0);
});
