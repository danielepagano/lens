import { EditorState, type Extension } from '@codemirror/state'
import {
  BlockInfo,
  Decoration,
  type DecorationSet,
  EditorView,
  lineNumbers,
  ViewPlugin,
  type ViewUpdate,
} from '@codemirror/view'
import type { Range } from '@codemirror/state'

export type LinePickRowState = 'pickable' | 'disabled' | 'annotation'

function finalizePick(
  states: Map<number, LinePickRowState>,
  lineNo: number,
  event: MouseEvent,
  onPick: (line: number) => void,
): boolean {
  if (states.get(lineNo) !== 'pickable') return false
  event.preventDefault()
  onPick(lineNo)
  return true
}

export function pickLineNumberConfig(
  states: Map<number, LinePickRowState>,
  onPick: (line: number) => void,
) {
  return {
    domEventHandlers: {
      mousedown(view: EditorView, line: BlockInfo, event: Event) {
        const ev = event as MouseEvent
        if (ev.button !== 0) return false
        const lineNo = view.state.doc.lineAt(line.from).number
        return finalizePick(states, lineNo, ev, onPick)
      },
    },
  }
}

export function pickLineNumbers(states: Map<number, LinePickRowState>, onPick: (line: number) => void) {
  return lineNumbers(pickLineNumberConfig(states, onPick))
}

const pickableDeco = Decoration.line({ class: 'cm-linepick-pickable' })
const disabledDeco = Decoration.line({ class: 'cm-linepick-disabled' })
const annotationDeco = Decoration.line({ class: 'cm-linepick-annotation' })

function decoFor(st: LinePickRowState) {
  switch (st) {
    case 'pickable':
      return pickableDeco
    case 'annotation':
      return annotationDeco
    default:
      return disabledDeco
  }
}

function buildLinePickDecorations(
  states: Map<number, LinePickRowState>,
  state: EditorState,
): DecorationSet {
  const builder: Range<Decoration>[] = []
  for (let i = 1; i <= state.doc.lines; i++) {
    const st = states.get(i) ?? 'disabled'
    const line = state.doc.line(i)
    builder.push(decoFor(st).range(line.from))
  }
  return Decoration.set(builder)
}

export function linePickDecorationField(states: Map<number, LinePickRowState>): Extension {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet
      constructor(view: EditorView) {
        this.decorations = buildLinePickDecorations(states, view.state)
      }
      update(u: ViewUpdate) {
        if (u.docChanged) this.decorations = buildLinePickDecorations(states, u.state)
      }
    },
    { decorations: (v) => v.decorations },
  )
}

export function pickRestExtensions(
  states: Map<number, LinePickRowState>,
  onPick: (line: number) => void,
): Extension[] {
  return [
    EditorState.readOnly.of(true),
    linePickDecorationField(states),
    EditorView.domEventHandlers({
      mousedown(event, view) {
        if (event.button !== 0) return false
        const pos = view.posAtCoords({ x: event.clientX, y: event.clientY })
        if (pos == null) return false
        const lineNo = view.state.doc.lineAt(pos).number
        return finalizePick(states, lineNo, event, onPick)
      },
    }),
  ]
}
