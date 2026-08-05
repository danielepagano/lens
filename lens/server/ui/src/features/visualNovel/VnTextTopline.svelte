<script lang="ts">
  import type { VnTtsSettings } from '../../utils/vnTypes'
  import VnTtsStrip from './VnTtsStrip.svelte'

  type AttributionControl = {
    label: string
    style?: string
    isFallback: boolean
  }

  type Props = {
    attributionControl?: AttributionControl | null
    frameCollapsed?: boolean
    showTtsUi?: boolean
    vnTts?: VnTtsSettings
    nodeAddress?: string
    line?: number
    chunkId?: string
    ttsCached?: boolean
    playbackTtsEnabled?: boolean
    autoVoiceEligible?: boolean
    itemIndex?: number
    onTtsEnded?: (() => void) | undefined
    onToggleCollapsed?: (() => void) | undefined
    isPlain?: boolean
  }

  let {
    attributionControl = null,
    frameCollapsed = false,
    showTtsUi = false,
    vnTts,
    nodeAddress = '',
    line = 0,
    chunkId = '',
    ttsCached = undefined,
    playbackTtsEnabled = false,
    autoVoiceEligible = true,
    itemIndex = 0,
    onTtsEnded = undefined,
    onToggleCollapsed = undefined,
    isPlain = false,
  }: Props = $props()
</script>

{#if attributionControl || showTtsUi}
  <div class={['vn-text-topline', { 'vn-text-topline--plain': isPlain }]}>
    {#if attributionControl}
      <button
        type="button"
        class={['vn-attribution-btn', { 'vn-attribution-btn--fallback': attributionControl.isFallback }]}
        style={attributionControl.style}
        aria-expanded={!frameCollapsed}
        onclick={() => onToggleCollapsed?.()}
      >
        {attributionControl.label}
      </button>
    {:else}
      <span class="vn-topline-spacer" aria-hidden="true"></span>
    {/if}
    {#if showTtsUi && vnTts}
      <div class="vn-topline-tts">
        <VnTtsStrip
          {nodeAddress}
          {line}
          {chunkId}
          {ttsCached}
          ttsEnabled={playbackTtsEnabled}
          {autoVoiceEligible}
          {itemIndex}
          {vnTts}
          {onTtsEnded}
        />
      </div>
    {/if}
  </div>
{/if}

<style>
  .vn-text-topline {
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: 0.35rem;
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
  @media (pointer: coarse) {
    .vn-attribution-btn {
      font-size: max(0.82rem, 16px);
    }
  }
</style>
