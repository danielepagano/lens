import { writable } from 'svelte/store'

export const activeNarrative = writable<string | null>(null)
export const availableNarratives = writable<string[]>([])
export const cursor = writable<string | null>(null)
