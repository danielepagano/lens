import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { TreeNode, Stats, MountEntry } from '../../services/api'

export interface Suggestion {
  label: string
  value: string
  kind: 'command' | 'slug' | 'kb-type' | 'kb-key' | 'flag' | 'node' | 'dice-roll'
  group: string
  nodeHasChildren?: boolean
  /** Mount browse only: directory row (yellow dashed chip like prefix groups) */
  isMountDirectory?: boolean
  /** Appended after `value` on Tab/select: `' '` finishes token, `'-'` continues dashed segments */
  completionSuffix?: string
}

/** Hard cap on CLI suggestion chips (display + Tab cycle use the same list). */
export const MAX_CLI_SUGGESTIONS = 32

export function limitCliSuggestions(suggestions: readonly Suggestion[]): Suggestion[] {
  return suggestions.slice(0, MAX_CLI_SUGGESTIONS)
}

/**
 * After picking a grouped dashed row: use `'-'` when longer keys exist (`artificer-*`), else `' '`.
 */
export function dashedGroupingCompletionSuffix(
  selected: string,
  pool: readonly string[],
): string {
  const exact = pool.includes(selected)
  const hasDashExtension = pool.some(
    (full) => full !== selected && full.startsWith(`${selected}-`),
  )
  if (exact) return ' '
  if (hasDashExtension) return '-'
  return ' '
}

/**
 * Split `keyPrefix` into a dash-boundary `stem` (complete segments, may end with `-`)
 * and `inSeg` (partial segment filter). Used to show labels relative to the stem
 * (e.g. `artificer-a` → stem `artificer-`, inSeg `a` → group on `alchemist-*` not `artificer-alchemist-*`).
 */
export function decomposeKbKeyTypingPrefix(
  keyPrefix: string,
  filteredKeys: readonly string[],
): { stem: string; inSeg: string } {
  if (!keyPrefix) return { stem: '', inSeg: '' }

  if (keyPrefix.endsWith('-')) {
    return { stem: keyPrefix, inSeg: '' }
  }

  const allBranch =
    filteredKeys.length > 0 &&
    filteredKeys.every((k) => k === keyPrefix || k.startsWith(`${keyPrefix}-`))
  if (allBranch) {
    return { stem: keyPrefix, inSeg: '' }
  }

  const lastDash = keyPrefix.lastIndexOf('-')
  if (lastDash >= 0) {
    return {
      stem: keyPrefix.slice(0, lastDash + 1),
      inSeg: keyPrefix.slice(lastDash + 1),
    }
  }

  return { stem: '', inSeg: keyPrefix }
}

/** Key text after `stem` (strip leading dashes from remainder). */
export function kbKeyRemainderAfterStem(fullKey: string, stem: string): string {
  if (!stem) return fullKey
  if (!fullKey.startsWith(stem)) return ''
  return fullKey.slice(stem.length).replace(/^-+/, '')
}

/** Rebuild full key from stem through a grouped remainder. */
export function joinKbStemAndGroupedRest(stem: string, groupedRest: string): string {
  if (!stem) return groupedRest
  if (!groupedRest) return stem
  if (stem.endsWith('-')) return stem + groupedRest
  return `${stem}-${groupedRest}`
}

export interface DataSources {
  kbTypes: string[]
  kbKeyCache: Map<string, string[]>
  fetchKbKeys: (type: string) => void
  nodeTree: TreeNode[] | null
  fetchNodeTree: () => void
  stats: Stats | null
  mountDirCache: Map<string, MountEntry[]>
  fetchMountDir: (path: string) => void
}

const DENSE_GROUP_MIN_LEAVES = 4

interface TrieNode {
  children: Map<string, TrieNode>
  terminalCount: number
  leafCount: number
}

function newTrieNode(): TrieNode {
  return { children: new Map(), terminalCount: 0, leafCount: 0 }
}

function splitSegments(s: string, delimiter: string): string[] {
  return s.split(delimiter).filter(Boolean)
}

function joinSegments(segments: readonly string[], delimiter: string): string {
  return segments.join(delimiter)
}

function insertTrie(root: TrieNode, segments: readonly string[]): void {
  let node = root
  for (const seg of segments) {
    let next = node.children.get(seg)
    if (!next) {
      next = newTrieNode()
      node.children.set(seg, next)
    }
    node = next
  }
  node.terminalCount += 1
}

