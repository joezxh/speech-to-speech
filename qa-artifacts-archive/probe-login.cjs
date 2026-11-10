const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://127.0.0.1:8811/console-preview.html');
  await page.click('.nav[data-goto="login"]');
  await page.waitForTimeout(300);
  const probe = await page.evaluate(() => {
    const out = [];
    for (const y of [880, 887, 890]) {
      const el = document.elementFromPoint(820, y);
      out.push({ y, tag: el && el.tagName, cls: el && el.className, rect: el && JSON.stringify(el.getBoundingClientRect()) });
    }
    const login = document.querySelector('.login').getBoundingClientRect();
    return { out, login: JSON.stringify(login) };
  });
  console.log(JSON.stringify(probe, null, 1));
  await browser.close();
})();
