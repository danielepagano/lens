<script lang="ts">
  import { kbDiffRequest } from '../../stores/ui'
  import { computeLineDiff } from '../../utils/lineDiff'

  let dialog: HTMLDialogElement | undefined

  const req = $derived($kbDiffRequest)
  const diffLines = $derived(req ? computeLineDiff(req.current, req.proposed) : [])

  $effect(() => {
    if (!dialog) return

    if (req) {
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
    kbDiffRequest.set(null)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }
</script>

<dialog
  bind:this={dialog}
  class="kb-diff-dialog"
  onclose={handleClose}
  onclick={handleBackdropClick}
>
  {#if req}
    <article class="kb-diff-article">
      <header class="kb-diff-header">
        <strong>KB Diff: {req.kbId}</strong>
        <button type="button" class="kb-diff-close" onclick={handleClose}>✕</button>
      </header>
      <div class="kb-diff-legend">
        <span class="kb-diff-legend-del">— current</span>
        <span class="kb-diff-legend-ins">+ proposed</span>
      </div>
      <pre class="kb-diff-body">{#each diffLines as line, i (i)}<span
          class="kb-diff-line kb-diff-line--{line.kind}"
        >{line.kind === 'insert' ? '+' : line.kind === 'delete' ? '-' : ' '} {line.text}
</span>{/each}</pre>
    </article>
  {/if}
</dialog>

<style>
  .kb-diff-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .kb-diff-article {
    margin: 0;
    flex-shrink: 0;
  }

  .kb-diff-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
    flex-shrink: 0;
  }

  .kb-diff-close {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    color: var(--pico-muted-color);
  }

  .kb-diff-close:hover {
    color: var(--pico-color);
  }

  .kb-diff-legend {
    display: flex;
    gap: 1rem;
    padding: 0.4rem 1rem;
    font-size: 0.8rem;
    flex-shrink: 0;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }

  .kb-diff-legend-del {
    color: var(--pico-del-color, #c0392b);
  }

  .kb-diff-legend-ins {
    color: var(--pico-ins-color, #27ae60);
  }

  .kb-diff-body {
    margin: 0;
    padding: 0.75rem 0;
    overflow-y: auto;
    overflow-x: hidden;
    flex: 1;
    font-size: 0.82rem;
    line-height: 1.5;
    background: var(--pico-code-background-color, var(--pico-background-color));
    border-radius: 0 0 var(--pico-border-radius) var(--pico-border-radius);
  }

  .kb-diff-line {
    display: block;
    white-space: pre-wrap;
    word-break: break-word;
    padding: 0 1rem;
  }

  .kb-diff-line--insert {
    background: rgba(39, 174, 96, 0.18);
    color: #27ae60;
  }

  .kb-diff-line--delete {
    background: rgba(192, 57, 43, 0.18);
    color: #c0392b;
  }

  .kb-diff-line--equal {
    color: var(--pico-muted-color);
  }
</style>
