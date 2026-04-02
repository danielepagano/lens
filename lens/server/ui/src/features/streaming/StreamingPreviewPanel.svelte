<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { streamingPreview } from '../../stores/document'
  import { cancelStream } from '../../services/api'

  $: isOpen = $streamingPreview !== null
  $: isWaiting = $streamingPreview !== null && $streamingPreview.text === ''
  $: waitLabel =
    $streamingPreview?.statusLine ?? (isWaiting ? 'Waiting…' : 'Streaming…')

  async function handleCancel() {
    try {
      await cancelStream()
    } catch (e) {
      console.error('Cancel failed:', e)
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!isOpen) return
    if (e.key === 'Escape') {
      e.preventDefault()
      handleCancel()
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleKeydown)
  })

  onDestroy(() => {
    window.removeEventListener('keydown', handleKeydown)
  })
</script>

{#if isOpen}
  <div class="streaming-panel" data-testid="streaming-panel">
    <span class="streaming-label">{waitLabel}</span>
    <button
      type="button"
      class="streaming-cancel-btn"
      on:click={handleCancel}
      aria-label="Cancel streaming"
    >
      Cancel
    </button>
  </div>
{/if}
