<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine } from '@codemirror/view'
  import { Compartment, EditorState, type Extension } from '@codemirror/state'
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdown } from '@codemirror/lang-markdown'
  import { syntaxHighlighting, HighlightStyle, bracketMatching } from '@codemirror/language'
  import { tags } from '@lezer/highlight'
  import { Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from '@codemirror/view'
  import { pickLineNumbers, pickRestExtensions, type LinePickRowState } from './cmLinePick'

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
  /** When set, the editor is read-only; pickable lines are chosen via click or gutter. */
  export let linePickLineStates: Map<number, LinePickRowState> | null = null

  const dispatch = createEventDispatcher<{ change: string; linePick: number }>()
  const lineNumbersCompartment = new Compartment()
  const pickRestCompartment = new Compartment()

  function emitLinePick(line: number) {
    dispatch('linePick', line)
  }

  let container: HTMLDivElement
  let view: EditorView | undefined
  // Track the last content we emitted via on:change so the reactive sync
  // below can tell the difference between our own echoed prop update and
  // a genuinely external content change. On mobile, the Svelte flush that
  // delivers the echoed prop can arrive after _sync.suppress is already false,
  // so a simple boolean flag is not reliable.
  const _sync = { lastEmitted: content }

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
    '.cm-content .cm-line.cm-linepick-pickable': {
      cursor: 'pointer',
    },
    '.cm-content .cm-line.cm-linepick-pickable:hover': {
      backgroundColor: 'color-mix(in srgb, var(--pico-primary) 12%, transparent)',
    },
    '.cm-content .cm-line.cm-linepick-annotation': {
      opacity: '0.35',
    },
    '.cm-content .cm-line.cm-linepick-disabled': {
      backgroundColor: 'color-mix(in srgb, var(--pico-del-color, #c62828) 8%, transparent)',
      opacity: '0.45',
      color: 'var(--pico-del-color, #c62828)',
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
      lineNumbersCompartment.of(
        linePickLineStates ? pickLineNumbers(linePickLineStates, emitLinePick) : lineNumbers(),
      ),
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
          const newDoc = update.state.doc.toString()
          _sync.lastEmitted = newDoc
          dispatch('change', newDoc)
        }
      }),
      pickRestCompartment.of(
        linePickLineStates ? pickRestExtensions(linePickLineStates, emitLinePick) : [],
      ),
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
    // Only push content into CodeMirror when it changed from outside (not
    // echoed back from our own on:change emission). Without this guard a
    // mobile browser's async input pipeline can deliver the echoed prop
    // after _sync.lastEmitted has already been updated, causing a false
    // "external change" detection that replaces the doc and snaps the
    // cursor to position 0.
    if (content !== current && content !== _sync.lastEmitted) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: content },
      })
    }
  }

  $: pickFingerprint =
    linePickLineStates == null
      ? ''
      : `${content.length}|${[...linePickLineStates.entries()].sort((a, b) => a[0] - b[0]).map(([k, v]) => `${k}:${v}`).join(',')}`

  let lastPickFingerprint = ''
  $: if (view && pickFingerprint !== lastPickFingerprint) {
    lastPickFingerprint = pickFingerprint
    view.dispatch({
      effects: [
        lineNumbersCompartment.reconfigure(
          linePickLineStates ? pickLineNumbers(linePickLineStates, emitLinePick) : lineNumbers(),
        ),
        pickRestCompartment.reconfigure(
          linePickLineStates ? pickRestExtensions(linePickLineStates, emitLinePick) : [],
        ),
      ],
    })
  }
</script>

<div class="cm-wrapper" bind:this={container}></div>

<style>
  .cm-wrapper {
    width: 100%;
    min-height: 100px;
  }
</style>
