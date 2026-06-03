<script lang="ts">
  /* global $props, $derived */
  import { quotePillHslVars } from '../../utils/markdown'
  import {
    parseAttributedPlaybackText,
    type VnLineAttributionPill,
  } from '../../utils/vnAttribution'
  import { stripForTts } from '../../utils/stripForTts'
  import type { VnTtsSettings } from '../../utils/vnTypes'
  import VnTtsStrip from './VnTtsStrip.svelte'

  type Props = {
    text: string
    aiGen?: boolean
    collapsed?: boolean
    showTtsUi?: boolean
    vnTts: VnTtsSettings
    nodeAddress?: string
    line?: number
    chunkId?: string
    ttsCached?: boolean
    playbackTtsEnabled?: boolean
    itemIndex?: number
    onTtsEnded?: (() => void) | undefined
    onToggleCollapsed?: (() => void) | undefined
    lineAttribution?: VnLineAttributionPill | null
    fallbackAttribution?: VnLineAttributionPill | null
  }

  let {
    text,
    aiGen = true,
    collapsed = false,
    showTtsUi = false,
    vnTts,
    nodeAddress = '',
    line = 0,
    chunkId = '',
    ttsCached = undefined,
    playbackTtsEnabled = false,
    itemIndex = 0,
    onTtsEnded = undefined,
    onToggleCollapsed = undefined,
    lineAttribution = null,
    fallbackAttribution = null,
  }: Props = $props()

  let parsedSelf = $derived(parseAttributedPlaybackText(text, quotePillHslVars))
  let parsed = $derived(
    parsedSelf ??
      (lineAttribution
        ? {
            label: lineAttribution.label,
            style: lineAttribution.style,
            body: stripForTts(text),
          }
        : null)
  )

  type VnTtsSegKind = 'text' | 'inline'
  type VnTtsSeg = { key: number; kind: VnTtsSegKind; text: string; className: string }

  const ATTRIBUTED_LINE_RE = /^(\s*(?:>\s*)+)\[([^\]]+)\]\s+(.*)$/s
  const TTS_MARKUP_RE = /(<\/?[a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*)*>)|(\[[a-z][a-z0-9-]*\])/gi

  type VnTtsStyleFlags = { italic?: boolean; bold?: boolean; size?: 'small' | 'large' }

  function wrapStyleForTagName(tagName: string): VnTtsStyleFlags {
    const t = tagName.toLowerCase()

    // These are heuristics, not an exhaustive or prescriptive tag list.
    // The only hard rule is: never render raw <...> tags; treat them as markup hints.
    if (t.includes('whisper') || t.includes('soft') || t.includes('quiet')) return { italic: true, size: 'small' }
    if (t.includes('loud') || t.includes('shout') || t.includes('yell')) return { bold: true, size: 'large' }
    if (t.includes('emphasis') || t.includes('emph') || t.includes('stress')) return { italic: true, bold: true }
    if (t.includes('slow') || t.includes('drawl')) return { italic: true, size: 'large' }
    if (t.includes('fast') || t.includes('quick') || t.includes('rapid')) return { italic: true, size: 'small' }
    if (t.includes('higher') || t.includes('high') || (t.includes('pitch') && !t.includes('low'))) return { italic: true, size: 'small' }
    if (t.includes('lower') || t.includes('low')) return { bold: true, size: 'large' }
    if (t.includes('build') || t.includes('intens')) return { bold: true, size: 'large' }
    if (t.includes('decrease') || t.includes('fade') || t.includes('calm')) return { italic: true, size: 'small' }
    if (t.includes('sing')) return { italic: true, size: 'large' }
    if (t.includes('laugh') || t.includes('giggle') || t.includes('chuckle')) return { italic: true, size: 'small' }

    // Fallback: unknown tags still become visibly "marked" without showing the tag.
    return { italic: true }
  }

  function stripLeadingBlockquoteMarks(line: string): string {
    let s = line
    while (s.trimStart().startsWith('>')) {
      const ix = s.indexOf('>')
      s = s.slice(ix + 1)
      if (s.startsWith(' ')) s = s.slice(1)
    }
    return s
  }

  function extractDisplayBody(source: string): string {
    const lines = source.split('\n')
    const first = lines[0] ?? ''
    const m = first.match(ATTRIBUTED_LINE_RE)
    if (m?.[3] !== undefined) {
      const firstRest = m[3]
      const rest = lines.slice(1).map(stripLeadingBlockquoteMarks)
      return [firstRest, ...rest].join('\n').trimEnd()
    }
    return lines.map(stripLeadingBlockquoteMarks).join('\n').trimEnd()
  }

  function classNameForWrapStack(stack: string[]): string {
    let italic = false
    let bold = false
    let size: 'small' | 'large' | null = null
    for (const t of stack) {
      const s = wrapStyleForTagName(t)
      italic ||= Boolean(s.italic)
      bold ||= Boolean(s.bold)
      if (s.size === 'large') size = 'large'
      else if (s.size === 'small' && size !== 'large') size = 'small'
    }
    const classes: string[] = []
    if (italic) classes.push('vn-tts-italic')
    if (bold) classes.push('vn-tts-bold')
    if (size === 'small') classes.push('vn-tts-small')
    if (size === 'large') classes.push('vn-tts-large')
    return classes.join(' ')
  }

  function normalizeAngleTagName(tag: string): string {
    const raw = tag.startsWith('</') ? tag.slice(2, -1) : tag.slice(1, -1)
    return raw.trim().replace(/\s+/g, ' ').toLowerCase()
  }

  function segmentTtsMarkup(source: string): VnTtsSeg[] {
    const segs: VnTtsSeg[] = []
    const stack: string[] = []
    let last = 0
    let key = 0

    for (const m of source.matchAll(TTS_MARKUP_RE)) {
      const i = m.index ?? 0
      if (i > last) {
        const text = source.slice(last, i)
        if (text) segs.push({ key: key++, kind: 'text', text, className: classNameForWrapStack(stack) })
      }

      const angle = m[1]
      const bracket = m[2]
      if (bracket) {
        // Inline [pause]-style tags are not helpful in the VN frame; omit them entirely.
      } else if (angle) {
        const isClose = angle.startsWith('</')
        const name = normalizeAngleTagName(angle)
        // Treat ALL <...> tags as non-rendered markup hints (not literal text).
        // Unknown tags still apply fallback styling via wrapStyleForTagName.
        if (isClose) {
          const ix = stack.lastIndexOf(name)
          if (ix !== -1) stack.splice(ix, stack.length - ix)
        } else {
          stack.push(name)
        }
      }
      last = i + (m[0]?.length ?? 0)
    }

    if (last < source.length) {
      const text = source.slice(last)
      if (text) segs.push({ key: key++, kind: 'text', text, className: classNameForWrapStack(stack) })
    }

    return segs
  }

  let displayBody = $derived(extractDisplayBody(text))
  let plainDisplay = $derived(stripForTts(text))
  let displaySegs = $derived(segmentTtsMarkup(displayBody))
  let plainSegs = $derived(segmentTtsMarkup(plainDisplay))
  let hasFallbackAttribution = $derived(fallbackAttribution !== null)
  let attributionControl = $derived(
    parsed
      ? { label: parsed.label, style: parsed.style, isFallback: false }
      : fallbackAttribution
        ? { label: fallbackAttribution.label, style: fallbackAttribution.style, isFallback: true }
        : null
  )
  let frameCollapsed = $derived(collapsed && attributionControl !== null)
  let frameStyle = $derived(parsed ? parsed.style : undefined)

  function handleToggleCollapsed() {
    onToggleCollapsed?.()
  }
