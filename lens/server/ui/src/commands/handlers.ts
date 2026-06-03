import type { CommandDefinition, CommandHandler, CommandModule } from './common'
import { mediaModule } from './media'
import { transactionModule } from './transaction'
import { narrativeModule } from './narrative'
import { operatorModule } from './operators'
import type { Stats } from '../services/api'

export type { CommandHandler }

const MODULES: CommandModule[] = [
  transactionModule,
  narrativeModule,
  operatorModule,
  mediaModule,
]

function buildFromModules(
  modules: CommandModule[],
  stats: Stats
): { definitions: CommandDefinition[]; handlerMap: Map<string, CommandHandler> } {
  const definitions: CommandDefinition[] = []
  const handlerMap = new Map<string, CommandHandler>()

  for (const mod of modules) {
    for (const cmd of mod.commands(stats)) {
      definitions.push(cmd)
      handlerMap.set(cmd.trigger, mod.handler)
    }
  }

  definitions.sort((a, b) => a.group.localeCompare(b.group) || a.trigger.localeCompare(b.trigger))

  return { definitions, handlerMap }
}

export let COMMAND_DEFINITIONS: readonly CommandDefinition[] = []
export let KNOWN_COMMANDS: readonly string[] = []
let HANDLER_MAP = new Map<string, CommandHandler>()

export function updateDatasetCommands(stats: Stats): void {
  const current = buildFromModules(MODULES, stats)
  HANDLER_MAP = current.handlerMap
  COMMAND_DEFINITIONS = current.definitions
  KNOWN_COMMANDS = current.definitions.map((c) => c.trigger)
}

export function resolveHandler(command: string): CommandHandler {
  const handler = HANDLER_MAP.get(command)
  if (!handler) throw new Error(`Unknown command: ${command}`)
  return handler
}
