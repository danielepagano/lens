<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseModalOpen } from '../../stores/ui'
  import { releaseApprove, releaseReject, releasePolicy } from '../../services/api'

  let dialog: HTMLDialogElement | undefined
  let actionInProgress = $state(false)
  let approvalBusy = $state(false)
  let rejectBusy = $state(false)
  let policyBusy = $state(false)
  let error = $state<string | null>(null)
  let selectedAutoUpdate = $state('')
  let requestedVersionInput = $state('')

  const rls = $derived($stats?.release)
  const pending = $derived(rls?.gated_update_pending ?? false)
  const approved = $derived(rls?.gated_update_approved ?? false)
  const targetVersion = $derived(rls?.gated_update_target_version ?? '')
  const repoUrl = $derived(rls?.lens_repo_url ?? '')
  const installedVersion = $derived(rls?.installed_version ?? '')
  const latestAvailable = $derived(rls?.latest_available ?? '')
  const autoUpdate = $derived(rls?.auto_update ?? 'off')

  function releaseUrl(ver: string): string {
    const base = repoUrl.replace(/\.git$/, '')
    return `${base}/releases/tag/${ver}`
  }

  $effect(() => {
    if (!dialog) return
    if ($releaseModalOpen) {
      dialog.showModal()
      selectedAutoUpdate = autoUpdate
      requestedVersionInput = rls?.requested_version ?? ''
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

  function resetBusy() {
    approvalBusy = false
    rejectBusy = false
    policyBusy = false
    actionInProgress = false
  }

  async function approve() {
    approvalBusy = true
    actionInProgress = true
    error = null
    try {
      await releaseApprove()
    } catch (e) {
      error = String(e)
    } finally {
      resetBusy()
    }
  }

  async function reject() {
    rejectBusy = true
    actionInProgress = true
    error = null
    try {
      await releaseReject()
    } catch (e) {
      error = String(e)
    } finally {
      resetBusy()
    }
  }

  async function savePolicy() {
    policyBusy = true
    actionInProgress = true
    error = null
    try {
      const body: { auto_update?: string; requested_version?: string } = {}
      if (selectedAutoUpdate !== autoUpdate) {
        body.auto_update = selectedAutoUpdate
      }
      if (requestedVersionInput !== (rls?.requested_version ?? '')) {
        body.requested_version = requestedVersionInput
      }
      if (Object.keys(body).length > 0) {
        await releasePolicy(body)
      }
    } catch (e) {
      error = String(e)
    } finally {
      resetBusy()
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
    {:else if pending && !approved}
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

      {#if error}
        <p class="release-error">{error}</p>
      {/if}

      <div class="release-actions">
        <button
          type="button"
          class="release-btn release-approve-btn"
          onclick={approve}
          disabled={actionInProgress}
        >{approvalBusy ? 'Approving…' : 'Approve'}</button>
        <button
          type="button"
          class="release-btn release-reject-btn"
          onclick={reject}
          disabled={actionInProgress}
        >{rejectBusy ? 'Rejecting…' : 'Reject'}</button>
        <button type="button" class="release-btn release-close-action-btn" onclick={handleClose}>Close</button>
      </div>
    {:else}
      <p class="release-section-label">Release settings</p>

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

      <label class="release-field">
        <span class="release-field-label">Auto-update policy</span>
        <select bind:value={selectedAutoUpdate} class="release-select">
          <option value="off">Off</option>
          <option value="minor">Minor</option>
          <option value="major">Major</option>
        </select>
      </label>

      <label class="release-field">
        <span class="release-field-label">Requested version</span>
        <input
          type="text"
          bind:value={requestedVersionInput}
          placeholder="e.g. v2.1.0"
          class="release-input"
        />
      </label>

      {#if error}
        <p class="release-error">{error}</p>
      {/if}

      <div class="release-actions">
        <button
          type="button"
          class="release-btn release-primary-btn"
          onclick={savePolicy}
          disabled={actionInProgress}
        >{policyBusy ? 'Saving…' : 'Save settings'}</button>
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

  .release-reject-btn {
    background: var(--pico-del-color, #da3633);
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

  .release-primary-btn {
    background: var(--pico-primary, #2ea043);
    color: #fff;
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

  .release-section-label {
    font-weight: 600;
    margin-bottom: 0.6rem;
    font-size: 0.95rem;
    opacity: 0.85;
  }

  .release-field {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin-top: 0.8rem;
  }

  .release-field-label {
    font-size: 0.85rem;
    opacity: 0.7;
  }

  .release-select,
  .release-input {
    padding: 0.4rem 0.5rem;
    border: 1px solid var(--pico-muted-border-color, #555);
    border-radius: 6px;
    background: var(--pico-card-background-color, #1a1a2e);
    color: inherit;
    font-size: 0.9rem;
  }
</style>