<script lang="ts">
  import { releaseInfo } from '../../stores/release'
  import { releaseModalOpen } from '../../stores/ui'
  import { fetchLatestRelease } from '../../services/api'
  import { onMount } from 'svelte'

  const installedVersion = $derived($releaseInfo?.installed_version ?? null)
  const requestedVersion = $derived($releaseInfo?.requested_version ?? '')
  const requestPending = $derived(
    !!requestedVersion && !!installedVersion && requestedVersion !== installedVersion
  )

  const updateAvailable = $derived($releaseInfo?.update_available ?? false)

  onMount(async () => {
    try {
      const result = await fetchLatestRelease()
      $releaseInfo = {
        ...($releaseInfo ?? { enabled: false, lens_repo_url: '', requested_version: '', requested_from_commit: '', app_leader: false, dataset_repos: [], installed_version: null, update_available: false }),
        latest_available: result.latest_available,
        update_available: result.update_available,
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
    title="Update requested">
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"
      ><path d="M1.5 6a4.5 4.5 0 1 1 9 0M10.5 3.5v2.5H8"/></svg
    >
  </button>
{:else if updateAvailable}
  <button class="release-indicator release-available" onclick={openModal}
    title="Update available">
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"
      ><path d="M6 10V3M3 6l3-3 3 3"/></svg
    >
  </button>
{/if}

<style>
  .release-indicator {
    background: none;
    border: 1px solid var(--pico-muted-border-color, #444);
    border-radius: 5px;
    cursor: pointer;
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    line-height: 1;
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
