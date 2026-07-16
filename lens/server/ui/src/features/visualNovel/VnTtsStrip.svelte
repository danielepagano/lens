<script lang="ts">
  import { onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import {
    fetchTtsChunkAsBlob,
    postTtsRender,
    TtsStreamBusyError,
    type PlaybackItem,
    type PlaybackTextItem,
  } from '../../services/api'
  import type { VnTtsSettings } from '../../utils/vnTypes'
  import { markVnPlaybackChunkTtsCached, vnPlayback } from '../../stores/visualNovel'

  type Props = {
    nodeAddress: string
    line: number
    chunkId: string
    ttsCached: boolean | undefined
    ttsEnabled: boolean
    itemIndex?: number
    vnTts: VnTtsSettings
    onTtsEnded?: (() => void) | undefined
  }
  let {
    nodeAddress,
    line,
    chunkId,
    ttsCached,
    ttsEnabled,
    itemIndex = 0,
    vnTts,
    onTtsEnded,
  }: Props = $props()

  let audioEl: HTMLAudioElement | null = $state(null)
  let objectUrl = $state<string | null>(null)
  let playing = $state(false)
  let loadingFirstChunk = $state(false)
  let buttonBusy = $state(false)
  let fetchSeq = $state(0)
  let prevChunkIdentity = $state('')
  let prevPlaybackGate = $state('')
  let prevUserAutoAdvance = $state(false)
  let armedForEndedAdvance = $state(false)

  function cleanupAudio() {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
      objectUrl = null
    }
    if (audioEl) {
      audioEl.pause()
      audioEl.src = ''
    }
    playing = false
    armedForEndedAdvance = false
  }

  function nextTextChunkInItems(items: PlaybackItem[], afterIndex: number): PlaybackTextItem | null {
    for (let i = afterIndex + 1; i < items.length; i++) {
      const it = items[i]
      if (it.type === 'text') return it
    }
    return null
  }

  async function queueLookAheadRender() {
    if (!nodeAddress || !vnTts.speak || !vnTts.renderNew) return
    const data = get(vnPlayback)
    if (!data) return
    const next = nextTextChunkInItems(data.items, itemIndex)
    if (!next || next.tts_cached === true) return
    if (next.ai_gen === false) return
    markVnPlaybackChunkTtsCached(next.id)
    try {
      await postTtsRender(nodeAddress, { line: next.line, chunk_id: next.id })
    } catch {
      /* ignore */
    }
  }

  async function loadAndPlay(): Promise<boolean> {
    const seq = fetchSeq
    cleanupAudio()
    loadingFirstChunk = true
    buttonBusy = true
    try {
      const { blob, fromCache } = await fetchTtsChunkAsBlob(
        nodeAddress,
        {
          line,
          chunk_id: chunkId,
        },
        {
          onFirstAudioChunk: () => {
            if (fetchSeq === seq) loadingFirstChunk = false
          },
        },
      )
      if (fetchSeq !== seq) return false
      loadingFirstChunk = false
      if (!fromCache) {
        markVnPlaybackChunkTtsCached(chunkId)
      }
      objectUrl = URL.createObjectURL(blob)
      if (audioEl) {
        audioEl.src = objectUrl
        await audioEl.play()
        if (fetchSeq !== seq) return false
        playing = true
        armedForEndedAdvance = true
        void queueLookAheadRender()
      }
      return true
    } catch (e) {
      if (e instanceof TtsStreamBusyError) {
        /* leave quiet — user can retry */
      }
      return false
    } finally {
      if (fetchSeq === seq) {
        loadingFirstChunk = false
        buttonBusy = false
      }
    }
  }

  async function maybeAutoPlay() {
    if (!ttsEnabled || !nodeAddress || !vnTts.speak) return
    if (!vnTts.renderNew && ttsCached === false) return
    await loadAndPlay()
  }

  async function kickAutoplayForCurrentChunk() {
    if (!ttsEnabled || !nodeAddress || !chunkId || !vnTts.speak || !vnTts.autoAdvance) return
    if (!vnTts.renderNew && ttsCached === false) return
    if (playing) return

    if (!objectUrl) {
      await maybeAutoPlay()
      return
    }
    if (audioEl?.ended) {
      armedForEndedAdvance = false
      onTtsEnded?.()
      return
    }
    if (audioEl) {
      playing = true
      armedForEndedAdvance = true
      void audioEl.play().then(() => void queueLookAheadRender())
    }
  }

  const ttsAvailable = $derived(vnTts.speak || ttsCached === true)
  const manuallyPlayable = $derived(
    Boolean(nodeAddress) && !buttonBusy && ttsAvailable,
  )
  const chunkIdentity = $derived(`${line}:${chunkId}:${nodeAddress}:${vnTts.speak}`)
  const playbackGate = $derived(`${vnTts.renderNew}:${ttsCached}:${ttsEnabled}`)

  $effect(() => {
    const id = chunkIdentity
    const gate = playbackGate
    const auto = vnTts.autoAdvance

    if (id !== prevChunkIdentity) {
      fetchSeq = fetchSeq + 1
      loadingFirstChunk = false
      buttonBusy = false
      prevChunkIdentity = id
      prevPlaybackGate = gate
      prevUserAutoAdvance = auto
      cleanupAudio()
      if (nodeAddress && chunkId) void maybeAutoPlay()
      return
    }
    if (gate !== prevPlaybackGate) {
      prevPlaybackGate = gate
      if (nodeAddress && chunkId && !playing && !objectUrl) {
        void maybeAutoPlay()
      }
      return
    }
    if (auto !== prevUserAutoAdvance) {
      const enabling = auto && !prevUserAutoAdvance
      prevUserAutoAdvance = auto
      if (enabling && nodeAddress && chunkId) void kickAutoplayForCurrentChunk()
    }
  })

  async function togglePlay() {
    if (!manuallyPlayable) return
    if (playing && audioEl) {
      audioEl.pause()
      playing = false
      armedForEndedAdvance = false
      return
    }
    if (objectUrl && audioEl) {
      playing = true
      armedForEndedAdvance = true
      void audioEl.play().then(() => void queueLookAheadRender())
      return
    }
    await loadAndPlay()
  }

  function handleAudioEnded() {
    playing = false
    if (vnTts.speak && vnTts.autoAdvance && armedForEndedAdvance) {
      armedForEndedAdvance = false
      onTtsEnded?.()
    } else {
      armedForEndedAdvance = false
    }
  }

  onDestroy(() => {
    cleanupAudio()
  })
