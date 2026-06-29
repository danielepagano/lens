<script lang="ts">
  import { tick } from 'svelte'

  type Props = {
    open: boolean
    history: string[]
    onSelect: (entry: string) => void
    onClear: () => void
    onClose: () => void
  }

  let { open, history, onSelect, onClear, onClose }: Props = $props()

  let drawerEl: HTMLDivElement | null = $state(null)

  $effect(() => {
    if (open) {
      void tick().then(() => {
        if (drawerEl) drawerEl.scrollTop = drawerEl.scrollHeight
      })
    }
  })

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') onClose()
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div
    bind:this={drawerEl}
    class="cli-history-drawer"
    role="listbox"
    aria-label="Command history"
  >
    {#each history as entry, i (i)}
      <button
        type="button"
        class="cli-history-entry"
        role="option"
        aria-selected={false}
        onclick={() => { onSelect(entry); onClose() }}
      >
        <span class="cli-history-text">{entry}</span>
      </button>
    {/each}
    <button
      type="button"
      class="cli-history-clear"
      onclick={() => { onClear(); onClose() }}
    >
      Clear input
    </button>
  </div>
{/if}

<style>
  .cli-history-drawer {
    position: absolute;
    bottom: 100%;
    left: 0;
    right: 0;
    max-height: 50vh;
    overflow-y: auto;
    background: var(--pico-background-color);
    border: 1px solid var(--pico-muted-border-color);
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    z-index: 260;
  }

  .cli-history-entry,
  .cli-history-clear {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: 0.4rem 0.75rem;
    margin-bottom: 0;
    font-size: 12px;
    font-family: ui-monospace, monospace;
    cursor: pointer;
    color: var(--pico-color);
    overflow: hidden;
  }

  .cli-history-entry:hover,
  .cli-history-clear:hover {
    background: var(--pico-muted-border-color);
  }

  .cli-history-text {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .cli-history-clear {
    color: var(--pico-muted-color);
    border-top: 1px solid var(--pico-muted-border-color);
    font-style: italic;
    text-align: right;
    font-size: smaller;
  }
</style>
