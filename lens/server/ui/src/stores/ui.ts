import { writable } from 'svelte/store'

export const kbPanelOpen = writable(false)
export const activePanel = writable<'document' | 'tree'>('document')
export const treeOpen = writable(false)

export interface CliOutputState {
  output: string
  exitCode: number | null
  streaming: boolean
}
export const cliOutput = writable<CliOutputState | null>(null)

export const treeRefreshTrigger = writable(0)

export interface TransactionResultState {
  title: string
  message: string
  theme?: 'error' | 'info'
}

export const transactionResult = writable<TransactionResultState | null>(null)

// KB state
export const selectedKbId = writable<string | null>(null)

// Line pick mode: active when CLI is waiting for a line number input
export interface LinePickState {
  address: string
  /** Set when picking the end line (second pick) — the already-picked start line. */
  startLine?: number
  /** Which operator's validation rules to apply for end-line filtering. */
  operatorMode?: 'edit' | 'collate' | 'attach'
}
export const linePickMode = writable<LinePickState | null>(null)
export const linePickSelection = writable<number | null>(null)

export interface KbFilterState {
  type: string
  tags: string[]
}

export const kbFilters = writable<KbFilterState>({ type: '', tags: [] })

/** Increment to request the main content area to scroll to bottom (e.g. when opening cursor node from tree). */
export const scrollContentToBottom = writable(0)

export interface MediaUploadRequest {
  dir: string
}
export const mediaUploadRequest = writable<MediaUploadRequest | null>(null)

export interface MediaRemoveRequest {
  path: string
}
export const mediaRemoveRequest = writable<MediaRemoveRequest | null>(null)

export interface MediaPreviewRequest {
  path: string
}
export const mediaPreviewRequest = writable<MediaPreviewRequest | null>(null)

/** Increment to force the mount directory autocomplete cache to reload. */
export const mountCacheRefreshTrigger = writable(0)

// Inline edit mode: active when the user entered `edit --replace` with no prompt text,
// or `write --manual` with no text (appendMode).
export interface InlineEditState {
  address: string
  startLine: number
  endLine: number
  originalText: string
  /** Count of lines strictly after `endLine` in the original document (unchanged suffix). */
  linesAfterSelection: number
  /** When true: append new text at end of node rather than replacing a range. */
  appendMode?: boolean
}
export const inlineEditMode = writable<InlineEditState | null>(null)
export const inlineEditResult = writable<string | null>(null)

export interface KbDiffRequest {
  kbId: string
  proposed: string
  current: string
}
export const kbDiffRequest = writable<KbDiffRequest | null>(null)
