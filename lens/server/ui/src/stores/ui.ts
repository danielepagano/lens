import { writable } from 'svelte/store'

export type AppMode = 'narrative' | 'kb'

export const appMode = writable<AppMode>('narrative')
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
}

export const transactionResult = writable<TransactionResultState | null>(null)

// KB state
export const selectedKbId = writable<string | null>(null)

export interface KbFilterState {
  type: string
  tags: string[]
}

export const kbFilters = writable<KbFilterState>({ type: '', tags: [] })
export const kbTypes = writable<string[]>([])
