import type { PlaybackItem, Stats } from '../services/api'

export function vnCursorCliSlotEligible(
  stats: Stats | null,
  currentAddress: string | null,
  items: PlaybackItem[]
): boolean {
  if (!currentAddress || !stats?.cursor || stats.cursor !== currentAddress) return false
  const op = stats.active_session_operator
  if (op !== 'play' && op !== 'chat') return false
  return items.length > 0
}

export function playbackTailTextId(items: PlaybackItem[]): string | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]!
    if (it.type === 'text') return it.id
  }
  return null
}
