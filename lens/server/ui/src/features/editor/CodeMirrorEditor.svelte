<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine } from '@codemirror/view'
  import { EditorState, type Extension } from '@codemirror/state'
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdown } from '@codemirror/lang-markdown'
  import { syntaxHighlighting, HighlightStyle, bracketMatching } from '@codemirror/language'
  import { tags } from '@lezer/highlight'
  import { Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from '@codemirror/view'

  /** Theme-aware highlighter: defaultHighlightStyle uses fixed dark blues (#219 etc.) whose
   *  StyleMod classes (e.g. …ec) are illegible on Pico dark backgrounds. */
  const lensHighlightStyle = HighlightStyle.define([
    { tag: tags.meta, color: 'var(--pico-muted-color)' },
    { tag: tags.link, color: 'var(--pico-primary)', textDecoration: 'underline' },
    { tag: tags.heading, textDecoration: 'underline', fontWeight: 'bold' },
    { tag: tags.emphasis, fontStyle: 'italic' },
    { tag: tags.strong, fontWeight: 'bold' },
    { tag: tags.strikethrough, textDecoration: 'line-through' },
    {
      tag: tags.keyword,
      color: 'color-mix(in srgb, var(--pico-primary) 45%, var(--pico-muted-color))',
    },
    {
      tag: [tags.atom, tags.bool, tags.url, tags.contentSeparator, tags.labelName],
      color: 'var(--pico-primary)',
    },
    { tag: [tags.literal, tags.inserted], color: 'var(--pico-ins-color)' },
    { tag: [tags.string, tags.deleted], color: 'var(--pico-del-color)' },
    {
      tag: [tags.regexp, tags.escape, tags.special(tags.string)],
      color: 'color-mix(in srgb, var(--pico-del-color) 55%, var(--pico-primary))',
    },
    { tag: tags.definition(tags.variableName), color: 'var(--pico-primary-hover)' },
    { tag: tags.local(tags.variableName), color: 'var(--pico-color)' },
    { tag: [tags.typeName, tags.namespace], color: 'var(--pico-ins-color)' },
    { tag: tags.className, color: 'var(--pico-primary)' },
    {
      tag: [tags.special(tags.variableName), tags.macroName],
      color: 'color-mix(in srgb, var(--pico-primary) 35%, var(--pico-color))',
    },
    { tag: tags.definition(tags.propertyName), color: 'var(--pico-primary)' },
    { tag: tags.comment, color: 'var(--pico-muted-color)' },
    { tag: tags.invalid, color: 'var(--pico-del-color)' },
  ])

  export let content: string
  export let editableRange: { fromLine: number; toLine: number } | null = null
  export let lang: 'markdown' | 'plain' = 'markdown'

  const dispatch = createEventDispatcher<{ change: string }>()

  let container: HTMLDivElement
  let view: EditorView | undefined
  const _sync = { suppress: false }

  const lensCmTheme = EditorView.theme({
    '&': {
      fontFamily: "'Courier New', Courier, monospace",
      fontSize: '16px',
      maxHeight: '70vh',
      overflow: 'hidden',
      border: '1px solid var(--pico-form-element-border-color, #bfc7cf)',
      borderRadius: 'var(--pico-border-radius, 0.25rem)',
    },
    '&.cm-focused': {
      outline: 'none',
      borderColor: 'var(--pico-primary, #1095c1)',
    },
    '.cm-scroller': {
      overflow: 'auto',
      fontFamily: "'Courier New', Courier, monospace",
    },
    '.cm-content': {
      padding: '0.5rem 0',
      caretColor: 'var(--pico-color)',
    },
    '.cm-line': {
      padding: '0 0.5rem',
    },
    '.cm-readonly-line': {
      background: 'var(--pico-secondary-background)',
      opacity: '0.5',
    },
    /* Pico must not restyle CodeMirror’s hidden native widgets */
    '& input, & button, & select': {
      all: 'revert',
    },
    '.cm-gutters': {
      backgroundColor:
        'color-mix(in srgb, var(--pico-muted-color) 14%, var(--pico-background-color))',
      color: 'var(--pico-muted-color)',
      borderRight: '1px solid var(--pico-muted-border-color)',
    },
    '.cm-lineNumbers .cm-gutterElement': {
      color: 'var(--pico-muted-color)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'transparent',
    },
    '.cm-activeLine': {
      backgroundColor: 'color-mix(in srgb, var(--pico-muted-color) 5%, transparent)',
    },
    '.cm-cursor, &.cm-focused .cm-cursor': {
      borderLeft: '3px solid var(--pico-color)',
      marginLeft: '-1px',
    },
    '.cm-dropcursor': {
      borderTop: '2px solid var(--pico-color)',
    },
  })

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

  function scrollEditableRangeIntoView(v: EditorView) {
    if (!editableRange) return
    const lineNo = Math.min(Math.max(1, editableRange.fromLine), v.state.doc.lines)
    const pos = v.state.doc.line(lineNo).from
    v.dispatch({
      selection: { anchor: pos, head: pos },
      effects: EditorView.scrollIntoView(pos, { y: 'start', yMargin: 8 }),
    })
  }

  function buildExtensions(): Extension[] {
    const exts: Extension[] = [
      lensCmTheme,
      lineNumbers(),
      drawSelection(),
    ]
    if (!editableRange) {
      exts.push(highlightActiveLine())
    }
    exts.push(
      EditorView.lineWrapping,
      history(),
      bracketMatching(),
    )
    if (lang === 'markdown') {
      exts.push(markdown())
    }
    exts.push(
      syntaxHighlighting(lensHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          _sync.suppress = true
          dispatch('change', update.state.doc.toString())
          _sync.suppress = false
        }
      }),
    )
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
    if (editableRange) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (view) scrollEditableRangeIntoView(view)
        })
      })
    }
  })

  onDestroy(() => {
    view?.destroy()
  })

  $: if (view) {
    const current = view.state.doc.toString()
    if (!_sync.suppress && content !== current) {
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
</style>
