// ---- CLI Payload Type System ----
import type { Stats } from '../services/api'

export type CliPayloadType = 'flag' | 'string' | 'slug' | 'kb-id' | 'address' | 'line' | 'int' | 'prompt' | 'file-path'

// Commands like write always append at cursor, edit never does, pin does by default but can be overriden, etc. 
export type CliCommandCursorTarget = 'always' | 'never' | 'can-override'

export interface CliPayload {
  name: string
  hint?: string
  valueType?: CliPayloadType  // default: 'flag'
  slugSource?: string         // comma-separated static list OR data from stats (e.g. '[stats.available_llms])')
  repeatable?: boolean
  required?: boolean
  default?: string            // if set, pre-fill the selection with a value
  exclude?: string[]          // kb-id values to exclude from suggestions (e.g. auto-pinned modules)
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
  cursorTargeting: CliCommandCursorTarget
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
 * Normalize a narrative address for CLI/API: trim trailing slashes.
 * - Nav form (`story/chapter`) — first segment is the narrative slug — is passed through unchanged.
 * - Bare segment (`chapter`) becomes `/chapter` (display form: path under active narrative).
 */
export function normalizeAddress(addr: string | undefined): string | undefined {
  if (!addr) return undefined
  const normalized = addr.replace(/\/+$/, '')
  if (!normalized) return '/'
  if (normalized.startsWith('/')) return normalized
  if (normalized.includes('/')) return normalized
  return '/' + normalized
}

/**
 * Convert a normalized address to the nav string used by `currentAddress` / `getNode` (e.g. `story/chapter-1`).
 * Display-relative paths (`/scene`) are prefixed with the active narrative root slug.
 */
export function addressToNavAddress(normalized: string, narrativeRoot: string): string {
  if (normalized.includes('/') && !normalized.startsWith('/')) {
    return normalized
  }
  if (normalized === '/' || normalized === '') {
    return narrativeRoot
  }
  if (normalized.startsWith('/')) {
    return narrativeRoot + normalized
  }
  return narrativeRoot + '/' + normalized
}
