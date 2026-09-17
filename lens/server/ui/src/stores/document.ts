import { writable } from 'svelte/store'
import type { NodeData, PendingKb, WorkflowStepSnapshot } from '../services/api'

export const currentAddress = writable<string | null>(null)
export const nodeContent = writable<string>('')
/**
 * Pending KB proposals for the node currently in `nodeContent`.
 *
 * The node route serves them only for the cursor, so this goes null the moment
 * you navigate away and comes back when you navigate back — which is exactly
 * how the layer itself behaves. Set it wherever `nodeContent` is set; use
 * `applyNodeData` rather than doing the two by hand.
 */
export const pendingKb = writable<PendingKb | null>(null)

/** Both halves of a fetched node, so neither can be refreshed without the other. */
export function applyNodeData(data: NodeData): void {
  nodeContent.set(data.content)
  pendingKb.set(data.pending_kb ?? null)
}

/** Clear both: no node in view. */
export function clearNodeData(): void {
  nodeContent.set('')
  pendingKb.set(null)
}

export interface StreamingPreviewState {
  targetNode: string
  text: string
  /** Shown instead of generic “Waiting…” while no tokens yet */
  statusLine?: string
  steps: WorkflowStepSnapshot[]
  activeStepId?: string
  /** Step waiting for retry/skip user action */
  pausedStepId?: string
  /** Keep panel visible after stream ends when workflow had failures */
  sticky?: boolean
  /** Client clock when the current step's generation began (for elapsed/rate display) */
  streamStartedAt?: number
  /** Cumulative reasoning/tool-call-argument bytes for the current step (not in `text`) */
  hiddenBytes?: number
  /** Highest LLM round-trip number seen for the current step (1 = single round) */
  turnCount?: number
}

export const streamingPreview = writable<StreamingPreviewState | null>(null)
