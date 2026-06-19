import { writable } from 'svelte/store'
import type {
  MediaGenerateParams,
  MediaStartEvent,
} from '../services/api'

export const kbPanelOpen = writable(false)
export const activePanel = writable<'document' | 'tree'>('document')
export const treeOpen = writable(false)

export interface CliOutputState {
  output: string
  exitCode: number | null
  streaming: boolean
}
export const cliOutput = writable<CliOutputState | null>(null)

export const cliHistory = writable<string[]>([])
/** `-1` means not currently browsing history. */
export const cliHistoryIndex = writable(-1)

export const treeRefreshTrigger = writable(0)

export interface TransactionResultState {
  title: string
  message: string
  theme?: 'error' | 'info'
}

export const transactionResult = writable<TransactionResultState | null>(null)

// KB state
export const selectedKbId = writable<string | null>(null)
export const kbDetailId = writable<string | null>(null)

// Line pick mode: active when CLI is waiting for a line number input
export interface LinePickState {
  address: string
  /** Set when picking the end line (second pick) — the already-picked start line. */
  startLine?: number
  /** Which operator's validation rules to apply for end-line filtering. */
  operatorMode?: 'edit' | 'attach'
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

/** Increment to request any visible CodeMirror instance to scroll to the latest lines (line pick, inline edit). */
export const scrollCodeMirrorToBottom = writable(0)

export interface MediaCarouselRequest {
  mode: 'attach' | 'manage' | 'replace'
  dir: string
  attachAddress?: string
  attachLine?: number
  /** 1-based disk line of a standalone image markdown row (`edit --replace`). */
  replaceImageLine?: number
}
export const mediaCarouselRequest = writable<MediaCarouselRequest | null>(null)

export interface PreviewItem {
  index: number
  ext: string
  b64: string
  src: string
  saved: boolean
  saving: boolean
  savedPath?: string
  resultSeq?: number
}

export interface MediaPreviewState {
  start: MediaStartEvent | null
  items: PreviewItem[]
  batchSeq: number | null
  status: 'streaming' | 'done' | 'error'
  error?: string
  selectedIndex: number
  rawParams: MediaGenerateParams
  /** Client clock when this preview session began (for elapsed UI). */
  generationStartedAt: number
}

export const mediaPreviewSession = writable<MediaPreviewState | null>(null)
export const cliInputRequest = writable<string | null>(null)

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
/** Increment to request InlineEditView to confirm (OK) the current edit. */
export const inlineEditConfirmTrigger = writable(0)
/** Increment to request InlineEditView to cancel the current edit. */
export const inlineEditCancelTrigger = writable(0)

export interface KbDiffRequest {
  kbId: string
  proposed: string
  current: string
}
export const kbDiffRequest = writable<KbDiffRequest | null>(null)

/** True when a CodeMirror editor has focus.  Used on mobile to hide the CLI
 *  bottom bar so the virtual keyboard doesn't waste screen space. */
export const editorFocused = writable(false)
