import type { CliPayload, CommandDefinition, ParsedArgs } from './common'

export interface ParseState {
  /** What the user is currently typing */
  phase: 'command' | 'positional' | 'option-value' | 'idle'
  /** The CliPayload slot currently being filled (if any) */
  activePayload?: CliPayload
  /** Partial text of the token being typed right now */
  currentToken: string
  /** Already-completed positional values */
  completedPositional: Record<string, string | string[]>
  /** Already-completed option values */
  completedOptions: Record<string, string | boolean | string[]>
  /** True once all required positionals are satisfied (so options can be offered) */
  canOfferOptions: boolean
}

function findOption(def: CommandDefinition, name: string): CliPayload | undefined {
  return def.options?.find((o) => o.name === name)
}

/**
 * Parse CLI input against a command definition.
 *
 * Two-pass approach:
 *   Pass 1 — extract completed --option tokens (and their values) from the token list.
 *   Pass 2 — fill positional slots from the remaining non-option tokens.
 *
 * This allows options to appear anywhere (before or after positionals) and prevents
 * a `string` positional from greedily consuming --flag tokens.
 *
 * Rules:
 * - `string` positional (must be last) consumes all remaining non-option tokens joined.
 * - `repeatable` positionals collect multiple values.
 * - Options can appear before, between, or after positionals.
 */
export function parseCliInput(raw: string, def: CommandDefinition | null): ParseState {
  const trimmed = raw.trim()
  const startsWithSlash = trimmed.startsWith('/')
  const withoutSlash = startsWithSlash ? trimmed.slice(1) : trimmed

  if (!withoutSlash) {
    return emptyState('command')
  }

  const endsWithSpace = raw.endsWith(' ')
  const allTokens = withoutSlash.split(/\s+/).filter(Boolean)
  const commandToken = allTokens[0] ?? ''

  // Still typing the command name
  if (!endsWithSpace && allTokens.length === 1) {
    return { ...emptyState('command'), currentToken: commandToken }
  }

  if (!def) {
    return emptyState('idle')
  }

  const positionals = def.positional ?? []
  const options = def.options ?? []

  // Split payload into "complete tokens" (already committed) and "typing token" (current partial)
  const payloadTokens = allTokens.slice(1)
  const completeTokens = endsWithSpace ? payloadTokens : payloadTokens.slice(0, -1)
  const typingToken = endsWithSpace ? '' : (payloadTokens[payloadTokens.length - 1] ?? '')

  // ---- Pass 1: extract option tokens ----
  const completedOptions: Record<string, string | boolean | string[]> = {}
  const nonOptionTokens: string[] = []

  let i = 0
  while (i < completeTokens.length) {
    const tok = completeTokens[i]!
    if (tok.startsWith('--')) {
      const optName = tok.slice(2)
      const opt = findOption(def, optName)
      if (opt) {
        const vt = opt.valueType ?? 'flag'
        if (vt === 'flag') {
          completedOptions[optName] = true
          i++
          continue
        }
        // Value-taking: only consume next token if it isn't itself a --flag
        const nextTok = completeTokens[i + 1]
        if (nextTok !== undefined && !nextTok.startsWith('--')) {
          if (opt.repeatable) {
            const arr = (completedOptions[optName] as string[] | undefined) ?? []
            arr.push(nextTok)
            completedOptions[optName] = arr
          } else {
            completedOptions[optName] = nextTok
          }
          i += 2
          continue
        }
        // --option at end without a value (the value is the typing token — handled below)
        i++
        continue
      }
    }
    // Non-option token
    nonOptionTokens.push(tok)
    i++
  }

  // ---- Pass 2: fill positional slots from non-option tokens ----
  const completedPositional: Record<string, string | string[]> = {}
  let posIdx = 0
  let nonOptIdx = 0
  while (nonOptIdx < nonOptionTokens.length) {
    const tok = nonOptionTokens[nonOptIdx]!
    const pos = positionals[posIdx]
    if (!pos) break
    const vt = pos.valueType ?? 'flag'
    if (vt === 'string') {
      // String positional: consume all remaining non-option tokens
      completedPositional[pos.name] = nonOptionTokens.slice(nonOptIdx).join(' ')
      nonOptIdx = nonOptionTokens.length
      break
    }
    if (pos.repeatable) {
      const arr = (completedPositional[pos.name] as string[] | undefined) ?? []
      arr.push(tok)
      completedPositional[pos.name] = arr
      nonOptIdx++
      continue
    }
    completedPositional[pos.name] = tok
    posIdx++
    nonOptIdx++
  }

  // ---- Determine canOfferOptions ----
  function requiredsSatisfied(): boolean {
    for (const pos of positionals) {
      if (!pos.required) continue
      const val = completedPositional[pos.name]
      if (val === undefined) return false
      if (pos.repeatable && Array.isArray(val) && val.length === 0) return false
    }
    return true
  }
  const canOfferOptions = requiredsSatisfied() && options.length > 0

  // ---- Determine phase for the typing token ----

  // Was the last complete token a value-taking --option without its value yet?
  const lastComplete = completeTokens[completeTokens.length - 1]
  if (lastComplete?.startsWith('--')) {
    const optName = lastComplete.slice(2)
    const opt = findOption(def, optName)
    if (opt && (opt.valueType ?? 'flag') !== 'flag') {
      return {
        phase: 'option-value',
        activePayload: opt,
        currentToken: typingToken,
        completedPositional,
        completedOptions,
        canOfferOptions,
      }
    }
  }

  // Typing a flag name
  if (typingToken.startsWith('-')) {
    return {
      phase: 'idle',
      currentToken: typingToken,
      completedPositional,
      completedOptions,
      canOfferOptions: true,
    }
  }

  // Find the next positional slot to fill.
  // A `string` positional is always "active" (it can absorb additional tokens) even if partially filled.
  function nextPositionalSlot(): CliPayload | undefined {
    for (const pos of positionals) {
      const vt = pos.valueType ?? 'flag'
      if (vt === 'string') return pos  // string is always the active slot once reached
      const filled = completedPositional[pos.name]
      if (filled === undefined) return pos
      if (pos.repeatable) return pos  // repeatable can always take more
    }
    return undefined
  }

  const nextPos = nextPositionalSlot()
  if (nextPos) {
    return {
      phase: 'positional',
      activePayload: nextPos,
      currentToken: typingToken,
      completedPositional,
      completedOptions,
      canOfferOptions,
    }
  }

  return {
    phase: 'idle',
    currentToken: typingToken,
    completedPositional,
    completedOptions,
    canOfferOptions,
  }
}

