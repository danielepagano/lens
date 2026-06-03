<script lang="ts">
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import { Compartment, EditorState, type Extension } from '@codemirror/state'
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdown } from '@codemirror/lang-markdown'
  import { syntaxHighlighting, HighlightStyle, bracketMatching } from '@codemirror/language'
  import {
    Decoration,
    type DecorationSet,
    EditorView,
    keymap,
    lineNumbers,
    drawSelection,
    highlightActiveLine,
    ViewPlugin,
    type ViewUpdate,
  } from '@codemirror/view'
  import { tags } from '@lezer/highlight'
  import { pickLineNumbers, pickRestExtensions, type LinePickRowState } from './cmLinePick'
  import { scrollCodeMirrorToBottom, editorFocused } from '../../stores/ui'

  type EditableRange = {
    fromLine: number
    toLine: number
    linesAfterSelection?: number
  }

  type Props = {
    content: string
    editableRange?: EditableRange | null
    lang?: 'markdown' | 'plain'
    linePickLineStates?: Map<number, LinePickRowState> | null
    onChange?: (text: string) => void
    onLinePick?: (line: number) => void
  }

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

  let {
    content,
    editableRange = null,
    lang = 'markdown',
    linePickLineStates = null,
    onChange = undefined,
    onLinePick = undefined,
  }: Props = $props()

  const lineNumbersCompartment = new Compartment()
  const pickRestCompartment = new Compartment()

  function emitLinePick(line: number) {
    onLinePick?.(line)
  }

  let container: HTMLDivElement
  let view: EditorView | undefined

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
      backgroundColor: 'color-mix(in srgb, var(--pico-del-color, #c62828) 10%, transparent)',
      opacity: '0.35',
    },
    '.cm-content .cm-line.cm-linepick-disabled': {
      backgroundColor: 'color-mix(in srgb, var(--pico-del-color, #c62828) 10%, transparent)',
      opacity: '0.45',
      color: 'var(--pico-del-color, #c62828)',
    },
  })

  const readonlyLineDeco = Decoration.line({ class: 'cm-readonly-line' })

  /** Character range allowed to change; computed on a given document state. */
  function editableCharRange(state: EditorState): { from: number; to: number } | null {
    if (!editableRange) return null
    const n = state.doc.lines
    const fl = editableRange.fromLine
    const tl = editableRange.toLine
    const tail = editableRange.linesAfterSelection
    if (tail === undefined) {
      if (n < 1) return null
      const a = Math.min(Math.max(1, fl), n)
      const b = Math.min(Math.max(1, tl), n)
      if (a > b) return null
      return { from: state.doc.line(a).from, to: state.doc.line(b).to }
    }
    const prefixEnd = fl - 1
    const suffixStart = n - tail + 1
    const firstEditable = prefixEnd + 1
    const lastEditable = suffixStart - 1
    if (firstEditable < 1 || lastEditable > n || firstEditable > lastEditable) return null
    return { from: state.doc.line(firstEditable).from, to: state.doc.line(lastEditable).to }
  }

  function buildReadonlyDecorations(state: EditorState): DecorationSet {
    if (!editableRange) return Decoration.none
    const builder: import('@codemirror/state').Range<Decoration>[] = []
    const n = state.doc.lines
    const tail = editableRange.linesAfterSelection
    if (tail === undefined) {
      for (let i = 1; i <= n; i++) {
        if (i < editableRange.fromLine || i > editableRange.toLine) {
          builder.push(readonlyLineDeco.range(state.doc.line(i).from))
        }
      }
      return Decoration.set(builder)
    }
    const prefixEnd = editableRange.fromLine - 1
    const suffixStart = n - tail + 1
    for (let i = 1; i <= n; i++) {
      if (i <= prefixEnd || i >= suffixStart) {
        builder.push(readonlyLineDeco.range(state.doc.line(i).from))
      }
    }
    return Decoration.set(builder)
  }

  const readonlyPlugin = ViewPlugin.fromClass(
    class {
      decorations: DecorationSet

      constructor(editorView: EditorView) {
        this.decorations = buildReadonlyDecorations(editorView.state)
      }

      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = buildReadonlyDecorations(update.state)
        }
      }
    },
    { decorations: (plugin) => plugin.decorations }
  )

  function rangeFilter(): Extension {
    if (!editableRange) return []
    return EditorState.transactionFilter.of((tr) => {
      if (!tr.docChanged) return tr
      const band = editableCharRange(tr.startState)
      if (!band) return []
      let dominated = true
      tr.changes.iterChangedRanges((chFrom, chTo) => {
        if (chFrom < band.from || chTo > band.to) dominated = false
      })
      return dominated ? tr : []
    })
  }

  /** Scroll to the end of the editable band, or the end of the document (line pick / full edit). */
  function scrollViewToLatest(editorView: EditorView) {
    const state = editorView.state
    const n = state.doc.lines
    if (n < 1) return
    let pos: number
    if (editableRange) {
      const tail = editableRange.linesAfterSelection
      if (tail === undefined) {
        const lineNo = Math.min(Math.max(1, editableRange.toLine), n)
        pos = state.doc.line(lineNo).to
      } else {
        const suffixStart = n - tail + 1
        const lastEditable = suffixStart - 1
        if (lastEditable < 1) {
          pos = state.doc.line(n).to
        } else {
          pos = state.doc.line(Math.min(lastEditable, n)).to
        }
      }
    } else {
      pos = state.doc.line(n).to
    }
    editorView.dispatch({
      selection: { anchor: pos, head: pos },
      effects: EditorView.scrollIntoView(pos, { y: 'end', yMargin: 12 }),
    })
  }

  function buildExtensions(): Extension[] {
    const extensions: Extension[] = [
      lensCmTheme,
      lineNumbersCompartment.of(
        linePickLineStates ? pickLineNumbers(linePickLineStates, emitLinePick) : lineNumbers(),
      ),
      drawSelection(),
    ]
    if (!editableRange) {
      extensions.push(highlightActiveLine())
    }
    extensions.push(
      EditorView.lineWrapping,
      history(),
      bracketMatching(),
      EditorView.updateListener.of((update) => {
        if (update.focusChanged) editorFocused.set(update.view.hasFocus)
      }),
    )
    if (lang === 'markdown') {
      extensions.push(markdown())
    }
    extensions.push(
      syntaxHighlighting(lensHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChange?.(update.state.doc.toString())
        }
      }),
      pickRestCompartment.of(
        linePickLineStates ? pickRestExtensions(linePickLineStates, emitLinePick) : [],
      ),
    )
    if (editableRange) {
      extensions.push(rangeFilter(), readonlyPlugin)
    }
    return extensions
  }

  let lastCmScrollRequest = get(scrollCodeMirrorToBottom)
  let pickFingerprint = $derived(
    linePickLineStates == null
      ? ''
      : `${content.length}|${[...linePickLineStates.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([k, v]) => `${k}:${v}`)
          .join(',')}`
  )
  let lastPickFingerprint = ''

  onMount(() => {
    const state = EditorState.create({
      doc: content,
      extensions: buildExtensions(),
    })
    view = new EditorView({ state, parent: container })
    if (editableRange || linePickLineStates) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (view) scrollViewToLatest(view)
        })
      })
    }

    return () => {
      view?.destroy()
      editorFocused.set(false)
    }
  })

  $effect(() => {
    if (!view) return
    const current = view.state.doc.toString()
    if (content !== current) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: content },
      })
    }
  })

  $effect(() => {
    if (!view || (!editableRange && !linePickLineStates)) return
    const scrollRequest = $scrollCodeMirrorToBottom
    if (scrollRequest === lastCmScrollRequest) return
    lastCmScrollRequest = scrollRequest
    requestAnimationFrame(() => {
      if (view) scrollViewToLatest(view)
    })
  })

  $effect(() => {
    if (!view || pickFingerprint === lastPickFingerprint) return
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
  })
</script>

<div class="cm-wrapper" bind:this={container}></div>

<style>
  .cm-wrapper {
    width: 100%;
    min-height: 100px;
  }
</style>
