import { writable } from 'svelte/store'
import type { Stats } from '../services/api'
import { updateDatasetCommands } from '../commands/handlers'
import { releaseInfo } from './release'

export type { Stats }
export type { TransactionState } from '../services/api'

export const stats = writable<Stats | null>(null)

export function applyStats(data: Stats): void {
  stats.set(data)

  if (data.release) {
    releaseInfo.update((prev) => ({
      ...(prev ?? {
        enabled: false,
        lens_repo_url: '',
        requested_version: '',
        requested_from_commit: '',
        app_leader: false,
        dataset_repos: [],
        installed_version: null,
        latest_available: null,
      }),
      ...data.release,
      latest_available: prev?.latest_available ?? null,
    }))
  }

  updateDatasetCommands(data)
}
