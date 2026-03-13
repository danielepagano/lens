import { narrativePin, type PinOperation } from '../services/api'
import { treeRefreshTrigger, transactionResult } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  PayloadSuggest,
} from './common'

const PIN_OPERATIONS: PinOperation[] = ['add', 'remove', 'block', 'unblock']

const PIN_PAYLOAD_SUGGEST: PayloadSuggest = {
  levelSeparator: '.',
  valueSeparator: ' ',
  levels: [
    { source: 'kb-types', separator: '.' },
    { source: 'kb-keys', separator: ' ', threshold: 10 },
  ],
}

export const NARRATIVE_COMMANDS: CommandDefinition[] = [
  {
    trigger: 'pin',
    group: 'narrative',
    params: { kind: 'none' },
    subOptions: PIN_OPERATIONS.map((v) => ({ value: v })),
    payloadHint: 'KB object IDs',
    payloadSuggest: PIN_PAYLOAD_SUGGEST,
    payloadOpts: [{ flag: 'node', hint: 'narrative node' }],
  },
]

function extractNodeFlag(parts: string[]): { node: string | undefined; ids: string[] } {
  const idx = parts.indexOf('--node')
  if (idx === -1 || idx + 1 >= parts.length) {
    return { node: undefined, ids: parts.filter((p) => !p.startsWith('--')) }
  }
  const rawNode = parts[idx + 1]
  const node = rawNode.startsWith('/') ? rawNode : '/' + rawNode
  const ids = parts.filter((_, i) => i !== idx && i !== idx + 1 && !parts[i].startsWith('--'))
  return { node, ids }
}

export const narrativeCommandHandler: CommandHandler = async (
  _command,
  payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)
  const parts = payload.trim().split(/\s+/).filter(Boolean)
  const operation = parts[0] as PinOperation | undefined
  const { node, ids } = extractNodeFlag(parts.slice(1))

  if (!operation || !PIN_OPERATIONS.includes(operation) || ids.length === 0) {
    return { clearInput: false }
  }

  try {
    const result = await narrativePin(operation, ids, node)
    if (result.status === 'ok') {
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      return { clearInput: true }
    }
    transactionResult.set({
      title: 'Pin error',
      message: result.detail ?? 'Unknown error',
    })
    return { clearInput: false }
  } catch (err) {
    transactionResult.set({
      title: 'Pin error',
      message: err instanceof Error ? err.message : String(err),
    })
    return { clearInput: false }
  }
}
