<script lang="ts">
  import CodeMirrorEditor from './CodeMirrorEditor.svelte'
  import { nodeContent } from '../../stores/document'
  import { inlineEditMode, inlineEditResult } from '../../stores/ui'

  $: state = $inlineEditMode!

  let currentText = ''

  function handleChange(e: CustomEvent<string>) {
    currentText = e.detail
  }

  function extractLines(text: string, from: number, to: number): string {
    return text.split('\n').slice(from - 1, to).join('\n')
  }

  function confirm() {
    const editedLines = extractLines(currentText, state.startLine, state.endLine)
    if (editedLines !== state.originalText) {
      inlineEditResult.set(editedLines)
    }
    inlineEditMode.set(null)
  }

  function cancel() {
    inlineEditMode.set(null)
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      cancel()
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      confirm()
    }
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="inline-edit-view" on:keydown={handleKeydown}>
  <div class="inline-edit-hint">
    Editing lines {state.startLine}–{state.endLine}
    <span class="inline-edit-shortcut">Ctrl+Enter to confirm, Esc to cancel</span>
  </div>
  <CodeMirrorEditor
    content={$nodeContent}
    editableRange={{ fromLine: state.startLine, toLine: state.endLine }}
    lang="markdown"
    on:change={handleChange}
  />
  <div class="inline-edit-toolbar">
    <button class="inline-edit-ok" on:click={confirm}>OK</button>
    <button class="inline-edit-cancel secondary" on:click={cancel}>Cancel</button>
  </div>
</div>

<style>
  .inline-edit-view {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    height: 100%;
  }
  .inline-edit-hint {
    font-size: 0.8rem;
    color: var(--pico-muted-color, #73828c);
    padding: 0 0.25rem;
  }
  .inline-edit-shortcut {
    margin-left: 0.75rem;
    opacity: 0.7;
  }
  .inline-edit-toolbar {
    display: flex;
    gap: 0.5rem;
    padding: 0.25rem 0;
  }
  .inline-edit-toolbar button {
    padding: 0.35rem 1rem;
    font-size: 0.85rem;
    margin: 0;
  }
</style>
