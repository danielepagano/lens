<script lang="ts">
  import { guideModalCommand } from '../../stores/ui'
  import { GUIDES } from '../../commands/guides'
  import { createMarkdownRenderer } from '../../utils/markdown'

  const md = createMarkdownRenderer()

  let dialog: HTMLDialogElement | undefined

  const commandKey = $derived($guideModalCommand)

  const guideMd = $derived(
    commandKey
      ? (GUIDES[commandKey] ?? GUIDES.__general)
      : GUIDES.__general
  )

  const title = $derived(
    commandKey === '__general' ? 'CLI Guide' : (commandKey ?? 'CLI Guide')
  )

  const rendered = $derived(guideMd ? md.render(guideMd) : '')

  $effect(() => {
    if (!dialog) return

    if (commandKey) {
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
    guideModalCommand.set(null)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }
</script>

<dialog
  bind:this={dialog}
  class="guide-dialog"
  onclose={handleClose}
  onclick={handleBackdropClick}
>
  {#if commandKey}
    <article class="guide-article">
      <header class="guide-header">
        <span class="guide-title">Guide: {title.replace(/-/g, ' ')}</span>
        <button type="button" class="guide-close" onclick={handleClose} aria-label="Close guide">✕</button>
      </header>
      <div class="guide-body">
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer output -->
        {@html rendered}
      </div>
    </article>
  {/if}
</dialog>

<style>
  .guide-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .guide-article {
    margin: 0;
    flex-shrink: 0;
    max-width: 800px;
    width: min(90vw, 800px);
  }

  .guide-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
    flex-shrink: 0;
  }

  .guide-title {
    font-weight: 600;
    font-size: 1rem;
    text-transform: capitalize;
  }

  .guide-close {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    color: var(--pico-muted-color);
  }

  .guide-close:hover {
    color: var(--pico-color);
  }

  .guide-body {
    padding: 0.75rem 1rem;
    overflow-y: auto;
    flex: 1;
    font-size: 0.88rem;
    line-height: 1.6;
    background: var(--pico-background-color);
    border-radius: 0 0 var(--pico-border-radius) var(--pico-border-radius);
    max-height: 70vh;
  }

  .guide-body :global(h1),
  .guide-body :global(h2),
  .guide-body :global(h3) {
    margin-top: 1em;
    margin-bottom: 0.5em;
  }

  .guide-body :global(h1:first-child) {
    margin-top: 0;
  }

  .guide-body :global(p) {
    margin-bottom: 0.75em;
  }

  .guide-body :global(code) {
    font-size: 0.82em;
    padding: 0.1em 0.3em;
    background: var(--pico-code-background-color);
    border-radius: 3px;
  }

  .guide-body :global(pre) {
    margin-bottom: 0.75em;
    padding: 0.5rem 0.75rem;
    overflow-x: auto;
    background: var(--pico-code-background-color);
    border-radius: var(--pico-border-radius);
    font-size: 0.82rem;
  }

  .guide-body :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1em;
    font-size: 0.82rem;
  }

  .guide-body :global(th),
  .guide-body :global(td) {
    border: 1px solid var(--pico-muted-border-color);
    padding: 0.3rem 0.5rem;
    text-align: left;
  }

  .guide-body :global(th) {
    background: var(--pico-table-head-background-color, var(--pico-muted-border-color));
    font-weight: 600;
  }

  .guide-body :global(ul),
  .guide-body :global(ol) {
    margin-bottom: 0.75em;
    padding-left: 1.5em;
  }

  .guide-body :global(li) {
    margin-bottom: 0.25em;
  }

  .guide-body :global(strong) {
    font-weight: 600;
  }
</style>
