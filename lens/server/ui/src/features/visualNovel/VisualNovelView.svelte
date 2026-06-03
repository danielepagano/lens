<script lang="ts">
  import { tick } from 'svelte'
  import { get } from 'svelte/store'
  import { currentAddress } from '../../stores/document'
  import { currentProject } from '../../stores/project'
  import { parsedHash } from '../../stores/parsedHash'
  import { stats } from '../../stores/stats'
  import {
    vnPlayback,
    vnLoading,
    vnError,
    vnImageExplore,
    vnPlaybackRefreshTrigger,
    vnPlaybackAnchor,
  } from '../../stores/visualNovel'
  import { isVNBackdropItem, type PlaybackItem, type PlaybackTextItem } from '../../services/api'
  import { quotePillHslVars } from '../../utils/markdown'
  import {
    resolveVisualNovelIndex,
    resolveVisualNovelTtsSettings,
    setVisualNovelHash,
  } from '../../utils/vnNavigate'
  import { buildLineAttributionByLine, type VnLineAttributionPill } from '../../utils/vnAttribution'
  import { vnCursorCliSlotEligible } from '../../utils/vnCursorCli'
  import {
    followingTextAfterImage,
    classifyVnTextChunkMedia,
    logicalStepToPlaybackIndex,
    navigateVnLogicalStep,
    vnLogicalStepCount,
  } from '../../utils/vnPlaybackNav'
  import { runVnPlaybackLoad, vnPlaybackFetchKey } from './vnPlaybackLoad'
  import VnImageStage from './VnImageStage.svelte'
  import VnSceneMediaButton from './VnSceneMediaButton.svelte'
  import VnBottomStack from './VnBottomStack.svelte'
  import { cliInputRequest, mediaCarouselRequest } from '../../stores/ui'

  type Props = {
    onCliDone?: (() => Promise<void>) | undefined
    navigate?: ((addr: string) => Promise<void>) | undefined
  }
  let { onCliDone, navigate }: Props = $props()

  let playbackFetchKey = $state<string | null>(null)
  let prevVirtualCli = $state(false)
  let textFrameCollapsed = $state(false)

  $effect(() => {
    if (!$parsedHash.vn) playbackFetchKey = null
  })

  $effect(() => {
    const ph = $parsedHash
    const addr = $currentAddress
    const proj = $currentProject
    const trig = $vnPlaybackRefreshTrigger
    if (!ph.vn || !addr || !proj) return
    const key = vnPlaybackFetchKey(addr, trig)
    if (playbackFetchKey === key) return
    playbackFetchKey = key
    void runVnPlaybackLoad(addr)
  })

  const items = $derived($vnPlayback?.items ?? [])
  const lineAttributionByLine = $derived(buildLineAttributionByLine(items, quotePillHslVars))
  const logicalStep = $derived(
    $parsedHash.vn && $currentProject && $currentAddress
      ? resolveVisualNovelIndex($parsedHash, $currentProject, $currentAddress)
      : 0,
  )
  const cursorCliSlot = $derived(vnCursorCliSlotEligible($stats, $currentAddress, items))
  const playbackIx = $derived(
    items.length > 0 ? logicalStepToPlaybackIndex(items, logicalStep, cursorCliSlot) : 0,
  )
  const sceneIx = $derived(items.length > 0 ? Math.min(playbackIx, items.length - 1) : 0)
  const currentItem = $derived(playbackIx < items.length ? (items[playbackIx] ?? null) : null)

  const textBeatIndex = $derived(
    currentItem?.type === 'text'
      ? playbackIx
      : currentItem && isVNBackdropItem(currentItem) && followingTextAfterImage(items, playbackIx)
        ? playbackIx + 1
        : null,
  )
  const textChunk = $derived(
    textBeatIndex !== null && items[textBeatIndex]?.type === 'text'
      ? (items[textBeatIndex] as PlaybackTextItem)
      : null,
  )
  const vnLineAttribution = $derived(
    textChunk ? lineAttributionByLine.get(textChunk.line) ?? null : null,
  )

  function fallbackAttributionLabel(
    textItem: PlaybackTextItem,
    chatSession: { ai_label?: string; human_label?: string } | null | undefined,
  ): string {
    const isAi = textItem.ai_gen ?? true
    const chatLabel = isAi ? chatSession?.ai_label : chatSession?.human_label
    if (chatLabel) return chatLabel
    return isAi ? 'narration' : 'user'
  }

  function buildFallbackAttribution(
    textItem: PlaybackTextItem,
    chatSession: { ai_label?: string; human_label?: string } | null | undefined,
  ): VnLineAttributionPill {
    const label = fallbackAttributionLabel(textItem, chatSession)
    const { accent, border } = quotePillHslVars(label)
    return {
      label,
      style: `--quote-pill-accent:${accent};--quote-pill-border:${border}`,
    }
  }

  const fallbackAttribution = $derived(
    textChunk ? buildFallbackAttribution(textChunk, $vnPlayback?.chat_session) : null,
  )

  function openVnSceneMedia() {
    const addr = $currentAddress
    if (!addr || textChunk === null || textBeatIndex === null) return
    const c = classifyVnTextChunkMedia(items, textBeatIndex)
    vnPlaybackAnchor.set({ address: addr, chunkId: textChunk.id })
    if (c.kind === 'current' && c.pairingImageLine !== undefined) {
      mediaCarouselRequest.set({
        mode: 'replace',
        dir: '',
        attachAddress: addr,
        replaceImageLine: c.pairingImageLine,
      })
    } else {
      mediaCarouselRequest.set({
        mode: 'attach',
        dir: '',
        attachAddress: addr,
        attachLine: textChunk.line,
      })
    }
  }

  const sceneMediaForFrame = $derived(
    $stats?.has_mount && textChunk !== null && textBeatIndex !== null
      ? classifyVnTextChunkMedia(items, textBeatIndex)
      : null,
  )

  function sceneMeta(
    list: PlaybackItem[],
    index: number,
  ): { url: string | null; alt: string; backdrop: 'image' | 'video' } {
    let url: string | null = null
    let alt = ''
    let backdrop: 'image' | 'video' = 'image'
    for (let i = 0; i <= index && i < list.length; i++) {
      const it = list[i]
      if (it && isVNBackdropItem(it)) {
        url = it.url
        alt = it.alt
        backdrop = it.type
      }
    }
    return { url, alt, backdrop }
  }

  const scene = $derived(sceneMeta(items, sceneIx))
  const vnTts = $derived(resolveVisualNovelTtsSettings($parsedHash))
  const atCursorCliBeat = $derived(
    cursorCliSlot && playbackIx === items.length && items.length > 0,
  )
  const vnMaxStep = $derived(Math.max(vnLogicalStepCount(items, cursorCliSlot) - 1, 0))
  const vnPrevDisabled = $derived(items.length < 1 || logicalStep <= 0)
  const vnNextDisabled = $derived(items.length < 1 || logicalStep >= vnMaxStep)

  $effect(() => {
    if (atCursorCliBeat && !prevVirtualCli) {
      prevVirtualCli = true
      void tick().then(() => cliInputRequest.set(''))
    } else if (!atCursorCliBeat) {
      prevVirtualCli = false
    }
  })

  function bump(delta: number) {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (!slug || !addr || !items.length) return
    const dir = delta > 0 ? 1 : -1
    const slot = vnCursorCliSlotEligible(get(stats), addr, items)
    const next = navigateVnLogicalStep(items, logicalStep, dir as -1 | 1, slot)
    const tts = resolveVisualNovelTtsSettings(get(parsedHash))
    setVisualNovelHash(slug, addr, next, tts)
  }

  function advance() {
    bump(1)
  }

  function isTextEntryTarget(target: EventTarget | null): boolean {
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement
    ) {
      return true
    }
    if (!(target instanceof Element)) return false
    if (target.closest('[contenteditable="true"]')) return true
    return false
  }

  function isInteractiveTarget(target: EventTarget | null): boolean {
    if (isTextEntryTarget(target)) return true
    if (!(target instanceof Element)) return false
    return Boolean(
      target.closest('button, a, summary, [role="button"], [role="link"]'),
    )
  }

  function toggleTextFrameCollapsed() {
    textFrameCollapsed = !textFrameCollapsed
  }

  function onGlobalKey(e: KeyboardEvent) {
    const t = e.target
    if (isTextEntryTarget(t)) return
    if ($vnImageExplore) return
    if (cursorCliSlot && playbackIx === items.length) return
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      bump(1)
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      bump(-1)
    } else if (isInteractiveTarget(t)) {
      return
    } else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      bump(1)
    }
  }
