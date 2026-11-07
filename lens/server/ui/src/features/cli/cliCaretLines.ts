/**
 * Visual-line geometry of a textarea, counting soft wraps.
 *
 * A textarea exposes no line geometry, so this lays the value out in an
 * off-screen mirror with the same font, width and wrapping, one span per
 * character, and reads where each caret position sits. Only used on Up/Down,
 * so the throwaway element is cheap enough.
 *
 * History browsing uses it to behave like one continuous text: Up leaves the
 * input only from its first line and lands on the last line of the older
 * entry, at the same horizontal position; Down mirrors that.
 */

const MIRRORED_PROPS = [
  'font-family',
  'font-size',
  'font-weight',
  'font-style',
  'font-variant',
  'font-stretch',
  'font-kerning',
  'font-feature-settings',
  'letter-spacing',
  'word-spacing',
  'line-height',
  'text-transform',
  'text-indent',
  'tab-size',
  'white-space',
  'word-break',
  'overflow-wrap',
  'direction',
] as const

type Layout = {
  /** Caret position where each visual line starts; `lineStarts[0]` is 0. */
  lineStarts: number[]
  /** Horizontal offset of the caret at each position `0..value.length`. */
  lefts: number[]
}

function layout(el: HTMLTextAreaElement, value: string): Layout {
  const style = getComputedStyle(el)
  const mirror = document.createElement('div')
  for (const prop of MIRRORED_PROPS) mirror.style.setProperty(prop, style.getPropertyValue(prop))
  const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0)
  Object.assign(mirror.style, {
    position: 'absolute',
    visibility: 'hidden',
    top: '0',
    left: '-9999px',
    boxSizing: 'content-box',
    padding: '0',
    border: '0',
    // clientWidth already excludes a vertical scrollbar when the textarea scrolls.
    width: `${Math.max(el.clientWidth - padX, 1)}px`,
    whiteSpace: 'pre-wrap',
    overflowWrap: style.overflowWrap === 'normal' ? 'break-word' : style.overflowWrap,
  })
  const spans: HTMLSpanElement[] = []
  for (const char of value) {
    // Surrogate pairs come through whole; pad them so positions stay UTF-16 offsets.
    const span = document.createElement('span')
    span.textContent = char
    spans.push(span)
    if (char.length === 2) spans.push(span)
    mirror.append(span)
  }
  const end = document.createElement('span')
  end.textContent = '​'
  spans.push(end)
  mirror.append(end)
  document.body.append(mirror)

  const lineHeight = parseFloat(style.lineHeight) || (parseFloat(style.fontSize) || 16) * 1.2
  const lineStarts = [0]
  const lefts: number[] = []
  let lineTop = spans[0]?.offsetTop ?? 0
  spans.forEach((span, pos) => {
    const top = span.offsetTop
    if (top - lineTop > lineHeight / 2) {
      lineStarts.push(pos)
      lineTop = top
    }
    lefts.push(span.offsetLeft)
  })
  mirror.remove()
  return { lineStarts, lefts }
}

function lineIndexOf(lineStarts: number[], pos: number): number {
  let index = 0
  while (index + 1 < lineStarts.length && (lineStarts[index + 1] ?? Infinity) <= pos) index += 1
  return index
}

export type CaretLineInfo = { onFirstLine: boolean; onLastLine: boolean; x: number }

/** Where a collapsed caret sits: first/last visual line and its x. `null` with a selection. */
export function caretLineInfo(el: HTMLTextAreaElement): CaretLineInfo | null {
  const start = el.selectionStart ?? 0
  if (start !== (el.selectionEnd ?? 0)) return null
  const { lineStarts, lefts } = layout(el, el.value)
  const line = lineIndexOf(lineStarts, start)
  return { onFirstLine: line === 0, onLastLine: line === lineStarts.length - 1, x: lefts[start] ?? 0 }
}

/** The caret position on the first or last visual line of the current value closest to `x`. */
export function positionOnLine(el: HTMLTextAreaElement, which: 'first' | 'last', x: number): number {
  const value = el.value
  const { lineStarts, lefts } = layout(el, value)
  const line = which === 'first' ? 0 : lineStarts.length - 1
  const from = lineStarts[line] ?? 0
  // The next line's start belongs to that line (the caret shows there after a wrap).
  const to = line + 1 < lineStarts.length ? (lineStarts[line + 1] ?? value.length) - 1 : value.length
  let best = from
  for (let pos = from; pos <= to; pos += 1) {
    if (Math.abs((lefts[pos] ?? 0) - x) < Math.abs((lefts[best] ?? 0) - x)) best = pos
  }
  return best
}
