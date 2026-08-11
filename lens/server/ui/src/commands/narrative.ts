import { narrativePin, narrativeRewind, type NarrativePinBody } from '../services/api'
import {
  treeRefreshTrigger,
  transactionResult,
  scrollContentToBottom,
  scrollCodeMirrorToBottom,
  explainRequest,
} from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { CORE_OPERATOR_SLUGS, DATASET_OPERATOR_SLUGS, normalizeAddress } from './common'

const PIN_KB_OPS = ['add', 'remove', 'block', 'unblock', 'mention', 'include'] as const
const PIN_VAR_OPS = ['set', 'unset'] as const
const PIN_PARAM_OPS = ['set', 'unset'] as const
const OPERATOR_SLUGS = [...CORE_OPERATOR_SLUGS, ...Object.keys(DATASET_OPERATOR_SLUGS)]
const PIN_PARAM_SCOPE_SLUGS = ['global', ...OPERATOR_SLUGS].join(',')
const PIN_PARAM_KEY_SLUGS = [
  'llm_id',
  'reasoning',
  'slug',
  'module_id',
  'summary_guide',
  'aggressiveness',
  'as_kb_id',
  'with_kb_id',
  'narrate',
  'wait',
  'as_pc',
  'increment',
].join(',')

const commands: CommandDefinition[] = [
  {
    trigger: 'pin-kb',
    group: 'pin',
    cursorTargeting: 'can-override',
    positional: [
      { name: 'action', valueType: 'slug', required: true, slugSource: 'add,remove,block,unblock,mention,include' },
      { name: 'ids', valueType: 'kb-id', required: true, repeatable: true, hint: 'KB object ID' },
    ],
    options: [{ name: 'node', valueType: 'address', hint: 'narrative address' }],
  },
  {
    trigger: 'pin-var',
    group: 'pin',
    cursorTargeting: 'can-override',
    positional: [
      { name: 'action', valueType: 'slug', required: true, slugSource: 'set,unset' },
      { name: 'key', required: true, hint: 'Var key' },
      { name: 'value', valueType: 'string', required: false, hint: 'Value (required for set)' },
    ],
    options: [{ name: 'node', valueType: 'address', hint: 'narrative address' }],
  },
  {
    trigger: 'pin-param',
    group: 'pin',
    cursorTargeting: 'can-override',
    positional: [
      { name: 'action', valueType: 'slug', required: true, slugSource: 'set,unset' },
      { name: 'scope', valueType: 'slug', required: true, slugSource: PIN_PARAM_SCOPE_SLUGS, hint: 'global or operator slug' },
      { name: 'key', valueType: 'slug', required: true, slugSource: PIN_PARAM_KEY_SLUGS, hint: 'Canonical param key' },
      { name: 'value', valueType: 'string', required: false, hint: 'Value (required for set)' },
    ],
    options: [{ name: 'node', valueType: 'address', hint: 'narrative address' }],
  },
  {
    trigger: 'structure-rewind',
    group: 'structure',
    cursorTargeting: 'never',
    positional: [
      { name: 'address', valueType: 'address', required: true, hint: 'node address' },
      { name: 'line', valueType: 'line', required: false, hint: 'line number' },
    ],
  },
  {
    trigger: 'structure-explain',
    group: 'structure',
    cursorTargeting: 'never',
    hint: 'what is in the prompt here, how big, and why',
    positional: [
      { name: 'address', valueType: 'address', required: false, hint: 'node address (default: cursor)' },
      { name: 'line', valueType: 'line', required: false, hint: 'as of line number' },
    ],
    options: [
      {
        name: 'operator',
        valueType: 'slug',
        slugSource: OPERATOR_SLUGS.join(','),
        hint: 'assemble as this operator',
      },
    ],
  },
]