function finalizeLeafCounts(node: TrieNode): number {
  let n = node.terminalCount
  for (const ch of node.children.values()) {
    n += finalizeLeafCounts(ch)
  }
  node.leafCount = n
  return n
}

function collectLeaves(node: TrieNode, prefixSegs: string[], delimiter: string): string[] {
  const out: string[] = []
  if (node.terminalCount > 0) {
    const j = joinSegments(prefixSegs, delimiter)
    for (let i = 0; i < node.terminalCount; i += 1) out.push(j)
  }
  for (const [k, ch] of node.children) {
    out.push(...collectLeaves(ch, [...prefixSegs, k], delimiter))
  }
  return out
}

function terminalsHere(node: TrieNode, prefixSegs: string[], delimiter: string): string[] {
  if (node.terminalCount === 0) return []
  const j = joinSegments(prefixSegs, delimiter)
  return Array.from({ length: node.terminalCount }, () => j)
}

function emitGrouped(node: TrieNode, prefixSegs: string[], delimiter: string): string[] {
  const lc = node.leafCount
  if (lc < DENSE_GROUP_MIN_LEAVES) {
    return collectLeaves(node, prefixSegs, delimiter).sort()
  }
  if (node.children.size === 0) {
    return collectLeaves(node, prefixSegs, delimiter).sort()
  }
  if (node.children.size === 1) {
    const k = [...node.children.keys()][0]!
    const fromChild = emitGrouped(node.children.get(k)!, [...prefixSegs, k], delimiter)
    return [...terminalsHere(node, prefixSegs, delimiter), ...fromChild].sort()
  }
  const childEntries = [...node.children.entries()]
  const allTerminalFan =
    node.terminalCount === 0 &&
    childEntries.every(([, ch]) => ch.leafCount === 1 && ch.children.size === 0)
  const pathStr = joinSegments(prefixSegs, delimiter)
  const manyChildBranches =
    node.terminalCount === 0 && node.children.size >= DENSE_GROUP_MIN_LEAVES
  const collapseDensePrefix =
    pathStr.length > 0 &&
    lc >= DENSE_GROUP_MIN_LEAVES &&
    (allTerminalFan || manyChildBranches)
  if (collapseDensePrefix) {
    return [pathStr]
  }
  const out: string[] = [...terminalsHere(node, prefixSegs, delimiter)]
  for (const k of [...node.children.keys()].sort()) {
    out.push(...emitGrouped(node.children.get(k)!, [...prefixSegs, k], delimiter))
  }
  return out.sort()
}

/**
 * Collapse dense branches into one prefix row: either a fan of terminal children (≥DENSE_GROUP_MIN_LEAVES leaves)
 * or ≥DENSE_GROUP_MIN_LEAVES distinct next-segment children with no completion ending exactly at this path (e.g. many
 * `artificer-*` keys that continue deeper). Delimiter is `-` for slugs/keys or `/` for paths.
 */
