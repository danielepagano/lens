import type { CommandDefinition, CommandHandler, CommandModule } from './common'
import { cliModule } from './cli'
import { transactionModule } from './transaction'
import { dndModule } from './dnd'
import { narrativeModule } from './narrative'
import { operatorModule } from './operators'

export type { CommandHandler }

const MODULES: CommandModule[] = [
  transactionModule,
  narrativeModule,
  operatorModule,
  cliModule,
  dndModule,
]

function buildFromModules(
  modules: CommandModule[],
  datasets: string[] | null
): { definitions: CommandDefinition[]; handlerMap: Map<string, CommandHandler> } {
  const definitions: CommandDefinition[] = []
  const handlerMap = new Map<string, CommandHandler>()

  for (const mod of modules) {
    for (const cmd of mod.commands(datasets)) {
      definitions.push(cmd)
      handlerMap.set(cmd.trigger, mod.handler)
    }
  }

  definitions.sort((a, b) => a.group.localeCompare(b.group) || a.trigger.localeCompare(b.trigger))

  return { definitions, handlerMap }
}

let current = buildFromModules(MODULES, null)

export let COMMAND_DEFINITIONS: readonly CommandDefinition[] = current.definitions
export let KNOWN_COMMANDS: readonly string[] = current.definitions.map((c) => c.trigger)

export function updateDatasetCommands(currentDatasets: string[] | null): void {
  current = buildFromModules(MODULES, currentDatasets)
  COMMAND_DEFINITIONS = current.definitions
  KNOWN_COMMANDS = current.definitions.map((c) => c.trigger)
}

export function resolveHandler(command: string): CommandHandler {
  const handler = current.handlerMap.get(command)
  if (!handler) throw new Error(`Unknown command: ${command}`)
  return handler
}
