<script lang="ts">
  import { quotePillHslVars } from '../../utils/markdown'
  import {
    parseAttributedPlaybackText,
    type VnLineAttributionPill,
  } from '../../utils/vnAttribution'
  import { stripForTts } from '../../utils/stripForTts'
  import type { VnTtsSettings } from '../../utils/vnTypes'
  import { extractDisplayBody, segmentTtsMarkup } from '../../utils/vnTtsMarkup'
  import VnTextTopline from './VnTextTopline.svelte'

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
  // Auto-generate (renderNew) is meant to voice the companion, not every AI-written
  // word: `aiGen` alone also covers narration prose written in the same operator
  // turn as the companion's line, and `with_line_mode: direct` means the other
  // party's attributed line is aiGen=false anyway. Restricting to attributed
  // dialogue lines is what actually narrows it to "the companion speaks."
  let autoVoiceEligible = $derived(aiGen && parsedSelf !== null)
  let parsed = $derived(
    parsedSelf ??
      (lineAttribution
        ? {
            label: lineAttribution.label,
            style: lineAttribution.style,
            body: stripForTts(text),
          }
        : null),
  )

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
        : null,
  )
  let frameCollapsed = $derived(collapsed && attributionControl !== null)
  let frameStyle = $derived(parsed ? parsed.style : undefined)
</script>

<div class="vn-text-stack">
  <VnTextTopline
    {attributionControl}
    {frameCollapsed}
    {showTtsUi}
    {vnTts}
    {nodeAddress}
    {line}
    {chunkId}
    {ttsCached}
    {playbackTtsEnabled}
    {autoVoiceEligible}
    {itemIndex}
    {onTtsEnded}
    onToggleCollapsed={onToggleCollapsed}
    isPlain={!parsed}
  />
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
  }
</style>
