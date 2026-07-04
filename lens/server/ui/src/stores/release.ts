import { writable } from 'svelte/store'

export interface ReleaseInfo {
  enabled: boolean
  lens_repo_url: string
  requested_version: string
  requested_from_commit: string
  app_leader: boolean
  dataset_repos: { name: string; git_url: string; ref: string }[]
  installed_version: string | null
  latest_available: string | null
  update_available: boolean
}

export const releaseInfo = writable<ReleaseInfo | null>(null)
