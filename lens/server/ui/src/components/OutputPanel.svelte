<script lang="ts">
  import type { Snippet } from 'svelte'
  import CloseIcon from './icons/CloseIcon.svelte'

  type OutputPanelTheme = 'cli' | 'error' | 'command'

  type Props = {
    title?: string
    theme?: OutputPanelTheme
    open?: boolean
    streaming?: boolean
    autoClose?: boolean
    hasContent?: boolean | null
    showCancel?: boolean
    onClose?: () => void
    onCancel?: () => void
    content?: Snippet
  }

  let {
    title = '',
    theme = 'cli',
    open = false,
    streaming = false,
    autoClose = false,
    hasContent = null,
    showCancel = false,
    onClose,
    onCancel,
    content
  }: Props = $props()

  function handleEscape(e: KeyboardEvent) {
    if (!open) return
    if (e.key !== 'Escape') return
    if (streaming && showCancel) {
      dispatchCancel()
    } else {
      dispatchClose()
    }
  }

  function dispatchClose() {
    onClose?.()
  }

  function dispatchCancel() {
    onCancel?.()
  }
</script>

<svelte:window onkeydown={handleEscape} />

{#if open}
  <div
    class={[
      'cli-output-panel',
      {
        error: theme === 'error',
        command: theme === 'command'
      }
    ]}
    data-testid="cli-output-panel"
  >
    {#if autoClose && !streaming}
      <span
        aria-hidden="true"
        class="cli-output-autoclose-sentinel"
        onanimationend={dispatchClose}
      ></span>
    {/if}
    <div class="cli-output-header">
      <span class="cli-output-title">{title}</span>
      <div class="cli-output-actions">
        {#if showCancel}
          <button
            type="button"
            class="cli-cancel-btn"
            onclick={dispatchCancel}
            aria-label="Cancel"
          >
            Cancel
          </button>
        {/if}
        <button
          type="button"
          class="cli-close-btn"
          onclick={dispatchClose}
          aria-label="Close"
        >
          <CloseIcon size={18} />
        </button>
      </div>
    </div>
    {#if hasContent === null ? true : hasContent}
      {@render content?.()}
    {/if}
  </div>
{/if}

<style>
  .cli-output-autoclose-sentinel {
    display: block;
    inline-size: 0;
    block-size: 0;
    overflow: hidden;
    animation: cli-output-autoclose 5s linear 1;
  }

  @keyframes cli-output-autoclose {
    from {
      opacity: 0;
    }

    to {
      opacity: 0;
    }
  }
</style>