</script>

<div class="vn-text-stack">
  {#if attributionControl || showTtsUi}
    <div
      class={['vn-text-topline', { 'vn-text-topline--plain': !parsed }]}
    >
      {#if attributionControl}
        <button
          type="button"
          class={['vn-attribution-btn', { 'vn-attribution-btn--fallback': attributionControl.isFallback }]}
          style={attributionControl.style}
          aria-expanded={!frameCollapsed}
          onclick={handleToggleCollapsed}
        >
          {attributionControl.label}
        </button>
      {:else}
        <span class="vn-topline-spacer" aria-hidden="true"></span>
      {/if}
      {#if showTtsUi}
        <div class="vn-topline-tts">
          <VnTtsStrip
            {nodeAddress}
            {line}
            chunkId={chunkId}
            {ttsCached}
            ttsEnabled={playbackTtsEnabled}
            {itemIndex}
            {vnTts}
            {onTtsEnded}
          />
        </div>
      {/if}
    </div>
  {/if}
  <div
    class={[
      'vn-text-frame',
      {
        'is-plain': !parsed,
        'is-user': !aiGen,
        'has-fallback-attribution': hasFallbackAttribution,
        'is-collapsed': frameCollapsed,
      },
    ]}
    style={frameStyle}
  >
    {#if !frameCollapsed}
      <div class="vn-body">
        {#each (parsed ? displaySegs : plainSegs) as seg (seg.key)}
          {#if seg.kind === 'inline'}
            <small class={`vn-inline-tag ${seg.className}`}><pre>{seg.text}</pre></small>
          {:else}
            <span class={seg.className}>{seg.text}</span>
          {/if}
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .vn-text-stack {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .vn-text-topline {
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: 0.35rem;
    /* Pull pill + VCR down so the pill straddles the frame’s top border */
    margin-bottom: -0.7rem;
    position: relative;
    z-index: 2;
    min-height: 0;
  }

  .vn-text-topline--plain .vn-topline-spacer {
    flex: 1;
    min-width: 0;
  }

  .vn-topline-tts {
    flex-shrink: 0;
    margin-left: auto;
  }

  .vn-attribution-btn {
    appearance: none;
    display: inline-block;
    align-self: flex-end;
    margin-left: 0.65rem;
    margin-bottom: 0;
    position: relative;
    z-index: 2;
    max-width: calc(100% - 5rem);
    touch-action: manipulation;
    padding: 0.12rem 0.5rem;
    border: 1px solid hsl(var(--quote-pill-border, 210 48% 42%));
    border-radius: 0.5rem;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.2;
    font-variant: small-caps;
    font-family: Verdana, Geneva, Tahoma, sans-serif;
    color: rgba(255, 255, 255, 0.94);
    background: hsl(var(--quote-pill-accent, 210 48% 34%));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
    cursor: pointer;
    text-align: left;
  }

  .vn-attribution-btn--fallback {
    background:
      linear-gradient(rgba(0, 0, 0, 0.42), rgba(0, 0, 0, 0.42)),
      hsl(var(--quote-pill-accent, 210 28% 24%));
    border-color: hsl(var(--quote-pill-border, 210 48% 42%) / 0.72);
    color: rgba(255, 255, 255, 0.5);
    font-style: italic;
    font-variant: normal;
    font-weight: 500;
    font-size: small;
    letter-spacing: 0.01em;
  }

  .vn-attribution-btn:hover {
    filter: brightness(1.05);
  }

  .vn-attribution-btn:focus {
    outline: none;
  }

  .vn-attribution-btn:focus-visible {
    outline: 1px solid hsl(var(--quote-pill-border, 210 48% 42%) / 0.65);
    outline-offset: 1px;
    box-shadow:
      0 0 0 2px rgba(5, 5, 10, 0.5),
      0 2px 10px rgba(0, 0, 0, 0.35);
  }

  .vn-text-frame {
    --vn-frame-bg: rgba(8, 10, 16, 0.33);
    --vn-frame-border-top: hsl(var(--quote-pill-border, 210 18% 32%) / 0.55);
    --vn-frame-font-family: inherit;
    --vn-frame-text-color: #fff;
    --vn-frame-text-shadow:
      0 0 1px rgba(0, 0, 0, 0.9),
      0 0 2px rgba(0, 0, 0, 0.82),
      0 0 2.75px rgba(0, 0, 0, 0.62);
    appearance: none;
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin: 0;
    touch-action: manipulation;
    /* Extra top room so the overlapped pill doesn’t crowd the first line */
    padding: 0.95rem 0.95rem 0.95rem;
    border: none;
    border-radius: 10px;
    text-align: left;
    background: var(--vn-frame-bg);
    box-shadow: 0 4px 28px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(10px);
    position: relative;
    z-index: 1;
    border-top: 2px solid var(--vn-frame-border-top);
    font: inherit;
    color: inherit;
  }

  .vn-text-frame.is-plain {
    border-top-color: rgba(255, 255, 255, 0.14);
  }

  .vn-text-frame.is-user {
    --vn-frame-bg: rgba(236, 240, 255, 0.66);
    --vn-frame-border-top: rgba(255, 255, 255, 0.9);
    --vn-frame-font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial,
      'Apple Color Emoji', 'Segoe UI Emoji';
    --vn-frame-text-color: rgba(22, 24, 32, 0.96);
    --vn-frame-text-shadow: 0 1px 0 rgba(255, 255, 255, 0.55);
    box-shadow: 0 6px 32px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(6px);
  }

  .vn-text-frame.is-collapsed {
    min-height: 0.55rem;
    padding: 0.42rem 0.95rem 0.24rem;
    overflow: hidden;
  }

  .vn-body {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.55;
    font-family: var(--vn-frame-font-family);
    color: var(--vn-frame-text-color);
    text-shadow: var(--vn-frame-text-shadow);
    white-space: pre-wrap;
  }


  .vn-body :global(.vn-tts-italic) {
    font-style: italic;
  }

  .vn-body :global(.vn-tts-bold) {
    font-weight: 700;
  }

  .vn-body :global(.vn-tts-small) {
    font-size: 0.92em;
  }

  .vn-body :global(.vn-tts-large) {
    font-size: 1.08em;
  }

  .vn-inline-tag {
    display: inline;
  }

  .vn-inline-tag pre {
    display: inline;
    margin: 0;
    padding: 0.05rem 0.25rem;
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.16);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 0.8em;
    line-height: 1.2;
    white-space: pre;
  }

  @media (pointer: coarse) {
    .vn-body {
      font-size: max(1.05rem, 20px);
    }

    .vn-attribution-btn {
      font-size: max(0.82rem, 16px);
    }
  }
</style>
