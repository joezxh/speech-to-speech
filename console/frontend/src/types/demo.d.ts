export interface IceServer {
  urls: string
  username?: string
  credential?: string
}

/** A.13 — `GET /api/config`, bare object, no token. */
export interface DemoConfig {
  search: boolean
  lb: boolean
  allowDirect: boolean
  s2sUrl: string
  rtc: boolean
  iceServers: IceServer[]
  startupGreeting: string
  auth: boolean
  /**
   * 会话归档闸门：服务端不点头时，浏览器的勾选只是摆设。两个 `maxAudio*` 是
   * 单轮音频的硬上限（超了后端 413）。
   */
  sessionRecord: {
    enabled: boolean
    retentionDays: number
    retentionMaxDays: number
    maxAudioBytes: number
    maxAudioSeconds: number
  }
  /** 这一次部署实际连的 pipeline；静态值，不在这个接口里做健康检查。 */
  pipeline: { baseUrl: string; container: string }
}
