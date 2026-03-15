// ---- CLI Payload Type System ----
import type { Stats } from '../services/api'

export type CliPayloadType = 'flag' | 'string' | 'slug' | 'kb-id' | 'address' | 'line'

export interface CliPayload {
  name: string
  hint?: string
  valueType?: CliPayloadType  // default: 'flag'
  slugSource?: string         // comma-separated static list OR data from stats (e.g. '[stats.available_llms])')
  repeatable?: boolean
  required?: boolean
}

// ---- Parsed arguments ----

export interface ParsedArgs {
  positional: Record<string, string | string[]>
  options: Record<string, string | boolean | string[]>
}

// ---- Command definition ----

export interface CommandDefinition {
  trigger: string
  group: string
  hint?: string
  positional?: CliPayload[]
  options?: CliPayload[]
  requiresDataset?: string
}

// ---- Handler types ----

export interface CommandContext {
  setBusyMessage(message: string | null): void
  onDone?: () => Promise<void>
  navigate?: (addr: string) => Promise<void>
  args: ParsedArgs
}

export interface CommandResult {
  clearInput: boolean
}

export type CommandHandler = (
  command: string,
  payload: string,
  ctx: CommandContext
) => Promise<CommandResult>

export interface CommandModule {
  commands: (stats: Stats) => CommandDefinition[]
  handler: CommandHandler
}

/**
 * Normalize a narrative address: ensure it starts with `/` and does not end with `/`.
 */
export function normalizeAddress(addr: string | undefined): string | undefined {
  if (!addr) return undefined
  let normalized = addr.replace(/\/+$/, '')
  if (!normalized.startsWith('/')) normalized = '/' + normalized
  return normalized
}
