/**
 * Pill rows for the cursor context panel.
 *
 * Pins, includes and mentions are three different scopes and the panel has to
 * say so: a pin covers the whole node and is inherited, an include covers the
 * rest of this node from where it was written, and a mention is good for one
 * more AI turn. Pure view logic, kept out of the component so it can be tested.
 */

export type PillScope = 'include' | 'mention'

export type KbPillRow = { id: string; unpin: boolean; scope?: PillScope }

const SCOPE_TITLE: Record<PillScope, string> = {
  include: 'Include — expands where it was written, for the rest of this node',
  mention: 'Mention — expands where it was written, for one more AI turn',
}

/** `-` unpinned, `+` include, `@` mention; a plain node pin has no prefix. */
export function pillLabel(row: KbPillRow): string {
  if (row.unpin) return `-${row.id}`
  if (row.scope === 'include') return `+${row.id}`
  if (row.scope === 'mention') return `@${row.id}`
  return row.id
}

/** Stable key: the same id can appear as both a pin and a mention. */
export function pillKey(row: KbPillRow, index: number): string {
  return `${index}:${row.scope ?? (row.unpin ? 'u' : 'p')}:${row.id}`
}

/**
 * One tooltip per pill, so the decorations cannot fight over `title`.
 * Scope wins over `state`: an object cannot be inlined *and* diverted to the
 * tail, so labelling a scoped pill as live state would be a lie.
 */
export function pillTitle(
  row: KbPillRow,
  opts: { isState: (id: string) => boolean; rememberTags: (id: string) => string[] },
): string | undefined {
  const lines: string[] = []
  if (row.scope) lines.push(SCOPE_TITLE[row.scope])
  else if (opts.isState(row.id)) {
    lines.push('Live state — sent after the last turn, re-sent every beat')
  }
  lines.push(...opts.rememberTags(row.id))
  return lines.length > 0 ? lines.join('\n') : undefined
}

/** Pins first, then the node-local scopes they do not behave like. */
export function cursorKbRows(
  pins: string[],
  includes: string[],
  mentions: string[],
): KbPillRow[] {
  return [
    ...pins.map((id) => ({ id, unpin: false })),
    ...includes.map((id) => ({ id, unpin: false, scope: 'include' as const })),
    ...mentions.map((id) => ({ id, unpin: false, scope: 'mention' as const })),
  ]
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

export function contextSummaryParts(counts: {
  pins: number
  unpins?: number
  vars: number
  params: number
  includes?: number
  mentions?: number
}): string[] {
  const parts: string[] = []
  if (counts.pins) parts.push(plural(counts.pins, 'pin'))
  if (counts.unpins) parts.push(plural(counts.unpins, 'unpin'))
  if (counts.vars) parts.push(plural(counts.vars, 'var'))
  if (counts.params) parts.push(plural(counts.params, 'param'))
  if (counts.includes) parts.push(plural(counts.includes, 'include'))
  if (counts.mentions) parts.push(plural(counts.mentions, 'mention'))
  return parts
}
