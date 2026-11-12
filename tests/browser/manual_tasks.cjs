/** Real section-search acceptance against a generated local site. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs/promises');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
(async () => {
  const root = path.resolve(process.argv[2]);
  const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}: {})});
  try {
    for (const code of ['zh','en']) {
      const context = await browser.newContext({viewport:{width:1280,height:900}});
      await context.route(/^https?:/, route=>route.abort());
      const page = await context.newPage();
      const errors=[];page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(pathToFileURL(path.join(root,code,'index.html')).href);
      assert.equal(await page.locator('.task-route').count(),5);
      const input = page.locator('#landing-search');
      await input.fill(code==='zh'?'空气 ROI':'air ROI');
      const link=page.locator('.search-hit[href="qa-air.html#step-2"]');
      assert.ok(await link.isVisible());
      assert.ok((await link.locator('span').textContent()).length>20);
      await link.focus();await page.keyboard.press('Enter');
      await page.waitForURL('**/qa-air.html#step-2');
      const rect=await page.locator('#step-2').boundingBox();assert.ok(rect.y>=60 && rect.y<900);
      assert.ok(await page.locator('.chapter-context').count());
      await page.locator('#manual-search').fill('ROI');
      assert.equal(await page.locator('.search-hit').count(),30);
      assert.ok((await page.locator('.search-status').textContent()).length>0);
      await page.locator('#manual-search').fill('notfound-zzq');
      assert.equal(await page.locator('.search-hit').count(),0);
      assert.ok(await page.locator('.search-help').isVisible());
      await page.locator('#manual-search').fill('ctrl+s');
      assert.ok(await page.locator('.search-hit').count()>0);
      await page.locator('#manual-search').fill('');
      assert.ok(await page.locator('.nav-group').first().isVisible());
      assert.ok(await page.locator('#search-results').isHidden());
      await page.locator('.chapter-pagination a[rel="next"]').click();
      assert.notEqual(new URL(page.url()).pathname,path.join(root,code,'qa-air.html'));
      await page.locator('.site-nav-language').click();
      assert.equal(await page.locator('html').getAttribute('lang'),code==='zh'?'en-US':'zh-CN');
      assert.deepEqual(errors,[]);
      for (const width of [375,768,1280,1920]) {
        await page.setViewportSize({width,height:900});
        for (const chapter of ['point-mtf','ramp-fwhm','qa-water','qa-noise','qa-air','ai-setup','shortcuts']) {
          await page.goto(pathToFileURL(path.join(root,code,chapter+'.html')).href);
          assert.ok(await page.locator('h1').isVisible());
          assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1), `${code}/${chapter}/${width}: no page overflow`);
          if (chapter==='point-mtf') {
            const legend=await page.locator('.mtf-figure ul').boundingBox();
            assert.ok(legend.x>=0 && legend.x+legend.width<=width+1, 'MTF legend stays readable without horizontal scrolling');
          }
          if (chapter==='point-mtf' && process.argv[3]) {
            await fs.mkdir(process.argv[3],{recursive:true});
            await page.screenshot({path:path.join(process.argv[3],`${code}-mtf-${width}.png`)});
          }
        }
      }
      assert.deepEqual(errors,[]);
      await context.close();
    }
    console.log('Passed bilingual task routes, section search, keyboard navigation, limits, shortcuts, clearing, pagination and language switching.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
