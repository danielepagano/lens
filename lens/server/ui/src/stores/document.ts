import { writable } from 'svelte/store'

export const currentAddress = writable<string | null>(null)
export const nodeContent = writable<string>('')
