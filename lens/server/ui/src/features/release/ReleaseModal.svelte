<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseModalOpen } from '../../stores/ui'

  let dialog: HTMLDialogElement | undefined
  let error = $state<string | null>(null)

  const rls = $derived($stats?.release)
  const repoUrl = $derived(rls?.lens_repo_url ?? '')
  const installedVersion = $derived(rls?.installed_version ?? '')
  const latestAvailable = $derived(rls?.latest_available ?? '')

  function releaseUrl(ver: string): string {
    const base = repoUrl.replace(/\.git$/, '')
    return `${base}/releases/tag/${ver}`
  }

  $effect(() => {
    if (!dialog) return
    if ($releaseModalOpen) {
      dialog.showModal()
    } else {
      if (dialog.open) dialog.close()
    }
  })

  function handleClose() {
    releaseModalOpen.set(false)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }
</script>

<dialog
  bind:this={dialog}
  onclose={handleClose}
  onclick={handleBackdropClick}
  class="release-dialog"
>
  <article class="release-article">
    <header class="release-header">
      <strong>Release Update</strong>
      <button type="button" class="release-close-btn" onclick={handleClose}>✕</button>
    </header>

    {#if !rls || !rls.enabled}
      <p>Release system is not enabled.</p>
    {:else}
      <div class="release-info">
        <span class="release-label">Installed version</span>
        <span class="release-value">{installedVersion || '(desktop / unknown)'}</span>
      </div>

      {#if latestAvailable}
        <div class="release-info">
          <span class="release-label">Latest available</span>
          <span class="release-value">{latestAvailable}</span>
        </div>
      {/if}

      {#if latestAvailable && latestAvailable !== installedVersion}
        <p class="release-upgrade-msg">
          <a href={releaseUrl(latestAvailable)} target="_blank" rel="noopener noreferrer">
            {latestAvailable} ↗
          </a>
          is available — deploy via CI to upgrade.
        </p>
      {/if}

      {#if error}
        <p class="release-error">{error}</p>
      {/if}

      <div class="release-actions">
        <button type="button" class="release-btn release-close-action-btn" onclick={handleClose}>Close</button>
      </div>
    {/if}
  </article>
</dialog>

<style>
  .release-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .release-dialog {
    max-width: 28rem;
    width: 90vw;
    border: none;
    border-radius: 10px;
    padding: 0;
    background: var(--pico-card-background-color, #1a1a2e);
    color: var(--pico-color, #ddd);
    overflow: visible;
  }

  .release-article {
    padding: 1.2rem;
    background: none;
    box-shadow: none;
  }

  .release-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 1.1rem;
    margin-bottom: 1rem;
  }

  .release-close-btn {
    background: none;
    border: none;
    font-size: 1.2rem;
    cursor: pointer;
    color: inherit;
    padding: 0.2rem;
    line-height: 1;
  }

  .release-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.45rem 0;
    border-bottom: 1px solid var(--pico-muted-border-color, #333);
    font-size: 0.9rem;
  }

  .release-label {
    opacity: 0.7;
  }

  .release-value {
    font-weight: 500;
  }

  .release-actions {
    display: flex;
    gap: 0.6rem;
    margin-top: 1.2rem;
    flex-wrap: wrap;
  }

  .release-btn {
    flex: 1;
    min-width: 6rem;
    padding: 0.5rem 0.8rem;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
    font-size: 0.9rem;
  }

  .release-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .release-close-action-btn {
    background: transparent;
    border: 1px solid var(--pico-muted-border-color, #555);
    color: inherit;
    flex: 0.6;
    min-width: 5rem;
    padding: 0.5rem 0.8rem;
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
    font-size: 0.9rem;
  }

  .release-error {
    color: var(--pico-del-color, #da3633);
    font-size: 0.85rem;
    margin-top: 0.6rem;
  }

  .release-upgrade-msg {
    margin-top: 0.8rem;
    font-size: 0.9rem;
  }

  .release-upgrade-msg a {
    color: var(--pico-primary);
    text-decoration: none;
    font-weight: 600;
  }

  .release-upgrade-msg a:hover {
    text-decoration: underline;
  }
</style>
