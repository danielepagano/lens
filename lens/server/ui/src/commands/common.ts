// ---- CLI Payload Type System ----

export type CliPayloadType = 'flag' | 'string' | 'slug' | 'kb-id' | 'address' | 'int'

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

export type CommandGroup = 'transactions' | 'cli' | (string & {})

export interface CommandDefinition {
  trigger: string
  group: CommandGroup
  hint?: string
  positional?: CliPayload[]
  options?: CliPayload[]
}

// ---- Handler types ----

export interface CommandContext {
  setBusyMessage(message: string | null): void
  onDone?: () => Promise<void>
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
