<script lang="ts">
  import { releaseModalOpen } from '../../stores/ui'
  import { releaseInfo } from '../../stores/release'
  import { releaseClear, releaseRequest } from '../../services/api'
  let dialog: HTMLDialogElement | undefined

  let updating = $state(false)
  let updateError = $state('')
  let clearing = $state(false)
  let clearError = $state('')

  const rls = $derived($releaseModalOpen ? $releaseInfo : null)
  const installed = $derived(rls?.installed_version ?? null)
  const latest = $derived(rls?.latest_available ?? null)
  const requested = $derived(rls?.requested_version ?? '')
  const hasPendingRequest = $derived(!!requested && !!installed && requested !== installed)

  $effect(() => {
    if (!dialog) return

    if ($releaseModalOpen) {
      if (!dialog.open) {
        dialog.showModal()
      }
      return
    }

    if (dialog.open) {
      dialog.close()
    }
  })

  function handleClose() {
    releaseModalOpen.set(false)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }

  async function handleUpdate() {
    if (!latest) return
    updating = true
    updateError = ''
    try {
      const result = await releaseRequest(latest)
      if (result.status === 'error') {
        updateError = result.detail ?? 'Update request failed'
      } else {
        $releaseInfo = {
          ...($releaseInfo ?? {
            enabled: false, lens_repo_url: '', requested_version: '',
            requested_from_commit: '', app_leader: false, dataset_repos: [],
            installed_version: null, latest_available: null,
          }),
          requested_version: result.requested_version ?? '',
          requested_from_commit: result.requested_from_commit ?? '',
        }
        handleClose()
      }
    } catch (err) {
      updateError = err instanceof Error ? err.message : String(err)
    } finally {
      updating = false
    }
  }

  async function handleClear() {
    clearing = true
    clearError = ''
    try {
      const result = await releaseClear()
      if (result.status === 'error') {
        clearError = result.detail ?? 'Clear failed'
      } else {
        $releaseInfo = {
          ...($releaseInfo ?? {
            enabled: false, lens_repo_url: '', requested_version: '',
            requested_from_commit: '', app_leader: false, dataset_repos: [],
            installed_version: null, latest_available: null,
          }),
          requested_version: '',
          requested_from_commit: '',
        }
        handleClose()
      }
    } catch (err) {
      clearError = err instanceof Error ? err.message : String(err)
    } finally {
      clearing = false
    }
  }

  const currentMsg = $derived(installed ? `v${installed.replace(/^v/, '')}` : '—')
  const latestMsg = $derived(latest ? `v${latest.replace(/^v/, '')}` : '—')
  const newerAvailable = $derived(!!installed && !!latest && latest !== installed)
</script>

<dialog
  bind:this={dialog}
  class="release-dialog"
  onclose={handleClose}
  onclick={handleBackdropClick}
>
  {#if rls}
    <article class="release-article">
      <header class="release-header">
        <strong>Release Update</strong>
        <button type="button" class="release-close" onclick={handleClose}>✕</button>
      </header>
      <div class="release-body">
        <div class="release-row">
          <span class="release-label">Current version</span>
          <span class="release-value">{currentMsg}</span>
        </div>
        <div class="release-row">
          <span class="release-label">Latest available</span>
          <span class="release-value">{latestMsg}</span>
        </div>

        {#if hasPendingRequest}
          <div class="release-pending">
            Update to <strong>{requested}</strong> requested — will apply on next checkpoint
          </div>
          {#if clearError}
            <div class="release-error">{clearError}</div>
          {/if}
          <button
            class="release-clear-btn"
            onclick={handleClear}
            disabled={clearing}
          >
            {clearing ? 'Clearing…' : 'Clear update request'}
          </button>
        {:else if newerAvailable}
          {#if updateError}
            <div class="release-error">{updateError}</div>
          {/if}
          <button
            class="release-update-btn"
            onclick={handleUpdate}
            disabled={updating}
          >
            {updating ? 'Requesting…' : `Update to ${latest}`}
          </button>
        {:else}
          <div class="release-up-to-date">Lens is up to date</div>
        {/if}
      </div>
    </article>
  {/if}
</dialog>

<style>
  .release-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .release-article {
    margin: 0;
    flex-shrink: 0;
    max-width: 420px;
    width: min(90vw, 420px);
  }

  .release-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
    flex-shrink: 0;
  }

  .release-close {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    color: var(--pico-muted-color);
  }

  .release-close:hover {
    color: var(--pico-color);
  }

  .release-body {
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .release-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.9rem;
  }

  .release-label {
    opacity: 0.75;
  }

  .release-value {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .release-pending {
    font-size: 0.82rem;
    opacity: 0.85;
    padding: 0.5rem 0.75rem;
    background: rgba(241, 196, 15, 0.12);
    border-radius: var(--pico-border-radius);
    text-align: center;
  }

  .release-update-btn {
    padding: 0.5rem 1rem;
    background: var(--pico-primary-background, #1e90ff);
    color: var(--pico-primary-inverse, #fff);
    border: none;
    border-radius: var(--pico-border-radius);
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 600;
    text-align: center;
  }

  .release-update-btn:hover:not(:disabled) {
    opacity: 0.9;
  }

  .release-update-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .release-clear-btn {
    padding: 0.5rem 1rem;
    background: transparent;
    color: var(--pico-del-color, #c0392b);
    border: 1px solid var(--pico-del-color, #c0392b);
    border-radius: var(--pico-border-radius);
    cursor: pointer;
    font-size: 0.85rem;
    text-align: center;
  }

  .release-clear-btn:hover:not(:disabled) {
    background: rgba(192, 57, 43, 0.08);
  }

  .release-clear-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .release-error {
    font-size: 0.82rem;
    color: var(--pico-del-color, #c0392b);
    padding: 0.4rem 0.5rem;
    background: rgba(192, 57, 43, 0.1);
    border-radius: var(--pico-border-radius);
  }

  .release-up-to-date {
    font-size: 0.85rem;
    opacity: 0.7;
    text-align: center;
    padding: 0.5rem 0;
  }
</style>
