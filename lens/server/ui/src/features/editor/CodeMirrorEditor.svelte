<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine } from '@codemirror/view'
  import { EditorState, type Extension } from '@codemirror/state'
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdown } from '@codemirror/lang-markdown'
  import { syntaxHighlighting, defaultHighlightStyle, bracketMatching } from '@codemirror/language'
  import { Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from '@codemirror/view'

  export let content: string
  export let editableRange: { fromLine: number; toLine: number } | null = null
  export let lang: 'markdown' | 'plain' = 'markdown'

  const dispatch = createEventDispatcher<{ change: string }>()

  let container: HTMLDivElement
  let view: EditorView | undefined
  let suppressExternalUpdate = false

  const readonlyLineDeco = Decoration.line({ class: 'cm-readonly-line' })

  function buildReadonlyDecorations(state: EditorState): DecorationSet {
    if (!editableRange) return Decoration.none
    const builder: import('@codemirror/state').Range<Decoration>[] = []
    for (let i = 1; i <= state.doc.lines; i++) {
      if (i < editableRange.fromLine || i > editableRange.toLine) {
        builder.push(readonlyLineDeco.range(state.doc.line(i).from))
      }
    }
    return Decoration.set(builder)
  }

  const readonlyPlugin = ViewPlugin.fromClass(
    class {
      decorations: DecorationSet
      constructor(view: EditorView) {
        this.decorations = buildReadonlyDecorations(view.state)
      }
      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = buildReadonlyDecorations(update.state)
        }
      }
    },
    { decorations: (v) => v.decorations }
  )

  function rangeFilter(): Extension {
    if (!editableRange) return []
    const fromLine = editableRange.fromLine
    const toLine = editableRange.toLine
    return EditorState.transactionFilter.of((tr) => {
      if (!tr.docChanged) return tr
      const doc = tr.startState.doc
      const editFrom = doc.line(Math.min(fromLine, doc.lines)).from
      const editTo = doc.line(Math.min(toLine, doc.lines)).to
      let dominated = true
      tr.changes.iterChangedRanges((chFrom, chTo) => {
        if (chFrom < editFrom || chTo > editTo) dominated = false
      })
      return dominated ? tr : []
    })
  }

  function buildExtensions(): Extension[] {
    const exts: Extension[] = [
      lineNumbers(),
      drawSelection(),
      highlightActiveLine(),
      history(),
      bracketMatching(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          suppressExternalUpdate = true
          dispatch('change', update.state.doc.toString())
          suppressExternalUpdate = false
        }
      }),
    ]
    if (lang === 'markdown') exts.push(markdown())
    if (editableRange) {
      exts.push(rangeFilter(), readonlyPlugin)
    }
    return exts
  }

  onMount(() => {
    const state = EditorState.create({
      doc: content,
      extensions: buildExtensions(),
    })
    view = new EditorView({ state, parent: container })
  })

  onDestroy(() => {
    view?.destroy()
  })

  $: if (view && !suppressExternalUpdate) {
    const current = view.state.doc.toString()
    if (content !== current) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: content },
      })
    }
  }
</script>

<div class="cm-wrapper" bind:this={container}></div>

<style>
  .cm-wrapper {
    width: 100%;
    min-height: 100px;
  }
  .cm-wrapper :global(.cm-editor) {
    border: 1px solid var(--pico-form-element-border-color, #bfc7cf);
    border-radius: var(--pico-border-radius, 0.25rem);
    font-family: var(--pico-font-family-monospace, monospace);
    font-size: 0.875rem;
    max-height: 70vh;
    overflow: auto;
  }
  .cm-wrapper :global(.cm-editor.cm-focused) {
    outline: none;
    border-color: var(--pico-primary, #1095c1);
  }
  .cm-wrapper :global(.cm-scroller) {
    overflow: auto;
  }
  .cm-wrapper :global(.cm-content) {
    padding: 0.5rem 0;
  }
  .cm-wrapper :global(.cm-line) {
    padding: 0 0.5rem;
  }
  .cm-wrapper :global(.cm-readonly-line) {
    background: var(--pico-muted-border-color, rgba(128, 128, 128, 0.08));
    opacity: 0.5;
  }
  /* Prevent Pico from styling CodeMirror internals */
  .cm-wrapper :global(.cm-editor input),
  .cm-wrapper :global(.cm-editor button),
  .cm-wrapper :global(.cm-editor select) {
    all: revert;
  }
</style>