</script>

<svelte:window onkeydown={onGlobalKey} />

<div
  class={['vn-root', { explore: $vnImageExplore }]}
>
  {#if $vnLoading}
    <div class="vn-overlay-msg">Loading…</div>
  {:else if $vnError}
    <div class="vn-overlay-msg vn-overlay-error" role="alert">{$vnError}</div>
  {/if}

  <div class="vn-image-stage-wrap">
    <VnImageStage
      url={scene.url}
      alt={scene.alt || 'Scene'}
      backdrop={scene.backdrop}
      blockBackgroundPointer={cursorCliSlot && playbackIx === items.length}
      onPrev={() => bump(-1)}
      onNext={() => bump(1)}
      prevDisabled={vnPrevDisabled}
      nextDisabled={vnNextDisabled}
    />
    {#if sceneMediaForFrame && !$vnImageExplore}
      <div class="vn-scene-media-overlay">
        <VnSceneMediaButton kind={sceneMediaForFrame.kind} onPick={openVnSceneMedia} />
      </div>
    {/if}
  </div>

  {#if !$vnImageExplore}
    <VnBottomStack
      {items}
      {textChunk}
      {textBeatIndex}
      {playbackIx}
      {atCursorCliBeat}
      textFrameCollapsed={textFrameCollapsed}
      ttsAvailable={Boolean($stats?.tts_available)}
      {vnTts}
      nodeAddress={$currentAddress ?? ''}
      playbackTtsEnabled={$vnPlayback?.tts_enabled ?? false}
      vnLoading={$vnLoading}
      vnError={$vnError}
      lineAttribution={vnLineAttribution}
      fallbackAttribution={fallbackAttribution}
      {onCliDone}
      {navigate}
      onTtsEnded={advance}
      onToggleCollapsed={toggleTextFrameCollapsed}
    />
  {/if}
</div>

<style>
  .vn-image-stage-wrap {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
  }

  .vn-scene-media-overlay {
    position: absolute;
    top: 0;
    left: 0;
    z-index: 25;
    padding: 0.5rem;
    pointer-events: none;
  }

  .vn-scene-media-overlay :global(.vn-scene-media) {
    pointer-events: auto;
  }

  .vn-root {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
    position: relative;
    background: #050508;
  }

  .vn-root.explore {
    z-index: 240;
  }

  .vn-overlay-msg {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    background: rgba(5, 5, 10, 0.65);
    color: #ddd;
    font-size: 0.95rem;
    pointer-events: none;
  }

  .vn-overlay-error {
    color: var(--pico-del-color, #e05c5c);
    padding: 1rem;
    text-align: center;
  }
</style>
