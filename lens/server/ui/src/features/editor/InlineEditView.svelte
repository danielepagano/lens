<script lang="ts">
  import { get } from 'svelte/store'
  import CodeMirrorEditor from './CodeMirrorEditor.svelte'
  import { nodeContent } from '../../stores/document'
  import { inlineEditMode, inlineEditResult, inlineEditConfirmTrigger, inlineEditCancelTrigger } from '../../stores/ui'

  let currentText = ''
  let lastConfirm = get(inlineEditConfirmTrigger)
  let lastCancel = get(inlineEditCancelTrigger)
  const inlineState = $derived($inlineEditMode)
  const appendContent = $derived(
    inlineState?.appendMode
      ? ($nodeContent.endsWith('\n') ? $nodeContent + '\n' : $nodeContent + '\n\n')
      : $nodeContent
  )

  $effect(() => {
    const trigger = $inlineEditConfirmTrigger
    if (trigger !== lastConfirm) {
      lastConfirm = trigger
      confirm()
    }
  })

  $effect(() => {
    const trigger = $inlineEditCancelTrigger
    if (trigger !== lastCancel) {
      lastCancel = trigger
      cancel()
    }
  })

  function handleChange(text: string) {
    currentText = text
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

<svelte:window onkeydown={handleWindowKeydown} />

{#if inlineState}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="inline-edit-view" data-testid="inline-edit-view" onkeydown={handleKeydown}>
    <CodeMirrorEditor
      content={appendContent}
      editableRange={{
        fromLine: inlineState.startLine,
        toLine: inlineState.endLine,
        linesAfterSelection: inlineState.linesAfterSelection,
      }}
      lang="markdown"
      onChange={handleChange}
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
