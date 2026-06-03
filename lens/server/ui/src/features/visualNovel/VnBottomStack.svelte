<script lang="ts">
  import type { PlaybackTextItem } from '../../services/api'
  import type { VnLineAttributionPill } from '../../utils/vnAttribution'
  import type { VnTtsSettings } from '../../utils/vnTypes'
  import VnTextFrame from './VnTextFrame.svelte'
  import Cli from '../../layout/Cli.svelte'

  type Props = {
    items: unknown[]
    textChunk: PlaybackTextItem | null
    textBeatIndex: number | null
    playbackIx: number
    atCursorCliBeat: boolean
    textFrameCollapsed: boolean
    ttsAvailable: boolean
    vnTts: VnTtsSettings
    nodeAddress: string
    playbackTtsEnabled: boolean
    vnLoading: boolean
    vnError: string | null
    lineAttribution: VnLineAttributionPill | null
    fallbackAttribution: VnLineAttributionPill | null
    onCliDone: (() => Promise<void>) | undefined
    navigate: ((addr: string) => Promise<void>) | undefined
    onTtsEnded: () => void
    onToggleCollapsed: () => void
  }

  let {
    items,
    textChunk,
    textBeatIndex,
    playbackIx,
    atCursorCliBeat,
    textFrameCollapsed,
    ttsAvailable,
    vnTts,
    nodeAddress,
    playbackTtsEnabled,
    vnLoading,
    vnError,
    lineAttribution,
    fallbackAttribution,
    onCliDone,
    navigate,
    onTtsEnded,
    onToggleCollapsed,
  }: Props = $props()
</script>

<div class="vn-bottom-stack">
  {#if textChunk}
    <VnTextFrame
      text={textChunk.text}
      aiGen={textChunk.ai_gen ?? true}
      collapsed={textFrameCollapsed}
      showTtsUi={ttsAvailable}
      {vnTts}
      {nodeAddress}
      line={textChunk.line}
      chunkId={textChunk.id}
      ttsCached={textChunk.tts_cached}
      {playbackTtsEnabled}
      itemIndex={textBeatIndex ?? playbackIx}
      {onTtsEnded}
      onToggleCollapsed={onToggleCollapsed}
      {lineAttribution}
      {fallbackAttribution}
    />
  {:else if atCursorCliBeat && onCliDone !== undefined && navigate !== undefined}
    <div class="vn-cli-in-scene">
      <Cli onCliDone={onCliDone} {navigate} />
    </div>
  {:else if items.length === 0 && !vnLoading && !vnError}
    <p class="vn-empty">Nothing to play back for this node.</p>
  {/if}
</div>

<style>
  .vn-bottom-stack {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    flex-shrink: 0;
    max-height: 42vh;
    touch-action: manipulation;
    overflow-y: auto;
    padding: 0 0.75rem;
    padding-bottom: calc(0.45rem + env(safe-area-inset-bottom, 0px));
    pointer-events: auto;
  }

  .vn-empty {
    margin: 0;
    padding: 1rem;
    color: #888;
    font-size: 0.9rem;
    text-align: center;
  }

  .vn-cli-in-scene :global(.bottom-bar) {
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(5, 5, 10, 0.92);
    backdrop-filter: blur(6px);
    z-index: 1;
    padding-left: 0;
    padding-right: 0;
  }
</style>
