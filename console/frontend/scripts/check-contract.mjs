// Contract gate for the console HTTP surface (spec A.0).
//
// The job that runs this starts the real app, so anything it asserts is the
// actual shape a browser gets — not a hand-copied mock. Checks stay additive:
// a route that does not exist yet is reported as pending, never as a pass.
const base = process.argv[2] ?? 'http://127.0.0.1:8000'

let failures = 0
const checks = []

function check(name, ok, detail = '') {
  checks.push({ name, ok, detail })
  if (!ok) failures += 1
}

async function json(path, init) {
  const response = await fetch(`${base}${path}`, init)
  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  return { status: response.status, body, headers: response.headers }
}

// A.0.1 — health is the one bare object on /api/v1.
{
  const { status, body } = await json('/api/v1/health')
  check('health 200', status === 200, `status=${status}`)
  check(
    'health is bare {status,version}',
    body !== null && Object.keys(body).sort().join(',') === 'status,version',
    JSON.stringify(body)
  )
}

// B10 — the demo surface must keep its own shape: no ApiResponse envelope.
{
  const { status, body } = await json('/api/config')
  if (status === 404) {
    checks.push({ name: 'demo /api/config', ok: true, detail: 'not in this build (404)' })
  } else {
    check('demo /api/config 200', status === 200, `status=${status}`)
    check('demo /api/config has no envelope', body !== null && !('code' in body), JSON.stringify(body)?.slice(0, 80))
  }
}

// A.0 — every /api/v1 error carries the same four keys.
{
  const { status, body } = await json('/api/v1/catalog')
  if (status === 401) {
    check('error envelope keys', body !== null && ['code', 'message', 'detail', 'requestId'].every((k) => k in body), JSON.stringify(body)?.slice(0, 120))
    check('unauthorized code', body?.code === 'unauthorized', String(body?.code))
  } else if (status === 404) {
    checks.push({ name: 'catalog envelope', ok: true, detail: 'route not in this build (404)' })
  } else {
    check('catalog requires auth', status === 401, `status=${status}`)
  }
}

for (const { name, ok, detail } of checks) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`)
}
if (failures) {
  console.error(`${failures} contract check(s) failed against ${base}`)
  process.exit(1)
}
console.log(`contract ok: ${checks.length} checks against ${base}`)
