/** Built-site browser acceptance; no server or external network required.
 * npm --prefix tests/browser install --ignore-scripts
 * node tests/browser/manual_layout.cjs SITE_ROOT [EVIDENCE_DIRECTORY]
 * PLAYWRIGHT_CHROMIUM_EXECUTABLE may select an already installed browser.
 * MANUAL_LAYOUT_MUTANT=stretch|overflow injects a process-local negative control.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

const site = path.resolve(process.argv[2] || '/tmp/voxplane-manual-site');
const evidence = path.resolve(process.argv[3] || '/tmp/voxplane-manual-browser-evidence');
const widths = [375, 768, 1280, 1920];
const results = [];

async function loadedImages(page) {
  await page.locator('img').evaluateAll(images => images.forEach(image => image.loading = 'eager'));
  await page.waitForFunction(() => [...document.images].every(image => image.complete), null, {timeout: 15000});
  const broken = await page.locator('img').evaluateAll(images => images.filter(image => !image.naturalWidth).map(image => image.currentSrc || image.src));
  assert.deepEqual(broken, [], 'Every local image must decode successfully');
}

async function layout(page, label) {
  await loadedImages(page);
  assert.ok(await page.locator('main h1').isVisible(), `${label}: meaningful page heading`);
  const faults = await page.evaluate(() => {
    const issues = [];
    if (document.documentElement.scrollWidth > innerWidth + 1)
      issues.push(`horizontal overflow: ${document.documentElement.scrollWidth} > ${innerWidth}`);
    for (const image of document.images) {
      const rect = image.getBoundingClientRect();
      const style = getComputedStyle(image);
      if (!rect.width || !rect.height || style.visibility === 'hidden') continue;
      // Icons have independent square presentation. Large screenshots must
      // preserve their natural ratio, either in the box or via object-fit.
      if (image.naturalWidth < 200 || image.naturalHeight < 100) continue;
      const width = rect.width - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth) - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const height = rect.height - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      const ratioError = Math.abs(width / height / (image.naturalWidth / image.naturalHeight) - 1);
      if (ratioError > .015 && !['contain', 'scale-down'].includes(style.objectFit))
        issues.push(`stretched/cropped screenshot: ${image.src}, ratio error ${ratioError}, object-fit ${style.objectFit}`);
      for (let parent = image.parentElement; parent; parent = parent.parentElement) {
        const parentStyle = getComputedStyle(parent);
        const bounds = parent.getBoundingClientRect();
        if (['hidden', 'clip'].includes(parentStyle.overflowX) && (rect.left < bounds.left - 2 || rect.right > bounds.right + 2))
          issues.push(`horizontally clipped screenshot: ${image.src}`);
        if (['hidden', 'clip'].includes(parentStyle.overflowY) && (rect.top < bounds.top - 2 || rect.bottom > bounds.bottom + 2))
          issues.push(`vertically clipped screenshot: ${image.src}`);
      }
    }
    return issues;
  });
  assert.deepEqual(faults, [], `${label}: rendered layout`);
  await page.screenshot({path: path.join(evidence, `${label}.png`)});
  results.push({page: label, status: 'pass'});
}

async function search(page, selector, target) {
  const input = page.locator(selector);
  const links = page.locator('a[data-search]');
  const count = await links.count();
  assert.ok(count > 1, 'Search needs multiple chapters');
  const link = links.filter({hasText: target});
  assert.equal(await link.count(), 1, 'Expected chapter must exist');
  await input.fill(target);
  assert.ok(await page.locator('.search-hit').filter({hasText: target}).count() > 0, 'Matching steps are shown');
  assert.ok(await links.locator('visible=true').count() < count, 'Search filters other chapters');
  await input.fill('no-chapter-7d3b88a9');
  assert.equal(await links.locator('visible=true').count(), 0, 'Unmatched search hides every chapter');
  assert.ok(await page.locator('#search-results .search-help').isVisible(), 'Empty search result is shown');
  await input.fill('');
  assert.equal(await links.locator('visible=true').count(), count, 'Clearing restores chapters');
}

(async () => {
  await fs.mkdir(evidence, {recursive: true});
  const browser = await chromium.launch({headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
  const inputs = {};
  for (const name of ['index.html', 'en-us/index.html', 'zh/index.html', 'en/index.html', 'zh/local-import.html', 'en/local-import.html', 'assets/manual.css', 'assets/manual.js', 'assets/product.css', 'assets/site-shell.css'])
    inputs[name] = createHash('sha256').update(await fs.readFile(path.join(site, name))).digest('hex');
  await fs.writeFile(path.join(evidence, 'environment.json'), JSON.stringify({browser: browser.version(), playwright: require('playwright/package.json').version, widths, inputs}, null, 2));
  try {
    for (const language of ['zh', 'en']) for (const width of widths) {
      const context = await browser.newContext({viewport: {width, height: 1000}, reducedMotion: 'reduce'});
      await context.route(/^https?:/, route => route.abort());
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      const product = language === 'zh' ? 'index.html' : 'en-us/index.html';
      await page.goto(pathToFileURL(path.join(site, product)).href);
      assert.ok((await page.title()).includes('VoxPlane'));
      if (process.env.MANUAL_LAYOUT_MUTANT === 'stretch')
        await page.addStyleTag({content: '.hero-visual img { height: 37px !important; object-fit: fill !important; }'});
      if (process.env.MANUAL_LAYOUT_MUTANT === 'overflow')
        await page.addStyleTag({content: 'body { min-width: 3000px !important; }'});
      await layout(page, `${language}-product-${width}`);
      const manualHref = language === 'zh' ? 'zh/index.html' : '../en/index.html';
      await page.locator(`a[href="${manualHref}"]`).first().click();
      assert.equal(new URL(page.url()).pathname, path.join(site, language, 'index.html'));
      await layout(page, `${language}-manual-${width}`);
      const chapter = page.locator('a[data-search][href="local-import.html"]');
      const title = (await chapter.innerText()).trim();
      await search(page, '#landing-search', title);
      await chapter.click();
      assert.equal(new URL(page.url()).pathname, path.join(site, language, 'local-import.html'));
      assert.equal((await page.locator('main h1').innerText()).trim(), title);
      await layout(page, `${language}-chapter-${width}`);
      const menu = page.locator('.menu-toggle');
      if (await menu.isVisible()) {
        await menu.click();
        assert.equal(await menu.getAttribute('aria-expanded'), 'true');
        assert.ok(await page.locator('#manual-search').isVisible());
      }
      await search(page, '#manual-search', title);
      if (await menu.isVisible()) {
        await page.keyboard.press('Escape');
        assert.equal(await menu.getAttribute('aria-expanded'), 'false');
      }
      const demo = page.locator('.tutorial').first();
      assert.ok(await demo.count(), 'Representative chapter must include a tutorial');
      await demo.scrollIntoViewIfNeeded();
      const button = demo.locator('button');
      const image = demo.locator('img');
      const still = await image.getAttribute('data-still');
      const animation = await image.getAttribute('data-animation');
      assert.equal(await image.getAttribute('src'), still);
      await button.click();
      await page.waitForFunction(() => {
        const image = document.querySelector('.tutorial img');
        return image.complete && image.naturalWidth > 0 && image.getAttribute('src') === image.dataset.animation;
      });
      assert.equal(await image.getAttribute('src'), animation);
      assert.equal(await button.getAttribute('aria-pressed'), 'true');
      await button.click();
      assert.equal(await image.getAttribute('src'), still);
      assert.equal(await button.getAttribute('aria-pressed'), 'false');
      assert.deepEqual(errors, [], 'No JavaScript or resource console errors');
      results.push({page: `${language}-interactions-${width}`, status: 'pass', checks: ['search', 'chapter navigation', 'tutorial play/stop']});
      await context.close();
    }
  } finally {
    await browser.close();
    await fs.writeFile(path.join(evidence, 'results.json'), JSON.stringify(results, null, 2));
  }
  console.log(`Passed ${results.length} layout/interaction checks across 2 languages and ${widths.length} widths.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
