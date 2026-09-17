/**
 * Pill rows for the cursor context panel.
 *
 * Pins, includes and mentions are three different scopes and the panel has to
 * say so: a pin covers the whole node and is inherited, an include covers the
 * rest of this node from where it was written, and a mention is good for one
 * more AI turn. Pure view logic, kept out of the component so it can be tested.
 */

import type { PendingKb } from '../../services/api'
import { KB_CHANGE_GLYPH, KB_CHANGE_VERB, opsForId, type PendingChange } from '../../utils/kbPending'

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
 * A `state`-tagged include/mention is diverted to the tail same as a state
 * pin — see `_add_mention_state_components` — so both lines apply: the scope
 * line says why it is in view, the state line says it does not inline where
 * that annotation sits.
 */
export function pillTitle(
  row: KbPillRow,
  opts: { isState: (id: string) => boolean; rememberTags: (id: string) => string[] },
): string | undefined {
  const lines: string[] = []
  if (row.scope) lines.push(SCOPE_TITLE[row.scope])
  if (!row.unpin && opts.isState(row.id)) {
    lines.push(
      row.scope
        ? 'Tagged `state` — diverts to Live State instead of inlining here'
        : 'Live state — sent after the last turn, re-sent every beat',
    )
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

/**
 * Split rows into the ancestor pins (usually unchanged node to node — fine to
 * fold behind the expandable summary) and the notable ones: scoped rows
 * (include/mention, node-local and short-lived) plus `state`-tagged pins
 * (mutable, re-sent every beat). The notable group is small and worth
 * surfacing without a click.
 */
export function splitPillRows(
  rows: KbPillRow[],
  isState: (id: string) => boolean,
): { plain: KbPillRow[]; notable: KbPillRow[] } {
  const plain: KbPillRow[] = []
  const notable: KbPillRow[] = []
  for (const row of rows) {
    const isNotable = Boolean(row.scope) || (!row.unpin && isState(row.id))
    ;(isNotable ? notable : plain).push(row)
  }
  return { plain, notable }
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
  pending?: number
}): string[] {
  const parts: string[] = []
  if (counts.pins) parts.push(plural(counts.pins, 'pin'))
  if (counts.unpins) parts.push(plural(counts.unpins, 'unpin'))
  if (counts.vars) parts.push(plural(counts.vars, 'var'))
  if (counts.params) parts.push(plural(counts.params, 'param'))
  if (counts.includes) parts.push(plural(counts.includes, 'include'))
  if (counts.mentions) parts.push(plural(counts.mentions, 'mention'))
  if (counts.pending) parts.push(plural(counts.pending, 'proposal'))
  return parts
}

export type PendingPillRow = {
  id: string
  change: PendingChange
  /** True when at least one op touching this id no longer resolves — a patch
   * whose anchor a direct edit removed, surfaced here rather than only in the
   * KB viewer, since the cursor footer is where a session-in-progress looks. */
  error: boolean
  /** Tooltip: what the change is, over what, and the failure if there is one. */
  title: string
}

/**
 * One bullet per *changed object*, not per op: ops stack (three patches to one
 * object are three ops in the log but one proposed object), so the object
 * list is what the footer summarizes and a bullet is a pointer into the KB
 * viewer for the full diff, never a summary of the patch itself.
 */
export function pendingKbRows(pending: PendingKb | null): PendingPillRow[] {
  if (!pending) return []
  return pending.objects.map((obj) => {
    const failingOps = opsForId(pending, obj.id).filter((op) => op.status === 'error')
    const lines = [KB_CHANGE_VERB[obj.change]]
    if (obj.base_source) lines.push(`over ${obj.base_source}`)
    for (const op of failingOps) lines.push(op.error)
    return {
      id: obj.id,
      change: obj.change,
      error: failingOps.length > 0,
      title: lines.join('\n'),
    }
  })
}

/** `+` created, `⟲` updated, `−` removed — same glyphs as the inline marker
 * and the KB viewer, so the reader learns one legend, not three. */
export function pendingPillLabel(row: PendingPillRow): string {
  return `${KB_CHANGE_GLYPH[row.change]} ${row.id}`
}