function emptyState(phase: ParseState['phase']): ParseState {
  return {
    phase,
    currentToken: '',
    completedPositional: {},
    completedOptions: {},
    canOfferOptions: false,
  }
}

/**
 * Build final ParsedArgs from a ParseState for submission.
 * Also folds the currentToken into its slot so that values without a trailing
 * space (e.g. `--node /chapter-1` submitted by pressing Enter) are captured.
 */
export function buildArgs(state: ParseState, def: CommandDefinition | null = null): ParsedArgs {
  const positional: Record<string, string | string[]> = { ...state.completedPositional }
  const options: Record<string, string | boolean | string[]> = { ...state.completedOptions }

  if (state.currentToken && state.activePayload) {
    const { name, repeatable, valueType } = state.activePayload
    if (state.phase === 'option-value') {
      if (repeatable) {
        const arr = (options[name] as string[] | undefined) ?? []
        options[name] = [...arr, state.currentToken]
      } else {
        options[name] = state.currentToken
      }
    } else if (state.phase === 'positional') {
      const vt = valueType ?? 'flag'
      if (vt === 'string') {
        const existing = positional[name] as string | undefined
        positional[name] = existing ? existing + ' ' + state.currentToken : state.currentToken
      } else if (repeatable) {
        const arr = (positional[name] as string[] | undefined) ?? []
        positional[name] = [...arr, state.currentToken]
      } else {
        positional[name] = state.currentToken
      }
    }
  }

  // Handle trailing flag without space (e.g. "--replace" typed but not yet followed by space)
  if (state.currentToken.startsWith('--') && def?.options) {
    const flagName = state.currentToken.slice(2)
    const opt = def.options.find((o) => o.name === flagName)
    if (opt && (opt.valueType ?? 'flag') === 'flag') {
      options[flagName] = true
    }
  }

  return { positional, options }
}
