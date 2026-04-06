<script lang="ts">
  import { get } from 'svelte/store'
  import CodeMirrorEditor from './CodeMirrorEditor.svelte'
  import { nodeContent } from '../../stores/document'
  import { inlineEditMode, inlineEditResult, inlineEditConfirmTrigger, inlineEditCancelTrigger } from '../../stores/ui'

  let currentText = ''
  let lastConfirm = get(inlineEditConfirmTrigger)
  let lastCancel = get(inlineEditCancelTrigger)

  $: {
    const t = $inlineEditConfirmTrigger
    if (t !== lastConfirm) { lastConfirm = t; confirm() }
  }
  $: {
    const t = $inlineEditCancelTrigger
    if (t !== lastCancel) { lastCancel = t; cancel() }
  }

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
  </div>
{/if}

<style>
  .inline-edit-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    min-width: 0;
    width: 100%;
    padding: 0.5rem;
    padding-bottom: 0.35rem;
    overflow: hidden;
    box-sizing: border-box;
  }
</style>
