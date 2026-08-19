<script lang="ts">
  import { quotePillHslVars } from '../../utils/markdown'
  import type { KbEditMeta } from './kbEditableControls'

  interface Props {
    meta: KbEditMeta | null
    onSave: (text: string) => void
    onCancel: () => void
  }
  let { meta, onSave, onCancel }: Props = $props()

  let dialogEl = $state<HTMLDialogElement | null>(null)
  let textareaEl = $state<HTMLTextAreaElement | null>(null)
  let draft = $state('')

  const pillStyle = $derived.by(() => {
    if (!meta?.slug) return ''
    const { accent, border } = quotePillHslVars(meta.slug)
    return `--quote-pill-accent:${accent};--quote-pill-border:${border}`
  })

  function autoGrow() {
    if (!textareaEl) return
    textareaEl.style.height = 'auto'
    textareaEl.style.height = `${textareaEl.scrollHeight}px`
  }

  $effect(() => {
    if (!dialogEl) return
    if (meta) {
      draft = meta.value
      if (!dialogEl.open) dialogEl.showModal()
      // Wait for the textarea to exist in the DOM (it's behind {#if meta}) before sizing/focusing it.
      queueMicrotask(() => {
        autoGrow()
        textareaEl?.focus()
        textareaEl?.select()
      })
    } else if (dialogEl.open) {
      dialogEl.close()
    }
  })

  // Content is one editable line: strip any newline a paste might introduce.
  function handleInput(e: Event) {
    const t = e.target as HTMLTextAreaElement
    const cleaned = t.value.replace(/\r?\n/g, ' ')
    if (cleaned !== t.value) t.value = cleaned
    draft = cleaned
    autoGrow()
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') e.preventDefault()
  }

  function handleSave() {
    onSave(draft)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialogEl) onCancel()
  }
</script>

<dialog
  bind:this={dialogEl}
  class="kb-quote-edit-dialog"
  onclose={onCancel}
  onclick={handleBackdropClick}
>
  {#if meta}
    <article class="kb-quote-edit-article">
      <header class="kb-quote-edit-header">
        {#if meta.slug}
          <span class="kb-quote-edit-pill" style={pillStyle}>{meta.slug}</span>
        {/if}
      </header>

      <textarea
        bind:this={textareaEl}
        class="kb-quote-edit-input"
        rows="1"
        value={draft}
        oninput={handleInput}
        onkeydown={handleKeydown}
      ></textarea>

      <footer class="kb-quote-edit-footer">
        <button type="button" class="secondary" onclick={onCancel}>Cancel</button>
        <button type="button" onclick={handleSave}>Save</button>
      </footer>
    </article>
  {/if}
</dialog>

<style>
  .kb-quote-edit-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  /* Pico's `dialog > article` gives the floating-card centering/max-height —
     this only narrows it to a compact width and tightens the padding. */
  .kb-quote-edit-article {
    width: min(92vw, 480px);
    padding: 0.85rem 1rem;
  }

  .kb-quote-edit-header {
    margin-bottom: 0.5rem;
  }

  /* Mirrors `.content blockquote .quote-pill` in app.css (out of that
     ancestor context here, inside the dialog, so it needs its own rule). */
  .kb-quote-edit-pill {
    display: inline-block;
    border-radius: 0.5rem;
    padding: 0.08rem 0.4rem;
    font-size: 1rem;
    font-variant: small-caps;
    font-family: Verdana, Geneva, Tahoma, sans-serif;
    letter-spacing: 0.02em;
    line-height: 1.2;
    color: rgba(255, 255, 255, 0.94);
    background: hsl(var(--quote-pill-accent, 210 48% 34%));
    border: 1px solid hsl(var(--quote-pill-border, 210 48% 42%));
    white-space: nowrap;
  }

  .kb-quote-edit-input {
    width: 100%;
    resize: none;
    overflow: hidden;
    min-height: 2.4rem;
    max-height: 40vh;
    font: inherit;
    line-height: 1.4;
    padding: 0.35rem 0.5rem;
    box-sizing: border-box;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 4px;
    background: var(--pico-background-color);
    color: var(--pico-color);
  }

  .kb-quote-edit-input:focus {
    outline: none;
    border-color: var(--pico-primary-background);
  }

  .kb-quote-edit-footer {
    margin-top: 0.5rem;
  }

  .kb-quote-edit-footer button {
    padding: 0.35rem 0.75rem;
    font-size: 0.85rem;
    min-height: 2rem;
  }
</style>
