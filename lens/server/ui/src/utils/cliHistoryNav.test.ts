import { describe, it, expect } from 'vitest'
import {
  appendHistory,
  historyJump,
  historyNewer,
  historyOlder,
  historyToDraft,
  IDLE_HISTORY_NAV,
  type CliHistoryNav,
} from './cliHistoryNav'

const HISTORY = ['/a', '/b', '/c']

function up(nav: CliHistoryNav, current: string) {
  const step = historyOlder(HISTORY, nav, current)
  if (!step) throw new Error('expected an older entry')
  return step
}

function down(nav: CliHistoryNav, current: string) {
  const step = historyNewer(HISTORY, nav, current)
  if (!step) throw new Error('expected a newer slot')
  return step
}

describe('cliHistoryNav', () => {
  it('walks back from newest to oldest and stops there', () => {
    const s1 = up(IDLE_HISTORY_NAV, '/')
    expect(s1.value).toBe('/c')
    const s2 = up(s1.nav, s1.value)
    expect(s2.value).toBe('/b')
    const s3 = up(s2.nav, s2.value)
    expect(s3.value).toBe('/a')
    expect(historyOlder(HISTORY, s3.nav, s3.value)).toBeNull()
  })

  it('keeps the draft and restores it when Down passes the newest entry', () => {
    const s1 = up(IDLE_HISTORY_NAV, '/write half a thought')
    const s2 = up(s1.nav, s1.value)
    const s3 = down(s2.nav, s2.value)
    expect(s3.value).toBe('/c')
    const s4 = down(s3.nav, s3.value)
    expect(s4.value).toBe('/write half a thought')
    expect(s4.nav.index).toBe(-1)
  })

  it('does nothing on Down while already on the draft', () => {
    expect(historyNewer(HISTORY, IDLE_HISTORY_NAV, '/typed')).toBeNull()
  })

  it('keeps edits made to a recalled entry when browsing away and back', () => {
    const s1 = up(IDLE_HISTORY_NAV, '/draft')
    const s2 = up(s1.nav, '/c edited')
    expect(s2.value).toBe('/b')
    const s3 = down(s2.nav, s2.value)
    expect(s3.value).toBe('/c edited')
    const s4 = down(s3.nav, s3.value)
    expect(s4.value).toBe('/draft')
  })

  it('forgets an edit that was typed back to the original', () => {
    const s1 = up(IDLE_HISTORY_NAV, '/draft')
    const s2 = up(s1.nav, '/c')
    expect(s2.nav.edits[2]).toBeUndefined()
  })

  it('Escape jumps straight back to the draft, keeping edits', () => {
    const s1 = up(IDLE_HISTORY_NAV, '/draft')
    const s2 = up(s1.nav, s1.value)
    const back = historyToDraft(HISTORY, s2.nav, '/b changed')
    expect(back?.value).toBe('/draft')
    expect(back?.nav.edits[1]).toBe('/b changed')
    expect(historyToDraft(HISTORY, IDLE_HISTORY_NAV, '/x')).toBeNull()
  })

  it('jumping from the drawer keeps the draft for Down to restore', () => {
    const jumped = historyJump(HISTORY, IDLE_HISTORY_NAV, '/draft', 0)
    expect(jumped?.value).toBe('/a')
    const back = down(jumped!.nav, jumped!.value)
    expect(back.value).toBe('/b')
    expect(historyJump(HISTORY, IDLE_HISTORY_NAV, '/draft', 9)).toBeNull()
  })

  it('treats a stale index past the end of a shrunk history as the draft', () => {
    const stale: CliHistoryNav = { index: 7, edits: { [-1]: '/draft' } }
    const step = historyOlder(HISTORY, stale, '/whatever')
    expect(step?.value).toBe('/c')
  })

  it('has nothing to browse with an empty history', () => {
    expect(historyOlder([], IDLE_HISTORY_NAV, '/x')).toBeNull()
  })

  it('appendHistory moves a repeated entry to the end instead of duplicating it', () => {
    expect(appendHistory(['/a', '/b', '/c'], '/a', 10)).toEqual(['/b', '/c', '/a'])
    expect(appendHistory(['/a', '/b'], '/b', 10)).toEqual(['/a', '/b'])
    expect(appendHistory(['/a', '/b', '/c'], '/d', 3)).toEqual(['/b', '/c', '/d'])
    expect(appendHistory(['/a'], '', 3)).toEqual(['/a'])
  })
})
