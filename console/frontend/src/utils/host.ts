/**
 * 机器身份 = base_url 的 hostname（spec §3：机器是从实例派生的，不是表）。
 * 与后端 instances_service.host_of 同口径；缺 scheme 的 host:port 也按 http 解析。
 */
export function hostOf(baseUrl: string): string {
  const url = baseUrl.includes('://') ? baseUrl : `http://${baseUrl}`
  try {
    return new URL(url).hostname
  } catch {
    return baseUrl
  }
}