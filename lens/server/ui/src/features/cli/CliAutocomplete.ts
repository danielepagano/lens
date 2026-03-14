import type { CommandGroup, CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { TreeNode, Stats } from '../../services/api'

export interface Suggestion {
  label: string
  value: string
  kind: 'command' | 'slug' | 'kb-type' | 'kb-key' | 'flag' | 'node'
  group: CommandGroup
  nodeHasChildren?: boolean
}

export interface DataSources {
  kbTypes: string[]
  kbKeyCache: Map<string, string[]>
  fetchKbKeys: (type: string) => void
  nodeTree: TreeNode[] | null
  fetchNodeTree: () => void
  kbKeyThreshold: number
  stats: Stats | null
}

/** Build command-level suggestions (no definition resolved yet). */
export function getCommandSuggestions(
  definitions: readonly CommandDefinition[],
  prefix: string,
): Suggestion[] {
  const lower = prefix.toLowerCase()
  const matches = lower
    ? definitions.filter((d) => d.trigger.startsWith(lower))
    : definitions
  const list = matches.length > 0 ? matches : definitions
  return list.map((d) => ({
    label: '/' + d.trigger,
    value: d.trigger,
    kind: 'command' as const,
    group: d.group,
  }))
}

/** Build suggestions based on parse state and the active payload being typed. */
export function getSuggestions(
  state: ParseState,
  def: CommandDefinition | null,
  sources: DataSources,
): Suggestion[] {
  const group = def?.group ?? 'cli'

  // Typing a --flag name: show matching available options
  if (state.currentToken.startsWith('-') && def?.options) {
    const partial = state.currentToken.replace(/^-+/, '')
    return def.options
      .filter((o) => {
        if (!o.repeatable && state.completedOptions[o.name] !== undefined) return false
        return o.name.startsWith(partial)
      })
      .map((o) => ({
        label: '--' + o.name,
        value: '--' + o.name,
        kind: 'flag' as const,
        group,
      }))
  }

  // Empty token: show option chips + positional suggestions.
  // While entering an option value (phase === 'option-value'), suppress other option chips
  // so the user only sees suggestions for the value being typed — not other flags.
  if (state.currentToken === '') {
    const enteringOptionValue = state.phase === 'option-value'
    const optionChips: Suggestion[] = !enteringOptionValue && state.canOfferOptions && def?.options
      ? def.options
          .filter((o) => !o.repeatable ? state.completedOptions[o.name] === undefined : true)
          .map((o) => ({
            label: '--' + o.name,
            value: '--' + o.name,
            kind: 'flag' as const,
            group,
          }))
      : []

    const positionalSugs = state.activePayload
      ? getPositionalSuggestions(state.activePayload, '', group, sources)
      : []

    return [...optionChips, ...positionalSugs]
  }

  // Non-empty non-flag token: positional suggestions only
  if (state.activePayload) {
    return getPositionalSuggestions(state.activePayload, state.currentToken, group, sources)
  }

  return []
}

function getPositionalSuggestions(
  payload: import('../../commands/common').CliPayload,
  currentToken: string,
  group: CommandGroup,
  sources: DataSources,
): Suggestion[] {
  switch (payload.valueType ?? 'flag') {
    case 'slug':
      return getSlugSuggestions(payload.slugSource ?? '', currentToken, group, sources.stats)
    case 'kb-id':
      return getKbIdSuggestions(currentToken, group, sources)
    case 'address':
      return getAddressSuggestions(currentToken, group, sources)
    default:
      return []
  }
}

function getSlugSuggestions(
  slugSource: string,
  prefix: string,
  group: CommandGroup,
  stats: Stats | null,
): Suggestion[] {
  let values: string[]

  // Dynamic stats reference: [stats.field_name]
  const statsMatch = slugSource.match(/^\[stats\.(\w+)\]$/)
  if (statsMatch) {
    const field = statsMatch[1] as keyof Stats
    const statsValue = stats?.[field]
    values = Array.isArray(statsValue) ? statsValue : []
  } else {
    // Comma-separated static list
    values = slugSource.split(',').map((s) => s.trim()).filter(Boolean)
  }

  const matches = prefix ? values.filter((v) => v.startsWith(prefix)) : values
  return (matches.length > 0 ? matches : values).map((v) => ({
    label: v,
    value: v,
    kind: 'slug' as const,
    group,
  }))
}

function getKbIdSuggestions(
  currentToken: string,
  group: CommandGroup,
  sources: DataSources,
): Suggestion[] {
  const dotIdx = currentToken.indexOf('.')
  if (dotIdx < 0) {
    // Type level: show KB types matching prefix
    const prefix = currentToken
    const matches = prefix
      ? sources.kbTypes.filter((t) => t.startsWith(prefix))
      : sources.kbTypes
    return matches.map((t) => ({
      label: t,
      value: t + '.',
      kind: 'kb-type' as const,
      group,
    }))
  }

  // Key level: show KB keys for the typed type
  const typeName = currentToken.slice(0, dotIdx)
  const keyPrefix = currentToken.slice(dotIdx + 1)

  if (typeName) {
    if (!sources.kbKeyCache.has(typeName)) {
      sources.fetchKbKeys(typeName)
      return []
    }
  }

  const allKeys = sources.kbKeyCache.get(typeName) ?? []
  if (keyPrefix.length === 0 && allKeys.length >= sources.kbKeyThreshold) {
    return [] // too many to show without a prefix
  }
  const matches = keyPrefix ? allKeys.filter((k) => k.startsWith(keyPrefix)) : allKeys
  return matches.map((k) => ({
    label: k,
    value: typeName + '.' + k,
    kind: 'kb-key' as const,
    group,
  }))
}

function getAddressSuggestions(
  partial: string,
  group: CommandGroup,
  sources: DataSources,
): Suggestion[] {
  if (sources.nodeTree === null) {
    sources.fetchNodeTree()
    return []
  }

  const endsWithSlash = partial.endsWith('/')
  const rawSegments = partial ? partial.split('/').filter(Boolean) : []
  let nodes: TreeNode[] = sources.nodeTree

  // Navigate to current level
  const navigateSegments = endsWithSlash ? rawSegments : rawSegments.slice(0, -1)
  for (const seg of navigateSegments) {
    const found = nodes.find((n) => n.key === seg)
    if (!found) return []
    nodes = found.children
  }

  const currentPrefix = endsWithSlash ? '' : (rawSegments[rawSegments.length - 1] ?? '')
  const addressBase = rawSegments
    .slice(0, endsWithSlash ? rawSegments.length : rawSegments.length - 1)
    .join('/')
  const baseWithSlash = addressBase ? addressBase + '/' : ''

  const filtered = currentPrefix
    ? nodes.filter((n) => n.key.startsWith(currentPrefix))
    : nodes

  return filtered.map((n) => ({
    label: n.key,
    value: baseWithSlash + n.key,
    kind: 'node' as const,
    group,
    nodeHasChildren: n.children.length > 0,
  }))
}
