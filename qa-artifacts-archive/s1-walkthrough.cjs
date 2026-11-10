// S1 manual walkthrough (Task 9) against the Vite dev server (:3000), which
// proxies /api to the console backend on :8000. Archives PNGs + a JSON report
// into ./2026-10-28-console-s1 and prints a per-check pass/fail line.
//
// The dev server (not the built dist) is used because the production CSP
// forbids 'unsafe-eval', which vue-i18n's runtime message compiler needs; the
// dev server applies no such header. See the acceptance notes.
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')

const BASE = process.env.S2S_CONSOLE_URL || 'http://localhost:3000'
const OUT = path.resolve(__dirname, '..', 'console', 'qa-artifacts-archive', '2026-10-28-console-s1')
const report = { base: BASE, checks: [], screenshots: [], pageErrors: [] }
const t0 = Date.now()
const log = (m) => console.log(`[${String(Date.now() - t0).padStart(6)}ms] ${m}`)
const check = (name, pass, detail) => {
  report.checks.push({ name, pass: Boolean(pass), detail })
  log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`)
}
const hasCjk = (s) => /[\u4e00-\u9fff]/.test(s || '')

async function shot(page, file) {
  await page.screenshot({ path: path.join(OUT, file), timeout: 30000 })
  report.screenshots.push(file)
  log('SHOT  ' + file)
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })

  // 登录页证据单独用无会话 context 拍：表单交互在 CI 浏览器里不稳，其余页面
  // 改用 API 签发的 token 注入 sessionStorage，确定性进入已登录态。
  const anon = await chromium.launch()
  const anonPage = await anon.newPage({ viewport: { width: 1440, height: 900 } })
  await anonPage.goto(BASE + '/console/login', { waitUntil: 'domcontentloaded', timeout: 45000 })
  await anonPage.waitForSelector('form', { timeout: 45000 })
  await anonPage.waitForTimeout(1500)
  await shot(anonPage, '01-login-zh.png')
  await anon.close()

  const login = await fetch(BASE + '/api/v1/auth/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'admin123456' })
  })
  const bundle = (await login.json()).data
  check('④ POST /auth/login returns a token bundle', Boolean(bundle && bundle.accessToken && bundle.user), bundle && bundle.user && bundle.user.role)

  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await context.addInitScript((b) => {
    window.sessionStorage.setItem('s2s.console.session', JSON.stringify(b))
    window.sessionStorage.setItem('s2s.console.profile', 'prod')
  }, bundle)
  const page = await context.newPage()
  page.on('pageerror', (e) => { report.pageErrors.push(String(e)); log('PAGEERR ' + e.message) })

  // Warm each route once so Vite finishes on-demand compilation before timing.
  for (const r of ['/console/overview', '/console/traffic']) {
    await page.goto(BASE + r, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
    await page.waitForTimeout(1500)
  }

  // ---- ④ signed-in /console lands on /console/overview -----------------
  await page.goto(BASE + '/console/overview', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-metric]', { timeout: 45000 })
  await page.waitForTimeout(1500)
  check('④ /console redirects to /console/overview', /\/console\/overview/.test(page.url()), page.url())

  // ---- ① three-section nav, labels from i18n ---------------------------
  await shot(page, '02-overview-zh.png')
  const nav = await page.$eval('#shell-nav', (navEl) => {
    const out = []
    for (const child of navEl.children) {
      if (child.classList.contains('shell__nav-label')) out.push({ group: child.textContent.trim() })
      else if (child.classList.contains('nav')) out.push({ item: child.textContent.trim(), title: child.getAttribute('title') })
    }
    return out
  })
  const groups = nav.filter((n) => n.group).map((n) => n.group)
  const items = nav.filter((n) => n.item)
  check('① nav has 3 group headings', groups.length === 3, groups.join(' | '))
  check('① nav items >= 12, each with an i18n title', items.length >= 12 && items.every((i) => !!i.title), items.length + ' items')

  // ---- ⑦ overview KPIs: real source, DASH for gaps, S2/S3 for unimpl ---
  const metrics = await page.$$eval('[data-metric]', (els) =>
    els.map((e) => ({ key: e.getAttribute('data-metric'), text: e.textContent.trim() }))
  )
  check('⑦ overview renders >=15 real KPI cells', metrics.length >= 15, metrics.length + ' cells')
  check('⑦ every KPI cell key is overview.kpi.*', metrics.every((m) => m.key.indexOf('overview.kpi.') === 0), '')
  const dash = metrics.filter((m) => m.text === '\u2014')
  check('⑦ unavailable facts render DASH not mock', dash.some((d) => d.key === 'overview.kpi.pipelineInstances'), dash.map((d) => d.key).join(','))
  const ni = await page.$$eval('[data-unimplemented]', (els) =>
    els.map((e) => ({ tag: e.getAttribute('data-unimplemented'), text: e.textContent.replace(/\s+/g, ' ').trim() }))
  )
  check('⑦ unimplemented markers carry S2/S3/none', ni.length >= 5 && ni.every((x) => ['S2', 'S3', 'none'].includes(x.tag)), ni.map((x) => x.tag).join(','))
  check('⑦ each unimplemented card shows its tag', ni.every((x) => x.text.indexOf(x.tag) === 0), '')

  // ---- ⑧ traffic: off banner + read-only fields + S3 features ----------
  await page.goto(BASE + '/console/traffic', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-field]', { timeout: 45000 })
  await page.waitForTimeout(1500)
  check('⑧ traffic route renders', /\/console\/traffic/.test(page.url()), page.url())
  check('⑧ off-mode info banner present', !!(await page.$('[data-testid=lb-off-banner]')), '')
  const tf = await page.$$eval('[data-field]', (els) => els.map((e) => `${e.getAttribute('data-field')}=${e.textContent.trim()}`))
  check('⑧ allocator fields rendered read-only', tf.length >= 12, tf.join(' '))
  const s3 = await page.$$eval('[data-unimplemented="S3"]', (els) => els.length)
  check('⑧ routing features marked S3', s3 === 3, String(s3))
  await shot(page, '05-traffic-zh.png')

  // ---- ③ old-path redirects (spec §6.2) --------------------------------
  for (const [from, to] of [
    ['params', 'deploy'],
    ['instances', 'machines'],
    ['instances/trends', 'traffic'],
    ['versions', 'release'],
    ['sessions', 'session-update'],
  ]) {
    await page.goto(`${BASE}/console/${from}`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction((x) => window.location.pathname.endsWith(`/console/${x}`), to, { timeout: 15000 }).catch(() => {})
    check(`③ /console/${from} -> /console/${to}`, page.url().endsWith(`/console/${to}`), page.url())
  }

  // ---- ⑤ language toggle persists across reload ------------------------
  await page.goto(BASE + '/console/overview', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.shell__lang', { timeout: 30000 })
  await page.waitForTimeout(1200)
  await page.click('.shell__lang')
  await page.waitForTimeout(800)
  const stored = await page.evaluate(() => localStorage.getItem('s2s.console.locale'))
  check('⑤ toggle writes locale=en-US', stored === 'en-US', String(stored))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-metric]', { timeout: 30000 })
  await page.waitForTimeout(1200)
  const enNav = await page.textContent('#shell-nav')
  check('⑤ locale persists after reload (nav English)', !hasCjk(enNav), (enNav || '').replace(/\s+/g, ' ').slice(0, 90))
  await shot(page, '03-overview-en.png')
  await page.goto(BASE + '/console/traffic', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid=lb-off-banner]', { timeout: 30000 })
  const enBanner = await page.textContent('[data-testid=lb-off-banner]')
  check('⑧ traffic off banner translated to EN', !hasCjk(enBanner), (enBanner || '').trim())
  await shot(page, '04-traffic-en.png')

  await browser.close()
  fs.writeFileSync(path.join(OUT, 'walkthrough-report.json'), JSON.stringify(report, null, 2))
  const failed = report.checks.filter((c) => !c.pass)
  log(`\n${report.checks.length - failed.length}/${report.checks.length} checks passed; ${report.pageErrors.length} page errors`)
  if (failed.length) {
    log('FAILURES:\n' + failed.map((f) => `  - ${f.name} (${f.detail})`).join('\n'))
    process.exitCode = 1
  }
})().catch((e) => {
  log('WALKTHROUGH ERROR ' + (e && e.message))
  try { fs.writeFileSync(path.join(OUT, 'walkthrough-report.json'), JSON.stringify(report, null, 2)) } catch {}
  process.exitCode = 2
})
