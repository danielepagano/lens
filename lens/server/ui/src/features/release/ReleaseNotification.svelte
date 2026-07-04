<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseInfo } from '../../stores/release'
  import { releaseModalOpen } from '../../stores/ui'
  import { fetchLatestRelease } from '../../services/api'
  import { onMount } from 'svelte'

  const rls = $derived($stats?.release)
  const installedVersion = $derived(rls?.installed_version ?? null)
  const requestedVersion = $derived(rls?.requested_version ?? '')
  const requestPending = $derived(
    !!requestedVersion && !!installedVersion && requestedVersion !== installedVersion
  )

  const latestAvailable = $derived($releaseInfo?.latest_available ?? null)
  const updateAvailable = $derived(
    !!installedVersion && !!latestAvailable && latestAvailable !== installedVersion
  )

  onMount(async () => {
    try {
      const result = await fetchLatestRelease()
      if (result.latest_available) {
        $releaseInfo = {
          ...($releaseInfo ?? { enabled: false, lens_repo_url: '', requested_version: '', requested_from_commit: '', app_leader: false, dataset_repos: [], installed_version: null }),
          latest_available: result.latest_available,
        }
      }
    } catch {
      // silently ignore
    }
  })

  function openModal() {
    releaseModalOpen.set(true)
  }
</script>

{#if requestPending}
  <button class="release-indicator release-requested" onclick={openModal} data-testid="release-requested"
    >Update requested</button
  >
{:else if updateAvailable}
  <button class="release-indicator release-available" onclick={openModal}
    >v{latestAvailable?.replace(/^v/, '')} available</button
  >
{/if}

<style>
  .release-indicator {
    background: none;
    border: 1px solid var(--pico-muted-border-color, #444);
    border-radius: 6px;
    padding: 0.15rem 0.45rem;
    cursor: pointer;
    margin-bottom: 0px;
    font-size: 0.72rem;
    color: inherit;
    flex-shrink: 0;
    white-space: nowrap;
    line-height: 1.4;
  }

  .release-indicator:hover {
    background: var(--pico-secondary-hover-background);
  }

  .release-requested {
    border-color: var(--pico-primary-background, #1e90ff);
    color: var(--pico-primary-background, #1e90ff);
  }

  .release-available {
    border-color: var(--pico-del-color, #e84855);
    color: var(--pico-del-color, #e84855);
  }
</style>
