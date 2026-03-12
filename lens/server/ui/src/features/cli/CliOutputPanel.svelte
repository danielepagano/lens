<script lang="ts">
  import { get } from 'svelte/store'
  import { cancelCliRun } from '../../services/api'
  import { cliOutput } from '../../stores/ui'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'

  async function cancel() {
    try {
      await cancelCliRun()
    } catch (e) {
      console.error('Cancel failed:', e)
    }
  }

  function close() {
    cliOutput.set(null)
  }

  function handleEscape(e: KeyboardEvent) {
    if (e.key !== 'Escape') return
    const out = get(cliOutput)
    if (!out) return
    if (out.streaming) {
      cancel()
    } else {
      close()
    }
  }
</script>

<svelte:window on:keydown={handleEscape} />

{#if $cliOutput}
  <div
    class="cli-output-panel"
    class:error={$cliOutput.exitCode !== null && $cliOutput.exitCode !== 0}
    data-testid="cli-output-panel"
  >
    <div class="cli-output-header">
      <span class="cli-output-title">CLI output</span>
      <div class="cli-output-actions">
        {#if $cliOutput.streaming}
          <button
            type="button"
            class="cli-cancel-btn"
            on:click={cancel}
            aria-label="Cancel"
          >
            Cancel
          </button>
        {/if}
        <button
          type="button"
          class="cli-close-btn"
          on:click={close}
          aria-label="Close"
        >
          <CloseIcon size={18} />
        </button>
      </div>
    </div>
    <pre class="cli-output-content">{$cliOutput.output || ' '}</pre>
  </div>
{/if}