</script>

<div class={['vn-tts-vcr', { hidden: !ttsAvailable }]}>
  <button
    type="button"
    class={['vn-vcr-btn', { 'vn-vcr-btn--cached': ttsCached === true }]}
    onclick={togglePlay}
    disabled={!manuallyPlayable}
    aria-busy={buttonBusy ? 'true' : undefined}
    aria-label={loadingFirstChunk
      ? 'Loading audio'
      : buttonBusy
        ? 'Preparing playback'
        : playing
          ? 'Pause'
          : 'Play'}
  >
    {#if !buttonBusy && playing}
      <svg class="vn-vcr-svg" viewBox="0 0 14 14" aria-hidden="true">
        <rect x="3" y="2.5" width="3" height="9" rx="0.6" fill="currentColor" />
        <rect x="8" y="2.5" width="3" height="9" rx="0.6" fill="currentColor" />
      </svg>
    {:else if !buttonBusy}
      <svg class="vn-vcr-svg" viewBox="0 0 14 14" aria-hidden="true">
        <path fill="currentColor" d="M3.5 2.5L12 7 3.5 11.5V2.5z" />
      </svg>
    {/if}
  </button>
  <audio bind:this={audioEl} class="vn-tts-audio" onended={handleAudioEnded}></audio>
</div>

<style>
  .vn-tts-vcr.hidden {
    display: none;
  }

  .vn-tts-vcr {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    touch-action: manipulation;
  }

  .vn-vcr-btn {
    box-sizing: border-box;
    width: 1.85rem;
    height: 1.85rem;
    padding: 0;
    margin: 0;
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 5px;
    background: rgba(0, 0, 0, 0.4);
    color: rgba(255, 255, 255, 0.95);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .vn-vcr-btn--cached {
    border-color: rgba(132, 203, 255, 0.94);
    box-shadow: 0 0 0 1px rgba(132, 203, 255, 0.52);
  }

  .vn-vcr-svg {
    width: 0.95rem;
    height: 0.95rem;
    display: block;
  }

  .vn-vcr-btn:hover:not(:disabled) {
    background: rgba(40, 44, 56, 0.75);
    border-color: rgba(255, 255, 255, 0.42);
  }

  .vn-vcr-btn--cached:hover:not(:disabled) {
    border-color: rgba(160, 220, 255, 0.98);
    box-shadow: 0 0 0 1px rgba(160, 220, 255, 0.58);
  }

  .vn-vcr-btn:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .vn-vcr-btn--cached:disabled {
    opacity: 1;
  }

  .vn-vcr-btn[aria-busy='true']:disabled {
    opacity: 0.88;
  }

  .vn-tts-audio {
    display: none;
  }
</style>
