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
}
