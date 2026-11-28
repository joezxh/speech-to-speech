import type { ToolInvokeResult, ToolRow } from '@/api/tools'
import type { ToolCall, ToolDef } from '@/features/voice/types'

const CAMERA_TOOL: ToolDef = {
  type: 'function',
  name: 'camera_snapshot',
  description: "Capture a frame from the user's webcam when they refer to something visual.",
  parameters: { type: 'object', properties: {}, required: [] }
}

function schema(row: ToolRow): Record<string, unknown> {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const param of row.params) {
    if (!param.k) continue
    properties[param.k] = { type: param.t === 'number' ? 'number' : param.t === 'boolean' ? 'boolean' : 'string' }
    if (param.req) required.push(param.k)
  }
  return { type: 'object', properties, required }
}

export function buildVoiceToolDefs(rows: ToolRow[], cameraEnabled: boolean): ToolDef[] {
  const defs: ToolDef[] = rows.map((row) => ({
    type: 'function',
    name: row.id,
    description: row.description || row.name,
    parameters: schema(row)
  }))
  if (cameraEnabled) defs.push(CAMERA_TOOL)
  return defs
}

export function serializeToolResult(envelope: ToolInvokeResult): string {
  return JSON.stringify(envelope)
}

export function describeToolCall(call: ToolCall, rows: ToolRow[]): string {
  const row = rows.find((item) => item.id === call.name)
  if (row) return row.description || row.name
  if (call.name === 'camera_snapshot') return 'Capturing a camera frame'
  return `Running ${call.name}`
}
