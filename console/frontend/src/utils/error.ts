/**
 * Machine code → human sentence. The backend sends `code` for exactly this
 * purpose (A.0): `message` is English, may quote an input value, and is not
 * something the UI is allowed to render.
 */
export const ERROR_TEXT: Record<string, string> = {
  // auth
  unauthorized: '登录已过期，请重新登录',
  invalid_credentials: '用户名或密码不正确',
  invalid_refresh_token: '登录已失效，请重新登录',
  too_many_attempts: '失败次数过多，请稍后再试',
  forbidden: '当前角色无权执行该操作',
  // write path
  invalid_parameter: '参数不合法',
  version_conflict: '配置已被他人修改，请刷新后重试',
  validation_failed: '参数校验未通过',
  vram_budget_exceeded: '显存预算不足，请减少 pipeline 数量或换更小的模型',
  publish_in_progress: '已有一次发布正在进行',
  render_failed: '生成配置文件失败',
  restart_unavailable: '无法重启 pipeline 进程',
  healthcheck_timeout: '重启后健康检查超时，已回滚',
  pipeline_token_missing: 'pipeline 缺少内部令牌',
  pipeline_unavailable: 'pipeline 进程不可达',
  internal_token_missing: '控制台未配置内部令牌',
  env_requires_recreate: '该字段需要重建容器才能生效，请在部署窗口处理',
  rollback_failed: '自动回滚也失败了，请人工介入',
  // read path
  pool_unreachable: '无法连接 pipeline 池',
  catalog_unavailable: '参数目录不可用',
  db_unavailable: '数据库不可用',
  unknown_profile: '未知的 profile',
  unknown_version: '未知的版本',
  version_not_rollbackable: '该版本不可回滚',
  no_draft: '没有草稿',
  unsupported_field: '该字段不支持热更新',
  asset_missing: '静态资源缺失',
  not_implemented: '功能尚未启用',
  // voices (§3.11 / A.18)
  voice_not_found: '音色不存在',
  voice_name_taken: '音色名已被占用（不区分大小写）',
  voice_audio_invalid: '参考音频不合格：需要 16 kHz 单声道 PCM16、1–30 秒',
  voice_too_large: '音频超过 10 MiB 上限',
  voice_consent_required: '上传音色前需勾选生物特征授权',
  voice_in_use: '音色正被配置引用，无法删除',
  voice_expired: '音频已按留存期限自动删除',
  voice_precompute_failed: '预计算失败',
  voice_precompute_busy: '已有一次预计算在进行',
  voice_binding_conflict: '音色字段互相冲突：ref_audio 与 ref_spk 只能选一套',
  // ours, never sent by the backend
  network_error: '网络不可达，请检查连接',
  timeout: '请求超时',
  not_found: '接口或资源不存在',
  unknown: '未知错误'
}

/**
 * `/instances` 的 `alerts` 也是机器码（A.10）。与 `ERROR_TEXT` 分开，因为一个是
 * 「你的操作失败了」，一个是「系统现状不佳」——语气和位置都不同。
 */
export const ALERT_TEXT: Record<string, string> = {
  pool_unreachable: '无法连接 pipeline 池',
  pool_stuck: '有 unit 卡在 stuck，需要重启 pipeline',
  pipeline_stopped: 'pipeline 进程未运行',
  usage_unavailable: '用量数据不可读'
}

/** 未知码原样返回：宁可让运维看到一个英文码，也不要让一条告警消失。 */
export function describeAlert(code: string): string {
  return ALERT_TEXT[code] ?? code
}

export const FALLBACK_TEXT = '操作失败，请查看审计记录'

export function translate(code: string): string {
  return ERROR_TEXT[code] ?? FALLBACK_TEXT
}

/**
 * A body-less failure (proxy error page, connection reset) still has to become
 * something the user can read, so the status code is turned into one of our own
 * codes. These three plus `unknown` are the only codes the frontend invents.
 */
export function fallbackCode(status?: number): string {
  switch (status) {
    case 403:
      return 'forbidden'
    case 404:
      return 'not_found'
    case 409:
      return 'version_conflict'
    case 429:
      return 'too_many_attempts'
    case 503:
      return 'db_unavailable'
    default:
      return 'network_error'
  }
}
