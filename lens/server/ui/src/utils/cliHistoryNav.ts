/**
 * Shell-style history browsing for the CLI input, with no text ever lost.
 *
 * `index` is the history entry on screen, `-1` the draft (what the user was
 * typing before they pressed Up). `edits` holds every slot the user changed
 * and then navigated away from, keyed by index, so the draft (`edits[-1]`) and
 * any recalled-then-edited entry come back exactly as left. All of it is
 * dropped on submit, which is also when the submitted line joins the history.
 */
export type CliHistoryNav = {
  index: number
  edits: Record<number, string>
}

export const IDLE_HISTORY_NAV: CliHistoryNav = { index: -1, edits: {} }

export type HistoryStep = { nav: CliHistoryNav; value: string }

function slotValue(history: string[], nav: CliHistoryNav, index: number): string {
  return nav.edits[index] ?? (index === -1 ? '' : (history[index] ?? ''))
}

/** Remember `current` as the content of the slot being left, if it differs from what the slot holds. */
function leaveSlot(history: string[], nav: CliHistoryNav, current: string): Record<number, string> {
  const original = nav.index === -1 ? null : (history[nav.index] ?? null)
  const edits = { ...nav.edits }
  if (current === original) delete edits[nav.index]
  else edits[nav.index] = current
  return edits
}

function moveTo(history: string[], nav: CliHistoryNav, current: string, index: number): HistoryStep {
  const edits = leaveSlot(history, nav, current)
  const next = { index, edits }
  return { nav: next, value: slotValue(history, next, index) }
}

/** Clamp a stale index (history cleared or trimmed while browsing) back into range. */
function normalize(history: string[], nav: CliHistoryNav): CliHistoryNav {
  if (nav.index < history.length) return nav
  return { ...nav, index: -1 }
}

/** Up: one entry older. `null` when there is nothing older to show. */
export function historyOlder(history: string[], nav: CliHistoryNav, current: string): HistoryStep | null {
  const state = normalize(history, nav)
  if (history.length === 0) return null
  if (state.index === -1) return moveTo(history, state, current, history.length - 1)
  if (state.index === 0) return null
  return moveTo(history, state, current, state.index - 1)
}

/** Down: one entry newer, ending on the draft. `null` when already on the draft. */
export function historyNewer(history: string[], nav: CliHistoryNav, current: string): HistoryStep | null {
  const state = normalize(history, nav)
  if (state.index === -1) return null
  const index = state.index >= history.length - 1 ? -1 : state.index + 1
  return moveTo(history, state, current, index)
}

/** Jump straight back to the draft (Escape while browsing). `null` when already there. */
export function historyToDraft(history: string[], nav: CliHistoryNav, current: string): HistoryStep | null {
  const state = normalize(history, nav)
  if (state.index === -1) return null
  return moveTo(history, state, current, -1)
}

/** Jump to a specific entry (picked from the history drawer), keeping the draft. */
export function historyJump(
  history: string[],
  nav: CliHistoryNav,
  current: string,
  index: number,
): HistoryStep | null {
  const state = normalize(history, nav)
  if (index < 0 || index >= history.length) return null
  return moveTo(history, state, current, index)
}

/** Append a submitted line: newest last, an earlier identical entry moved up rather than repeated. */
export function appendHistory(history: string[], entry: string, max: number): string[] {
  if (!entry) return history
  return [...history.filter((item) => item !== entry), entry].slice(-max)
}
