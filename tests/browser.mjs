import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
execFileSync(
  process.env.PYTHON || 'python3',
  [
    '-m',
    'robot_crash',
    'demo',
    '--encoding',
    'mcap',
    '--output',
    '.local/matrix.json',
    '--html',
    '.local/report.html',
    '--lang',
    'fr',
  ],
  { stdio: 'pipe' },
);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(pathToFileURL(resolve('.local/report.html')).href);
  for (const lang of ['fr', 'en', 'es']) {
    await page.locator(`[data-lang=${lang}]`).click();
    assert.equal(await page.locator('html').getAttribute('lang'), lang);
    assert.equal(await page.locator('#safe-count').textContent(), '4/4');
    assert.equal(await page.locator('#kill-count').textContent(), '8');
    assert.equal(await page.locator('#broken-count').textContent(), '3/4');
    await page.locator('[data-filter=safe]').click();
    assert.equal(await page.locator('.trial').count(), 4);
    assert.equal(await page.locator('.trial.invalid').count(), 0);
    await page.locator('[data-filter=metadata_first]').click();
    assert.equal(await page.locator('.trial.invalid').count(), 3);
    await page.locator('.trial summary').first().click();
    assert.match(await page.locator('.trial pre').first().textContent(), /SIGKILL/);
    const event = page.waitForEvent('download');
    await page.locator('#download').click();
    assert.equal((await event).suggestedFilename(), 'robot-crash-matrix.json');
    await page.locator('[data-filter=all]').click();
  }
  await page.locator('[data-lang=fr]').click();
  await page.screenshot({ path: '.local/preview-fr.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log(
    'FR/EN/ES: real MCAP crash report, protocol filters, evidence, export and mobile verified.',
  );
} finally {
  await browser.close();
}
