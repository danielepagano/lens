<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import CloseIcon from './icons/CloseIcon.svelte'

  type OutputPanelTheme = 'cli' | 'error' | 'command'

  export let title = ''
  export let theme: OutputPanelTheme = 'cli'
  export let open = false
  export let streaming = false
  export let autoClose = false
  export let hasContent: boolean | null = null
  export let showCancel = false

  const dispatch = createEventDispatcher<{
    close: void
    cancel: void
  }>()

  let autoCloseTimeout: ReturnType<typeof setTimeout> | null = null

  function handleEscape(e: KeyboardEvent) {
    if (!open) return
    if (e.key !== 'Escape') return
    if (streaming && showCancel) {
      dispatch('cancel')
    } else {
      dispatch('close')
    }
  }

  function clearAutoCloseTimeout() {
    if (autoCloseTimeout !== null) {
      clearTimeout(autoCloseTimeout)
      autoCloseTimeout = null
    }
  }

  $: {
    clearAutoCloseTimeout()
    if (open && autoClose && !streaming) {
      autoCloseTimeout = setTimeout(() => {
        if (open) {
          dispatch('close')
        }
      }, 5000)
    }
  }
</script>

<svelte:window on:keydown={handleEscape} />

{#if open}
  <div
    class="cli-output-panel"
    class:error={theme === 'error'}
    class:command={theme === 'command'}
    data-testid="cli-output-panel"
  >
    <div class="cli-output-header">
      <span class="cli-output-title">{title}</span>
      <div class="cli-output-actions">
        {#if showCancel}
          <button
            type="button"
            class="cli-cancel-btn"
            on:click={() => dispatch('cancel')}
            aria-label="Cancel"
          >
            Cancel
          </button>
        {/if}
        <button
          type="button"
          class="cli-close-btn"
          on:click={() => dispatch('close')}
          aria-label="Close"
        >
          <CloseIcon size={18} />
        </button>
      </div>
    </div>
    {#if hasContent === null ? true : hasContent}
      <slot name="content" />
    {/if}
  </div>
{/if}

