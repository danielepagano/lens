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
    <div class="kb-quote-edit-body">
      {#if meta.slug}
        <span class="kb-quote-edit-pill" style={pillStyle}>{meta.slug}</span>
      {/if}
      <textarea
        bind:this={textareaEl}
        class="kb-quote-edit-input"
        rows="1"
        value={draft}
        oninput={handleInput}
        onkeydown={handleKeydown}
      ></textarea>
    </div>
    <div class="kb-quote-edit-actions">
      <button type="button" class="kb-quote-edit-btn" onclick={onCancel}>Cancel</button>
      <button type="button" class="kb-quote-edit-btn kb-quote-edit-btn-primary" onclick={handleSave}>Save</button>
    </div>
  {/if}
</dialog>

<style>
  .kb-quote-edit-dialog {
    border: none;
    border-radius: var(--pico-border-radius, 6px);
    padding: 0;
    width: min(28rem, 92vw);
    background: var(--pico-background-color);
    color: var(--pico-color);
  }

  .kb-quote-edit-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .kb-quote-edit-body {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 1rem;
  }

  /* Mirrors `.content blockquote .quote-pill` in app.css (out of that
     ancestor context here, inside the dialog, so it needs its own rule). */
  .kb-quote-edit-pill {
    flex-shrink: 0;
    display: inline-block;
    margin-top: 0.35rem;
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
    flex: 1;
    resize: none;
    overflow: hidden;
    min-height: 2.2rem;
    max-height: 40vh;
    font: inherit;
    line-height: 1.4;
    padding: 0.35rem 0.5rem;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 4px;
    background: var(--pico-background-color);
    color: var(--pico-color);
  }

  .kb-quote-edit-input:focus {
    outline: none;
    border-color: var(--pico-primary-background);
  }

  .kb-quote-edit-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--pico-muted-border-color);
  }

  .kb-quote-edit-btn {
    height: 1.9rem;
    padding: 0 0.75rem;
    font-size: 0.85rem;
    border-radius: 3px;
    border: 1px solid var(--pico-muted-border-color);
    background: none;
    color: var(--pico-muted-color);
    cursor: pointer;
  }

  .kb-quote-edit-btn:hover {
    background: var(--pico-secondary-hover-background);
    color: var(--pico-color);
  }

  .kb-quote-edit-btn-primary {
    border-color: var(--pico-primary-background);
    background: var(--pico-primary-background);
    color: var(--pico-primary-inverse);
  }

  .kb-quote-edit-btn-primary:hover {
    opacity: 0.9;
    color: var(--pico-primary-inverse);
  }
</style>
