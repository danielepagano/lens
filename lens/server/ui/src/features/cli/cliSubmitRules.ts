import { COMMAND_DEFINITIONS } from '../../commands/handlers'
import { parseCliInput, buildArgs } from '../../commands/parser'

/** Space after ``--replace`` submits ``/edit … --replace`` with no prompt. */
export function shouldSpaceSubmitEditReplace(candidateInput: string): boolean {
  const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === 'edit')
  if (!definition) return false
  if (!candidateInput.trim().startsWith('/')) return false
  const state = parseCliInput(candidateInput, definition)
  const args = buildArgs(state, definition)
  if (args.options['replace'] !== true) return false
  const prompt = args.positional['prompt'] as string | undefined
  if (prompt !== undefined && String(prompt).trim() !== '') return false
  const addr = args.positional['address']
  const start = args.positional['start']
  const end = args.positional['end']
  if (addr === undefined || start === undefined || end === undefined) return false
  const startNumber = parseInt(String(start), 10)
  const endNumber = parseInt(String(end), 10)
  if (!Number.isFinite(startNumber) || !Number.isFinite(endNumber)) return false
  return true
}

/** Space after ``--manual`` submits ``/write --manual`` with no prompt. */
export function shouldSpaceSubmitWriteManual(candidateInput: string): boolean {
  const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === 'write')
  if (!definition) return false
  if (!candidateInput.trim().startsWith('/')) return false
  const state = parseCliInput(candidateInput, definition)
  const args = buildArgs(state, definition)
  if (args.options['manual'] !== true) return false
  const prompt = args.positional['prompt'] as string | undefined
  if (prompt !== undefined && String(prompt).trim() !== '') return false
  return true
}

export function shouldSpaceSubmit(candidateInput: string): boolean {
  return shouldSpaceSubmitEditReplace(candidateInput) || shouldSpaceSubmitWriteManual(candidateInput)
}
