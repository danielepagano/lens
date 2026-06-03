import { writable } from 'svelte/store'

/** Current `window.location.hash` (including `#`), for reactive URL-driven UI. */
export const urlHash = writable(
  typeof window !== 'undefined' ? window.location.hash : '#'
)

export function syncUrlHashFromWindow(): void {
  urlHash.set(window.location.hash)
}
