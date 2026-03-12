export interface CommandContext {
  setBusyMessage(message: string | null): void
  onDone?: () => Promise<void>
}

export interface CommandResult {
  clearInput: boolean
}

export type CommandHandler = (
  command: string,
  payload: string,
  ctx: CommandContext
) => Promise<CommandResult>

export type CommandGroup = 'transactions' | 'cli' | (string & {})

export interface CommandDefinition {
  trigger: string
  group: CommandGroup
}

