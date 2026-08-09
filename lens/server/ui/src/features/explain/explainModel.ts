/**
 * Pure model behind the context composition modal.
 *
 * All arithmetic, formatting and colour assignment lives here so the Svelte
 * components stay presentational and the invariants stay testable.
 *
 * The payload reconciles exactly in both units — `block.bytes` is the sum of
 * its components plus `framing_bytes`, and `totals.bytes` is the sum of the
 * blocks plus `other_bytes` — so nothing here needs a fudge segment. Shares
 * are recomputed rather than read off `percent`, because the server's
 * `percent` is byte-based and the modal can be showing tokens.
 */

import type { ExplainBlock, ExplainCache, ExplainComponent, ExplainReport } from '../../services/api'

export type ExplainUnit = 'tokens' | 'bytes'

/**
 * Visual floor for a bar segment, in percent. A block worth 0.3% of the
 * prompt still has to be visible and tappable; the remaining segments are
 * scaled down to pay for it.
 */
export const MIN_SEGMENT_WIDTH = 2.5

/** Provenance kinds that follow from something else rather than a pin of their own. */
const DERIVED_KINDS = new Set(['expansion', 'rules_companion', 'modality'])

/**
 * Colour slot per block id.
 *
 * `system` and `task` are operator boilerplate — not curation targets — so
 * they wear neutral chart chrome rather than a series colour. The four blocks
 * a reader can actually act on get the categorical hues; that set is validated
 * all-pairs in both modes, so a missing block (which makes two non-consecutive
 * blocks neighbours in the bar) can never produce a confusable pair.
 *
 * `current_passage` and `conversation` are mutually exclusive — the passage
 * either renders whole or parses into turns — so they share a slot.
 */
const BLOCK_SLOT: Record<string, string> = {
  system: 'chrome-1',
  relevant_knowledge: 'series-1',
  previous_events_summary: 'series-2',
  current_passage: 'series-3',
  conversation: 'series-3',
  extra: 'series-4',
  task: 'chrome-2',
}

/** Short names for the legend; the payload's own label is used for anything else. */
const BLOCK_SHORT_LABEL: Record<string, string> = {
  system: 'System',
  relevant_knowledge: 'Knowledge',
  previous_events_summary: 'Previous',
  current_passage: 'Passage',
  conversation: 'Turns',
  extra: 'Extra',
  task: 'Task',
}

export interface SizedRow {
  bytes: number
  tokens: number
}

export function sizeOf(row: SizedRow, unit: ExplainUnit): number {
  return unit === 'bytes' ? row.bytes : row.tokens
}

/** Tokens read as plain counts; bytes get a magnitude suffix. */
export function formatSize(value: number, unit: ExplainUnit): string {
  if (unit === 'tokens') return `${value.toLocaleString()} tok`
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

/** Never round a real contribution down to `0.0%` — it reads as "not there". */
export function formatShare(share: number): string {
  if (share <= 0) return '0%'
  if (share < 0.1) return '<0.1%'
  return `${share.toFixed(1)}%`
}

export function share(value: number, total: number): number {
  return total > 0 ? (value / total) * 100 : 0
}

export function isDerived(component: ExplainComponent): boolean {
  return DERIVED_KINDS.has(component.provenance_kind)
}

/** CSS custom property holding this block's fill, stable per block id. */
export function blockColorVar(blockId: string): string {
  return `--explain-${BLOCK_SLOT[blockId] ?? 'chrome-unknown'}`
}

export function blockShortLabel(block: ExplainBlock): string {
  return BLOCK_SHORT_LABEL[block.id] ?? block.label
}

/** The explanation the payload deliberately omits, so each surface can word it. */
export function cacheNote(cache: ExplainCache): string {
  return cache === 'prefix'
    ? 'Stable across calls — the part a prompt cache can reuse.'
    : 'Changes every call — re-sent in full each time.'
}

export interface BlockSegment {
  id: string
  label: string
  shortLabel: string
  value: number
  /** True share of the total, for the label. */
  share: number
  /** Share after the minimum-width floor, for the rendered geometry. */
  width: number
  cache: ExplainCache
  colorVar: string
}

/**
 * Segments for the single 100%-wide bar, in prompt order.
 *
 * Empty blocks are dropped — a zero-width segment is noise, and the block
 * still gets its own section below. Tiny blocks are floored to
 * `MIN_SEGMENT_WIDTH` and the rest renormalised, so the widths still sum to
 * 100 while a 0.3% block stays visible.
 */
export function blockSegments(report: ExplainReport, unit: ExplainUnit): BlockSegment[] {
  const total = sizeOf(report.totals, unit)
  const blocks = [...report.blocks]
    .sort((a, b) => a.order - b.order)
    .filter((b) => sizeOf(b, unit) > 0)
  if (blocks.length === 0) return []

  const raw = blocks.map((b) => share(sizeOf(b, unit), total))
  const floored = raw.map((r) => r < MIN_SEGMENT_WIDTH)
  const flooredTotal = floored.reduce((sum, isFloor) => sum + (isFloor ? MIN_SEGMENT_WIDTH : 0), 0)
  const restRaw = raw.reduce((sum, r, i) => sum + (floored[i] ? 0 : r), 0)
  const restBudget = Math.max(0, 100 - flooredTotal)

  return blocks.map((block, i) => ({
    id: block.id,
    label: block.label,
    shortLabel: blockShortLabel(block),
    value: sizeOf(block, unit),
    share: raw[i],
    width: floored[i]
      ? MIN_SEGMENT_WIDTH
      : restRaw > 0
        ? (raw[i] / restRaw) * restBudget
        : 0,
    cache: block.cache,
    colorVar: blockColorVar(block.id),
  }))
}

export interface ComponentRow {
  key: string
  id: string
  value: number
  shareOfTotal: number
  shareOfBlock: number
  provenance: string
  provenanceKind: string
  derived: boolean
  kbId: string | null
  /** The ancestor a pin actually lives on — where you would go to change it. */
  pinNode: string | null
  tags: string[]
}

export function componentRows(
  block: ExplainBlock,
  report: ExplainReport,
  unit: ExplainUnit
): ComponentRow[] {
  const total = sizeOf(report.totals, unit)
  const blockTotal = sizeOf(block, unit)
  return [...block.components]
    .sort((a, b) => a.order - b.order)
    .map((component, i) => ({
      key: `${component.id}:${i}`,
      id: component.id,
      value: sizeOf(component, unit),
      shareOfTotal: share(sizeOf(component, unit), total),
      shareOfBlock: share(sizeOf(component, unit), blockTotal),
      provenance: component.provenance,
      provenanceKind: component.provenance_kind,
      derived: isDerived(component),
      kbId: component.detail.kb_id ?? null,
      pinNode: component.detail.pin_node ?? null,
      tags: component.detail.tags ? component.detail.tags.split(',').map((t) => t.trim()).filter(Boolean) : [],
    }))
}

/** Headline for the modal: "Context at /chapter-1 · write" (+ line when pinned to one). */
export function reportHeadline(report: ExplainReport): string {
  const base = `${report.address} · ${report.operator}`
  return report.line !== null ? `${base} · as of line ${report.line}` : base
}

/**
 * How much of the prompt a cache could reuse. The classification is a
 * heuristic today (see the note the modal renders), but the arithmetic over it
 * is exact.
 */
export function prefixShare(report: ExplainReport, unit: ExplainUnit): number {
  const total = sizeOf(report.totals, unit)
  const prefix = report.blocks
    .filter((b) => b.cache === 'prefix')
    .reduce((sum, b) => sum + sizeOf(b, unit), 0)
  return share(prefix, total)
}