async function postPin(body: NarrativePinBody, ctx: CommandContext): Promise<{ clearInput: boolean }> {
  try {
    const result = await narrativePin(body)
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

function positionalLine(ctx: CommandContext): number | undefined {
  const raw = ctx.args.positional['line'] as string | undefined
  const parsed = raw !== undefined && raw !== '' ? parseInt(raw, 10) : NaN
  return Number.isInteger(parsed) ? parsed : undefined
}

const handler: CommandHandler = async (command, _payload, ctx: CommandContext) => {
  transactionResult.set(null)

  if (command === 'structure-explain') {
    // Read-only report: the modal owns the fetch, this only opens it.
    const address = normalizeAddress(ctx.args.positional['address'] as string | undefined)
    const operator = ctx.args.options['operator'] as string | undefined
    explainRequest.set({
      ...(address !== undefined ? { address } : {}),
      ...(positionalLine(ctx) !== undefined ? { line: positionalLine(ctx) } : {}),
      ...(operator ? { operator } : {}),
    })
    return { clearInput: true }
  }

  if (command === 'structure-rewind') {
    const rawAddress = ctx.args.positional['address'] as string | undefined
    const address = normalizeAddress(rawAddress)
    const line = positionalLine(ctx)
    if (!address) {
      return { clearInput: false }
    }
    try {
      const result = await narrativeRewind({ address, line })
      if (result.status === 'ok') {
        if (ctx.onDone) await ctx.onDone()
        treeRefreshTrigger.update((n) => n + 1)
        scrollContentToBottom.update((n) => n + 1)
        scrollCodeMirrorToBottom.update((n) => n + 1)
        return { clearInput: true }
      }
      transactionResult.set({
        title: 'Rewind error',
        message: result.detail ?? 'Unknown error',
      })
      return { clearInput: false }
    } catch (err) {
      transactionResult.set({
        title: 'Rewind error',
        message: err instanceof Error ? err.message : String(err),
      })
      return { clearInput: false }
    }
  }

  const node = normalizeAddress(ctx.args.options['node'] as string | undefined)

  if (command === 'pin-kb') {
    const operation = ctx.args.positional['action'] as string | undefined
    const ids = ctx.args.positional['ids'] as string[] | undefined
    if (!operation || !PIN_KB_OPS.includes(operation as (typeof PIN_KB_OPS)[number]) || !ids || ids.length === 0) {
      return { clearInput: false }
    }
    const body: NarrativePinBody = {
      kind: 'kb',
      operation: operation as (typeof PIN_KB_OPS)[number],
      ids,
      node,
    }
    return postPin(body, ctx)
  }

  if (command === 'pin-var') {
    const action = ctx.args.positional['action'] as string | undefined
    const key = ctx.args.positional['key'] as string | undefined
    const valueRaw = ctx.args.positional['value'] as string | undefined
    if (!action || !PIN_VAR_OPS.includes(action as (typeof PIN_VAR_OPS)[number]) || !key) {
      return { clearInput: false }
    }
    if (action === 'set' && (valueRaw === undefined || valueRaw === '')) {
      transactionResult.set({
        title: 'Pin error',
        message: 'var set requires a value',
      })
      return { clearInput: false }
    }
    const body: NarrativePinBody =
      action === 'set'
        ? { kind: 'var', operation: 'set', key, value: valueRaw ?? '', node }
        : { kind: 'var', operation: 'unset', key, node }
    return postPin(body, ctx)
  }

  if (command === 'pin-param') {
    const action = ctx.args.positional['action'] as string | undefined
    const scope = ctx.args.positional['scope'] as string | undefined
    const key = ctx.args.positional['key'] as string | undefined
    const valueRaw = ctx.args.positional['value'] as string | undefined
    if (
      !action ||
      !PIN_PARAM_OPS.includes(action as (typeof PIN_PARAM_OPS)[number]) ||
      !scope ||
      !key
    ) {
      return { clearInput: false }
    }
    if (action === 'set' && (valueRaw === undefined || valueRaw === '')) {
      transactionResult.set({
        title: 'Pin error',
        message: 'param set requires a value',
      })
      return { clearInput: false }
    }
    const body: NarrativePinBody =
      action === 'set'
        ? { kind: 'param', operation: 'set', scope, key, value: valueRaw ?? '', node }
        : { kind: 'param', operation: 'unset', scope, key, node }
    return postPin(body, ctx)
  }

  return { clearInput: false }
}

export const narrativeModule: CommandModule = { commands: () => commands, handler }
