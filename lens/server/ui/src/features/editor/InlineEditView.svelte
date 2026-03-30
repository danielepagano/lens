<script lang="ts">
  import { get } from 'svelte/store'
  import CodeMirrorEditor from './CodeMirrorEditor.svelte'
  import { nodeContent } from '../../stores/document'
  import { inlineEditMode, inlineEditResult } from '../../stores/ui'

  let currentText = ''

  function handleChange(e: CustomEvent<string>) {
    currentText = e.detail
  }

  function confirm() {
    const s = get(inlineEditMode)
    if (!s) return
    if (s.appendMode) {
      const fullText = currentText.length > 0 ? currentText : ''
      const appendedText = fullText.split('\n').slice(s.startLine - 1).join('\n')
      if (appendedText.trim()) {
        inlineEditResult.set(appendedText)
      }
      inlineEditMode.set(null)
      return
    }
    const fullText = currentText.length > 0 ? currentText : get(nodeContent)
    const modifiedLines = fullText.split('\n')
    const suffix = s.linesAfterSelection
    const end = modifiedLines.length - suffix
    const editedLines = modifiedLines.slice(s.startLine - 1, end).join('\n')
    if (editedLines !== s.originalText) {
      inlineEditResult.set(editedLines)
    }
    inlineEditMode.set(null)
  }

  function cancel() {
    inlineEditResult.set(null)
    inlineEditMode.set(null)
  }

  function handleWindowKeydown(e: KeyboardEvent) {
    if (!$inlineEditMode) return
    if (e.key === 'Escape') {
      e.preventDefault()
      cancel()
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      confirm()
    }
  }
</script>

<svelte:window on:keydown={handleWindowKeydown} />

{#if $inlineEditMode}
  {@const state = $inlineEditMode}
  {@const appendContent = state.appendMode
    ? ($nodeContent.endsWith('\n') ? $nodeContent + '\n' : $nodeContent + '\n\n')
    : $nodeContent}
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="inline-edit-view" data-testid="inline-edit-view" on:keydown={handleKeydown}>
    <div class="inline-edit-hint">
      {#if state.appendMode}
        Append text
      {:else}
        Editing lines {state.startLine}–{state.endLine}
      {/if}
      <span class="inline-edit-shortcut">Ctrl+Enter to apply · Esc to cancel</span>
    </div>
    <CodeMirrorEditor
      content={appendContent}
      editableRange={{
        fromLine: state.startLine,
        toLine: state.endLine,
        linesAfterSelection: state.linesAfterSelection,
      }}
      lang="markdown"
      on:change={handleChange}
    />
    <div class="inline-edit-toolbar">
      <button type="button" class="inline-edit-ok" on:click={confirm}>OK</button>
      <button type="button" class="inline-edit-cancel secondary" on:click={cancel}>Cancel</button>
    </div>
  </div>
{/if}

<style>
  .inline-edit-view {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
    min-height: 0;
    min-width: 0;
    width: 100%;
    padding: 0.5rem;
    padding-bottom: 0.35rem;
    overflow: hidden;
    box-sizing: border-box;
  }
  .inline-edit-hint {
    flex-shrink: 0;
    font-size: 0.8rem;
    color: var(--pico-muted-color, #73828c);
    padding: 0 0.25rem;
  }
  .inline-edit-shortcut {
    margin-left: 0.75rem;
    opacity: 0.7;
  }
  .inline-edit-toolbar {
    flex-shrink: 0;
    display: flex;
    gap: 0.5rem;
    padding: 0.15rem 0 0;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  .inline-edit-toolbar button {
    padding: 0.35rem 1rem;
    font-size: 0.85rem;
    margin: 0;
  }
</style>