export function groupDenseSegmentedPrefixes(
  values: readonly string[],
  delimiter: string,
): string[] {
  const unique = [...new Set(values.filter((v) => v.length > 0))]
  if (unique.length === 0) return []
  const root = newTrieNode()
  for (const v of unique) {
    const segs = splitSegments(v, delimiter)
    if (segs.length === 0) continue
    insertTrie(root, segs)
  }
  finalizeLeafCounts(root)
  return emitGrouped(root, [], delimiter)
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

/**
 * Returns true if we can determine that an option would have zero valid suggestions.
 * For kb-id options with a default type prefix: checks the cached key list (minus excludes).
 * For slug options: resolves the source and checks for entries.
 * Returns false (= show the option) when we can't tell yet (e.g. keys not cached).
 */
function optionKnownEmpty(
  o: import('../../commands/common').CliPayload,
  sources: DataSources,
): boolean {
  if (!o.valueType || o.valueType === 'flag') return false

  if (o.valueType === 'kb-id' && o.default) {
    // default is a type prefix like "rules." — check if the type has any non-excluded keys
    const typeName = o.default.replace(/\.$/, '')
    if (!sources.kbKeyCache.has(typeName)) {
      sources.fetchKbKeys(typeName) // trigger load; will re-evaluate once cached
      return false
    }
    const allKeys = (sources.kbKeyCache.get(typeName) ?? []).filter((k) => !k.startsWith('_template'))
    if (o.exclude) {
      const excludeSet = new Set(o.exclude)
      return allKeys.every((k) => excludeSet.has(typeName + '.' + k))
    }
    return allKeys.length === 0
  }

  if (o.valueType === 'slug' && o.slugSource) {
    const statsMatch = o.slugSource.match(/^\[stats\.(\w+)\]$/)
    if (statsMatch) {
      const field = statsMatch[1] as keyof Stats
      const statsValue = sources.stats?.[field]
      return !Array.isArray(statsValue) || statsValue.length === 0
    }
    // Static list — never empty if defined
  }

  return false
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
        if (optionKnownEmpty(o, sources)) return false
        return o.name.startsWith(partial)
      })
      .map((o) => ({
        label: '--' + o.name,
        value: '--' + o.name,
        kind: 'flag' as const,
        group,
      }))
  }

  // @mention autocomplete in prompt positionals: when typing @word, show KB type/key suggestions
  if (
    state.phase === 'positional' &&
    state.activePayload?.valueType === 'prompt' &&
    state.currentToken.startsWith('@')
  ) {
    return getPositionalSuggestions(state.activePayload, state.currentToken, group, sources)
  }

  // Empty token, or typing in a string/prompt positional: show option chips + positional suggestions
  // so the list doesn't pop in/out while editing. For string/prompt positionals we pass '' so we
  // only show option chips (no positional suggestions for free-form text).
  const showChipsAndPositional =
    state.currentToken === '' ||
    (state.phase === 'positional' &&
      (state.activePayload?.valueType === 'string' || state.activePayload?.valueType === 'prompt'))
  if (showChipsAndPositional) {
    const enteringOptionValue = state.phase === 'option-value'
    const optionChips: Suggestion[] = !enteringOptionValue && state.canOfferOptions && def?.options
      ? def.options
          .filter((o) => {
            if (!o.repeatable && state.completedOptions[o.name] !== undefined) return false
            return !optionKnownEmpty(o, sources)
          })
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
  group: string,
  sources: DataSources,
): Suggestion[] {
  switch (payload.valueType ?? 'flag') {
    case 'slug':
      return getSlugSuggestions(payload.slugSource ?? '', currentToken, group, sources.stats)
    case 'kb-id':
      return getKbIdSuggestions(currentToken, group, sources, payload.exclude)
    case 'address':
      return getAddressSuggestions(currentToken, group, sources)
    case 'prompt': {
      // Only suggest when typing an @mention
      if (!currentToken.startsWith('@')) return []
      // @roll autocomplete: token starts with '@roll' but is not a KB id mention (no dot after 'roll')
      if (currentToken.startsWith('@roll') && !currentToken.slice(1).includes('.')) {
        return [
          {
            label: 'roll',
            value: '@roll',
            kind: 'dice-roll' as const,
            group,
            completionSuffix: '',
          },
        ]
      }
      const kbPart = currentToken.slice(1)
      const rawSuggestions = getKbIdSuggestions(kbPart, group, sources, payload.exclude)
      return rawSuggestions.map((s) => ({ ...s, value: '@' + s.value }))
    }
    case 'file-path':
      return getFileSuggestions(currentToken, group, sources)
    default:
      return []
  }
}

function getSlugSuggestions(
  slugSource: string,
  prefix: string,
  group: string,
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
  const candidates = matches.length > 0 ? matches : values
  const grouped = groupDenseSegmentedPrefixes(candidates, '-')
  return grouped.map((v) => ({
    label: v,
    value: v,
    kind: 'slug' as const,
    group,
    completionSuffix: dashedGroupingCompletionSuffix(v, candidates),
  }))
}

