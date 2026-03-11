import { writable } from 'svelte/store'

export const activePanel = writable<'document' | 'tree'>('document')
export const treeOpen = writable(false)

export interface CliOutputState {
  output: string
  exitCode: number | null
  streaming: boolean
}
export const cliOutput = writable<CliOutputState | null>(null)

export const treeRefreshTrigger = writable(0)
