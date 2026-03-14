import { writable } from 'svelte/store'

export const currentAddress = writable<string | null>(null)
export const nodeContent = writable<string>('')

export interface StreamingPreviewState {
  targetNode: string
  text: string
}

export const streamingPreview = writable<StreamingPreviewState | null>(null)
