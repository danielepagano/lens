import { writable } from 'svelte/store'

export const activePanel = writable<'document' | 'tree'>('document')
export const treeOpen = writable(false)
