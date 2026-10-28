import type { TrafficSettings } from '@/types/traffic'

export interface TrafficFeature {
  feature: string
  reasonKey: string
}

/** Backend token → the `traffic.unimpl.*` leaf that documents who owns it. */
const FEATURE_KEYS: Record<string, string> = {
  'session-stickiness': 'stickiness',
  'canary-ratio': 'canary',
  'routing-rules': 'routing'
}

export function trafficViewModel(settings: TrafficSettings): {
  showOffBanner: boolean
  policyReadOnly: boolean
  features: TrafficFeature[]
} {
  return {
    showOffBanner: settings.allocatorMode === 'off',
    // S3 turns the policy into a real enum; until then `configurable` is false.
    policyReadOnly: settings.scheduling.configurable === false,
    features: settings.unimplemented.map((feature) => ({
      feature,
      reasonKey: `traffic.unimpl.${FEATURE_KEYS[feature] ?? feature}`
    }))
  }
}
