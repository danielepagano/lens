import { writable } from 'svelte/store'
import type { WorkflowStepSnapshot } from '../services/api'

export const currentAddress = writable<string | null>(null)
export const nodeContent = writable<string>('')

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
}

export const streamingPreview = writable<StreamingPreviewState | null>(null)
