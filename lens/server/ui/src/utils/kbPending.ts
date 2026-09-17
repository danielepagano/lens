/**
 * Shared vocabulary for pending KB proposals.
 *
 * Three places show the same proposals — the inline marker where the
 * `[kb-op …]: #` block sits, the diff in the KB viewer, and the bullets in the
 * cursor footer — and they have to agree about what an op is called and which
 * glyph stands for it, or the reader has to learn three legends. The op verbs
 * are the five in `core/kb_pending.py`; the change kinds are the three in
 * `core/commands/kb_pending_view.py`.
 */

import type { PendingKb, PendingKbObject, PendingKbOp } from '../services/api'

/** One glyph per op verb. `applied` is the odd one: a record, not a proposal. */
export const KB_OP_GLYPH: Record<string, string> = {
  add: '+',
  patch: '⟲',
  tag: '#',
  remove: '−',
  applied: '✔',
}

/** Heading form: names the op, where a sentence would read as a caption. */
export const KB_OP_LABEL: Record<string, string> = {
  add: 'Create',
  patch: 'Patch',
  tag: 'Retag',
  remove: 'Remove',
  applied: 'Written at close',
}

/** Sentence form, for a tooltip that has to stand on its own. */
export const KB_OP_VERB: Record<string, string> = {
  add: 'Creates',
  patch: 'Patches',
  tag: 'Retags',
  remove: 'Removes',
  applied: 'Written at close',
}

export type PendingChange = PendingKbObject['change']

export const KB_CHANGE_GLYPH: Record<PendingChange, string> = {
  created: '+',
  updated: '⟲',
  removed: '−',
}

/** Sentence form, for a tooltip that has to stand on its own. */
export const KB_CHANGE_VERB: Record<PendingChange, string> = {
  created: 'New — this session would create it',
  updated: 'Changed — proposed over what is on disk',
  removed: 'Removed — this session would delete it',
}

/** Label form, for a banner that already says "proposed" beside it. */
export const KB_CHANGE_LABEL: Record<PendingChange, string> = {
  created: 'New object',
  updated: 'Changed',
  removed: 'Removed',
}

export function kbOpGlyph(op: string): string {
  return KB_OP_GLYPH[op] ?? '·'
}

export function kbOpVerb(op: string): string {
  return KB_OP_VERB[op] ?? op
}

export function kbOpLabel(op: string): string {
  return KB_OP_LABEL[op] ?? op
}

/**
 * The ops touching *id*, which is what a viewer banner counts.
 *
 * Ops stack — three patches to one object are three ops and one changed
 * object — so the object list and the op list answer different questions and
 * neither is derivable from the other.
 */
export function opsForId(pending: PendingKb | null, id: string): PendingKbOp[] {
  if (!pending) return []
  return pending.ops.filter((op) => op.op !== 'applied' && op.id === id)
}

export function pendingObjectFor(
  pending: PendingKb | null,
  id: string,
): PendingKbObject | null {
  if (!pending) return null
  return pending.objects.find((obj) => obj.id === id) ?? null
}
