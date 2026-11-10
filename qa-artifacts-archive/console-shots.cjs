const { chromium } = require('playwright');
const path = require('path');

const OUT = path.resolve(__dirname, 'console-preview-shots');
const VIEWS = ['params', 'sessions', 'versions', 'instances', 'audit', 'login'];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('http://127.0.0.1:8811/console-preview.html', { waitUntil: 'load' });
  await page.waitForTimeout(400);

  for (const v of VIEWS) {
    if (v !== 'params') {
      await page.click(`.nav[data-goto="${v}"]`);
      await page.waitForTimeout(250);
    }
    await page.screenshot({ path: path.join(OUT, `${v}.png`), fullPage: false });
    const geo = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      scrollH: document.documentElement.scrollHeight,
    }));
    console.log(v, JSON.stringify(geo));
  }

  // 窄屏兜底检查：不许出现横向滚动
  await page.click('#login-toggle'); // 从登录页切回参数页
  await page.waitForTimeout(200);
  for (const w of [1280, 1024, 900]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(200);
    const r = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    console.log('width=' + w, JSON.stringify(r), r.scrollW > r.clientW ? 'OVERFLOW' : 'ok');
  }

  console.log('pageerrors=' + errors.length, errors.join(' | '));
  await browser.close();
})();
