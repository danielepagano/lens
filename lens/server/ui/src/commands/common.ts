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

