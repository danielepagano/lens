<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { deleteMountPath } from '../../services/api'
  import { mediaRemoveRequest, transactionResult, mountCacheRefreshTrigger } from '../../stores/ui'

  let removing = false
  let error: string | null = null

  $: isOpen = $mediaRemoveRequest !== null
  $: path = $mediaRemoveRequest?.path ?? ''

  $: if (isOpen) {
    removing = false
    error = null
  }

  function handleClose() {
    mediaRemoveRequest.set(null)
  }

  async function handleConfirm() {
    removing = true
    error = null
    try {
      await deleteMountPath(path)
      mountCacheRefreshTrigger.update((n) => n + 1)
      mediaRemoveRequest.set(null)
      transactionResult.set({ title: 'Removed', message: `Removed: ${path}`, theme: 'info' })
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    } finally {
      removing = false
    }
  }
</script>

<OutputPanel
  title="Confirm remove"
  theme="error"
  open={isOpen}
  streaming={false}
  autoClose={false}
  hasContent={true}
  showCancel={false}
  on:close={handleClose}
>
  <div slot="content" class="media-remove-panel">
    <p class="media-remove-path"><code>{path}</code></p>
    <p class="media-remove-warning">This cannot be undone.</p>

    {#if error}
      <p class="media-remove-error" role="alert">{error}</p>
    {/if}

    <div class="media-remove-actions">
      <button
        type="button"
        class="media-remove-cancel"
        disabled={removing}
        on:click={handleClose}
      >
        Cancel
      </button>
      <button
        type="button"
        class="media-remove-confirm"
        disabled={removing}
        on:click={handleConfirm}
      >
        {removing ? 'Removing…' : 'Remove'}
      </button>
    </div>
  </div>
</OutputPanel>

<style>
  .media-remove-panel {
    padding: 0.75rem 1rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .media-remove-path {
    margin: 0;
    word-break: break-all;
  }

  .media-remove-warning {
    margin: 0;
    font-size: 0.85rem;
    opacity: 0.7;
  }

  .media-remove-error {
    margin: 0;
    font-size: 0.85rem;
    color: var(--pico-del-color, #e05c5c);
  }

  .media-remove-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.25rem;
  }

  .media-remove-cancel {
    flex: 1;
    padding: 0.65rem;
    min-height: 44px;
    cursor: pointer;
  }

  .media-remove-confirm {
    flex: 1;
    padding: 0.65rem;
    min-height: 44px;
    cursor: pointer;
    background: var(--pico-del-color, #e05c5c);
    border-color: var(--pico-del-color, #e05c5c);
    color: #fff;
  }

  .media-remove-confirm:disabled,
  .media-remove-cancel:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
