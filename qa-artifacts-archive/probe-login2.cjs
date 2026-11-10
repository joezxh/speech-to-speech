const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 3 });
  await page.goto('http://127.0.0.1:8811/console-preview.html');
  await page.click('.nav[data-goto="login"]');
  await page.waitForTimeout(300);
  await page.screenshot({
    path: path.resolve(__dirname, 'console-preview-shots', 'login-bottom-zoom.png'),
    clip: { x: 600, y: 840, width: 440, height: 60 },
  });
  await browser.close();
})();
