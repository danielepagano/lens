import type { CliCommandCursorTarget } from '../commands/common'

/**
 * A single suggestion chip. Shape is CLI-flavored today (kind/group cover CLI
 * concepts like commands, KB mentions, dice rolls); other CommandBar
 * consumers are free to add new `kind`/`group` values as they grow their own
 * suggestion sources — CommandSuggestions renders unknown kinds with the
 * plain base style.
 */
export interface Suggestion {
  label: string
  value: string
  kind:
    | 'command'
    | 'slug'
    | 'kb-type'
    | 'kb-key'
    | 'flag'
    | 'node'
    | 'dice-roll'
    | 'time-now'
    | 'go-cursor'
    | 'var-prefix'
    | 'var-key'
  group: string
  nodeHasChildren?: boolean
  /** Mount browse only: directory row (yellow dashed chip like prefix groups) */
  isMountDirectory?: boolean
  /** Appended after `value` on Tab/select: `' '` finishes token, `'-'` continues dashed segments */
  completionSuffix?: string
  /** From active command: chips that target the narrative cursor vs explicit node */
  cursorTargeting?: CliCommandCursorTarget
  /** ``--`` flag matches merged pinned params when viewing the narrative cursor */
  effectiveParamPin?: boolean
}

/** Icon/label/behavior for the CommandBar's left or right button. */
export type CommandBarButton = {
  /** Rendered glyph, e.g. '↓', '?', '✕'. */
  icon: string
  /** Used as the `title` tooltip, and as `aria-label` unless `ariaLabel` is given. */
  label: string
  ariaLabel?: string
  active?: boolean
  onClick: () => void
}
