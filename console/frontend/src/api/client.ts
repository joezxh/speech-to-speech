import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'

import type { ApiErrorBody, Envelope, TokenBundle } from '@/types/api'
import { fallbackCode, translate } from '@/utils/error'
import { clearSession, readBundle, readToken, saveBundle } from '@/utils/storage'

/** Everything a component needs to know about a failed call. */
export class AppError extends Error {
  readonly code: string
  readonly requestId: string
  readonly detail: unknown[]

  constructor(code: string, message: string, requestId = '', detail: unknown[] = []) {
    super(message)
    this.name = 'AppError'
    this.code = code
    this.requestId = requestId
    this.detail = detail
  }
}

/** Same-origin relative base: the page never learns an upstream address (D1). */
export const client = axios.create({ baseURL: '/api/v1', timeout: 30_000 })

type Retriable = AxiosRequestConfig & { __retried?: boolean }

let inFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const bundle = readBundle()
  if (!bundle?.refreshToken) return null
  // Raw axios on purpose: going through `client` would re-enter this interceptor
  // on a 401 from `/auth/refresh` and recurse until the tab gives up.
  const response = await axios.post<Envelope<TokenBundle>>('/api/v1/auth/refresh', {
    refreshToken: bundle.refreshToken
  })
  const next = response.data.data
  saveBundle(next)
  return next.accessToken
}

/** One refresh attempt shared by every 401 that lands while it is running. */
function refreshOnce(): Promise<string | null> {
  if (inFlight === null) {
    inFlight = refreshAccessToken()
      .catch(() => null)
      .finally(() => {
        inFlight = null
      }) as Promise<string | null>
  }
  return inFlight
}

function redirectToLogin(): void {
  if (!window.location.pathname.startsWith('/console')) return
  const next = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/console/login?next=${next}`)
}

client.interceptors.request.use((config) => {
  const token = readToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

client.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const config = error.config as Retriable | undefined
    const status = error.response?.status
    // A 401 from `/auth/*` is a wrong password, not an expired session: trying to
    // refresh a login turns a typo into a redirect loop.
    const isAuthEndpoint = config?.url?.startsWith('/auth/') ?? false

    if (status === 401 && config && !config.__retried && !isAuthEndpoint) {
      const token = await refreshOnce()
      if (token) {
        config.__retried = true
        return client.request(config)
      }
      clearSession()
      redirectToLogin()
    }

    const body = error.response?.data
    const code = typeof body?.code === 'string' && body.code ? body.code : fallbackCode(status)
    return Promise.reject(
      new AppError(code, translate(code), body?.requestId ?? '', body?.detail ?? [])
    )
  }
)

/** Unwraps `{code,message,data}` so callers only ever see `data`. */
async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await client.request<Envelope<T>>(config)
  return response.data.data
}

export const api = {
  get: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'get' }),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'post', data: body }),
  delete: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'delete' })
}
