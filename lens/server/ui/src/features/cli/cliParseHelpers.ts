import type { CommandDefinition } from '../../commands/common'

export const MAX_CLI_HISTORY = 50
/** Command token after `/`; with the CLI's leading slash this spells `/@cursor`. */
export const GO_CURSOR_CHIP = '@cursor'

export function goCursorChipMatchesToken(commandToken: string): boolean {
  const prefix = commandToken.toLowerCase()
  if (prefix === '') return true
  if (GO_CURSOR_CHIP.startsWith(prefix)) return true
  if (GO_CURSOR_CHIP.slice(1).startsWith(prefix)) return true
  return false
}

export function parseCommandAndPayload(value: string): { command: string | null; payload: string } {
  const trimmed = value.trim()
  if (!trimmed.startsWith('/')) return { command: null, payload: '' }
  const withoutSlash = trimmed.slice(1)
  if (!withoutSlash) return { command: null, payload: '' }
  const parts = withoutSlash.split(/\s+/)
  const command = parts[0]?.toLowerCase() ?? null
  const payload = parts.slice(1).join(' ').trimStart()
  return { command, payload }
}

export function cliContainsOnlySessionOperator(input: string, sessionOp: string): boolean {
  const { command, payload } = parseCommandAndPayload(input)
  return command === sessionOp.toLowerCase() && payload.trim() === ''
}

export function commandHasNoCliParameters(definition: CommandDefinition | undefined): boolean {
  if (!definition) return false
  return (definition.positional?.length ?? 0) === 0 && (definition.options?.length ?? 0) === 0
}