function getKbIdSuggestions(
  currentToken: string,
  group: string,
  sources: DataSources,
  exclude?: string[],
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

  const excludeSet = exclude ? new Set(exclude) : null
  const allKeys = sources.kbKeyCache.get(typeName) ?? []
  const matches = keyPrefix ? allKeys.filter((k) => k.startsWith(keyPrefix)) : allKeys
  const filteredKeys = matches.filter(
    (k) => !k.startsWith('_template') && (!excludeSet || !excludeSet.has(typeName + '.' + k)),
  )

  const { stem, inSeg } = decomposeKbKeyTypingPrefix(keyPrefix, filteredKeys)

  const restRows: { fullKey: string; rest: string }[] = []
  for (const fullKey of filteredKeys) {
    const rest = kbKeyRemainderAfterStem(fullKey, stem)
    if (inSeg.length > 0 && !rest.startsWith(inSeg)) continue
    restRows.push({ fullKey, rest })
  }

  const withTail = restRows.filter((r) => r.rest.length > 0)
  const exactOnly = restRows.filter((r) => r.rest.length === 0)

  const restPool = withTail.map((r) => r.rest)
  const groupedRests = groupDenseSegmentedPrefixes(restPool, '-')

  const out: Suggestion[] = []
  for (const g of groupedRests) {
    const mergedKey = joinKbStemAndGroupedRest(stem, g)
    out.push({
      label: g,
      value: typeName + '.' + mergedKey,
      kind: 'kb-key' as const,
      group,
      completionSuffix: dashedGroupingCompletionSuffix(g, restPool),
    })
  }

  for (const { fullKey } of exactOnly) {
    const dash = fullKey.lastIndexOf('-')
    const label = dash < 0 ? fullKey : fullKey.slice(dash + 1)
    out.push({
      label,
      value: typeName + '.' + fullKey,
      kind: 'kb-key' as const,
      group,
      completionSuffix: ' ',
    })
  }

  return out.sort((a, b) => a.label.localeCompare(b.label))
}

function getAddressSuggestions(
  partial: string,
  group: string,
  sources: DataSources,
): Suggestion[] {
  if (sources.nodeTree === null) {
    sources.fetchNodeTree()
    return []
  }

  // The tree always has the narrative root as its single top-level node.
  // Address values use leading-slash form ('/' for root, '/ch1' for child), but tree
  // keys are rootKey-prefixed. Map leading-slash partials to rootKey-prefixed navigation
  // paths so tree traversal works correctly.
  // e.g. partial='/'    → navPartial='story/'   (navigate into root's children)
  //      partial='/ch1'  → navPartial='story/ch1' (match ch1 inside root)
  const rootKey = sources.nodeTree.length > 0 ? sources.nodeTree[0].key : null
  const navPartial = rootKey && partial.startsWith('/') ? rootKey + partial : partial

  const endsWithSlash = navPartial.endsWith('/')
  const rawSegments = navPartial ? navPartial.split('/').filter(Boolean) : []
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

  return filtered.map((n) => {
    const raw = baseWithSlash + n.key
    let value: string
    if (rootKey) {
      if (raw === rootKey) value = '/'
      else if (raw.startsWith(rootKey + '/')) value = raw.slice(rootKey.length)
      else value = raw
    } else {
      value = raw
    }
    return { label: n.key, value, kind: 'node' as const, group, nodeHasChildren: n.children.length > 0 }
  })
}

function getFileSuggestions(
  partial: string,
  group: string,
  sources: DataSources,
): Suggestion[] {
  // Split partial into directory prefix and filename prefix
  const lastSlash = partial.lastIndexOf('/')
  const dirPrefix = lastSlash >= 0 ? partial.slice(0, lastSlash + 1) : ''
  const namePrefix = lastSlash >= 0 ? partial.slice(lastSlash + 1) : partial

  const cacheKey = dirPrefix || ''
  if (!sources.mountDirCache.has(cacheKey)) {
    sources.fetchMountDir(cacheKey)
    return []
  }

  const entries = sources.mountDirCache.get(cacheKey) ?? []
  const lowerPrefix = namePrefix.toLowerCase()
  const filtered = namePrefix
    ? entries.filter((e) => e.name.toLowerCase().startsWith(lowerPrefix))
    : entries

  // Do not run groupDenseSegmentedPrefixes here: sibling entries in a directory are the
  // actual pick targets (files/dirs). Collapsing ≥DENSE_GROUP_MIN_LEAVES leaf names would replace them with the
  // parent path and make browsing empty or useless.
  return filtered.map((e) => ({
    label: e.name + (e.is_dir ? '/' : ''),
    value: dirPrefix + e.name,
    kind: 'node' as const,
    group,
    nodeHasChildren: e.is_dir,
    isMountDirectory: e.is_dir,
  }))
}
