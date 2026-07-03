<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseModalOpen } from '../../stores/ui'
  import { releaseApprove } from '../../services/api'

  let dialog: HTMLDialogElement | undefined
  let approving = $state(false)
  let error = $state<string | null>(null)

  const rls = $derived($stats?.release)
  const approved = $derived(rls?.gated_update_approved ?? false)
  const targetVersion = $derived(rls?.gated_update_target_version ?? '')
  const repoUrl = $derived(rls?.lens_repo_url ?? '')
  const installedVersion = $derived(rls?.installed_version ?? '')
  const autoUpdate = $derived(rls?.auto_update ?? '')

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

  async function approve() {
    approving = true
    error = null
    try {
      await releaseApprove()
    } catch (e) {
      error = String(e)
    } finally {
      approving = false
    }
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
    {:else if approved}
      <p class="release-approved-text">Approved — awaiting deployment by CI.</p>
      <p class="release-meta">
        Target: <strong>{targetVersion}</strong>
      </p>
      <div class="release-actions">
        <button type="button" class="release-btn release-close-action-btn" onclick={handleClose}>Close</button>
      </div>
    {:else}
      <p>A new Lens version is available for review:</p>

      <div class="release-info">
        <span class="release-label">Target version</span>
        <span class="release-value">
          <a href={releaseUrl(targetVersion)} target="_blank" rel="noopener noreferrer">
            {targetVersion} ↗
          </a>
        </span>
      </div>

      <div class="release-info">
        <span class="release-label">Currently installed</span>
        <span class="release-value">{installedVersion || '(desktop / unknown)'}</span>
      </div>

      {#if autoUpdate}
        <div class="release-info">
          <span class="release-label">Auto-update policy</span>
          <span class="release-value">{autoUpdate}</span>
        </div>
      {/if}

      {#if error}
        <p class="release-error">{error}</p>
      {/if}

      <div class="release-actions">
        <button
          type="button"
          class="release-btn release-approve-btn"
          onclick={approve}
          disabled={approving}
        >{approving ? 'Approving…' : 'Approve'}</button>
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

  .release-value a {
    color: var(--pico-primary);
    text-decoration: none;
  }

  .release-value a:hover {
    text-decoration: underline;
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

  .release-approve-btn {
    background: var(--pico-ins-color, #2ea043);
    color: #fff;
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

  .release-approved-text {
    color: var(--pico-ins-color, #2ea043);
    font-weight: 600;
    font-size: 1rem;
  }

  .release-meta {
    margin-top: 0.6rem;
    font-size: 0.9rem;
    opacity: 0.85;
  }

  .release-error {
    color: var(--pico-del-color, #da3633);
    font-size: 0.85rem;
    margin-top: 0.6rem;
  }
</style>
