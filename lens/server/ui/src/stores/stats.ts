import { writable } from 'svelte/store'
import type { Stats } from '../services/api'
import { updateDatasetCommands } from '../commands/handlers'

export type { Stats }
export type { TransactionState } from '../services/api'

export const stats = writable<Stats | null>(null)

export function applyStats(data: Stats): void {
  stats.set(data)
  updateDatasetCommands(data.current_datasets ?? [])
}
