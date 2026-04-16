import { writable } from 'svelte/store'

export const currentProject = writable<string | null>(null)
export const availableProjects = writable<string[]>([])
