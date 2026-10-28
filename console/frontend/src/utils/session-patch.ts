/** Build A.9's payload from the form: only filled-in fields travel.
 *
 * `session.update` merges `model_fields_set` (spec §2.2), so “absent” and
 * “explicitly false/null” are different instructions. `null` here means the
 * operator never touched the control, and the field must not be sent at all.
 */
import i18n from '@/i18n'

export interface SessionForm {
  instructions: string
  createResponse: boolean | null
  interruptResponse: boolean | null
  language: string
  /** Raw JSON text for `extensions`; `''` means “leave it alone”. */
  extensions: string
}

export interface BuiltPatch {
  session: Record<string, unknown>
  /** Non-empty means “do not submit”. */
  problems: string[]
}

export function buildSessionPatch(form: SessionForm): BuiltPatch {
  const problems: string[] = []
  const session: Record<string, unknown> = {}

  const instructions = form.instructions.trim()
  if (instructions) session.instructions = instructions

  const turnDetection: Record<string, unknown> = {}
  if (form.createResponse !== null) turnDetection.create_response = form.createResponse
  if (form.interruptResponse !== null) turnDetection.interrupt_response = form.interruptResponse

  const language = form.language.trim()
  const audioInput: Record<string, unknown> = {}
  if (Object.keys(turnDetection).length > 0) audioInput.turn_detection = turnDetection
  if (language) audioInput.transcription = { language }
  if (Object.keys(audioInput).length > 0) session.audio = { input: audioInput }

  const extensions = form.extensions.trim()
  if (extensions) {
    try {
      const parsed: unknown = JSON.parse(extensions)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        session.extensions = parsed
      } else {
        problems.push(i18n.global.t('sessionUpdate.problemExtensionsNotObject'))
      }
    } catch {
      problems.push(i18n.global.t('sessionUpdate.problemExtensionsInvalidJson'))
    }
  }

  if (Object.keys(session).length === 0 && problems.length === 0) {
    problems.push(i18n.global.t('sessionUpdate.problemNothingToPatch'))
  }
  return { session, problems }
}
