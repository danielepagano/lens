<script lang="ts">
  /**
   * Normal: image/video fills stage height (full vertical); wider media clip on the sides.
   * Explore: ⛶ then tap cycles contain ↔ natural scroll (fine pointer only).
   * Coarse pointer: same chromeless mode, fitted image only; pinch-zoom, no tap-to-cycle.
   */
  import { onMount } from 'svelte'
  import { vnImageExplore, vnImageFitStep } from '../../stores/visualNovel'
  import { getMountFilePath } from '../../services/api'
  import { normalizeMountRelativePath } from '../../utils/mountPath'

  type Props = {
    url: string | null
    alt: string
    backdrop?: 'image' | 'video'
    blockBackgroundPointer?: boolean
    onPrev?: () => void
    onNext?: () => void
    prevDisabled?: boolean
    nextDisabled?: boolean
  }

  let {
    url,
    alt,
    backdrop = 'image',
    blockBackgroundPointer = false,
    onPrev,
    onNext,
    prevDisabled = false,
    nextDisabled = false,
  }: Props = $props()

  let coarsePointer = $state(
    typeof globalThis !== 'undefined' &&
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(pointer: coarse)').matches
  )

  onMount(() => {
    const mql = window.matchMedia('(pointer: coarse)')
    coarsePointer = mql.matches
    if (mql.matches) vnImageFitStep.set(0)
    const onChange = () => {
      coarsePointer = mql.matches
      if (mql.matches) vnImageFitStep.set(0)
    }
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  })

  let resolvedSrc = $derived(url ? getMountFilePath(normalizeMountRelativePath(url)) : '')
  let explore = $derived($vnImageExplore)
  let fitScroll = $derived(explore && $vnImageFitStep === 1 && !coarsePointer)

  let prevNavDisabled = $derived(prevDisabled || !onPrev)
  let nextNavDisabled = $derived(nextDisabled || !onNext)

  function handlePrev() {
    if (prevNavDisabled) return
    onPrev?.()
  }

  function handleNext() {
    if (nextNavDisabled) return
    onNext?.()
  }

  function enterExplore() {
    vnImageExplore.set(true)
    vnImageFitStep.set(0)
  }

  function exitExplore() {
    vnImageExplore.set(false)
    vnImageFitStep.set(0)
  }

  function mediaFocusAriaLabel(back: typeof backdrop): string {
    return back === 'video' ? 'Focus video' : 'Focus image'
  }

  function handleCycleFit() {
    vnImageFitStep.update((s) => (s + 1) % 2)
  }

  function handlePrevClick(event: MouseEvent) {
    event.stopPropagation()
    handlePrev()
  }

  function handleNextClick(event: MouseEvent) {
    event.stopPropagation()
    handleNext()
  }

  function handleEnterExploreClick(event: MouseEvent) {
    event.stopPropagation()
    enterExplore()
  }

  function handleExitExploreClick(event: MouseEvent) {
    event.stopPropagation()
    exitExplore()
  }
</script>

{#if url}
  <div
    class={[
      'vn-image-stage',
      {
        explore,
        'fit-scroll': fitScroll,
        'coarse-pointer': coarsePointer,
        'block-bg-pointer': blockBackgroundPointer,
      },
    ]}
  >
    {#if !explore}
      <div class="vn-nav-zones">
        <button
          type="button"
          class={['vn-nav-zone', 'vn-nav-zone--prev', { 'is-disabled': prevNavDisabled }]}
          aria-label="Previous scene"
          aria-disabled={prevNavDisabled ? 'true' : 'false'}
          onclick={handlePrevClick}
        >
          <span class="vn-nav-chevron" aria-hidden="true">‹</span>
        </button>
        <button
          type="button"
          class={['vn-nav-zone', 'vn-nav-zone--next', { 'is-disabled': nextNavDisabled }]}
          aria-label="Next scene"
          aria-disabled={nextNavDisabled ? 'true' : 'false'}
          onclick={handleNextClick}
        >
          <span class="vn-nav-chevron" aria-hidden="true">›</span>
        </button>
      </div>
    {/if}
    {#if !explore}
      <button
        type="button"
        class="vn-chromeless-btn"
        aria-label={mediaFocusAriaLabel(backdrop)}
        onclick={handleEnterExploreClick}
      >⛶</button>
    {:else}
      <button
        type="button"
        class="vn-explore-close"
        aria-label="Leave image exploration"
        onclick={handleExitExploreClick}
      >✕</button>
    {/if}
    {#if explore}
      {#if coarsePointer || backdrop === 'video'}
        <div class="vn-image-hit vn-image-hit--coarse-explore">
          {#key resolvedSrc}
            {#if backdrop === 'video'}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video
                src={resolvedSrc}
                class="vn-scene-video contain"
                controls
                playsinline
                preload="metadata"
                aria-label={alt}
              ></video>
            {:else}
              <img
                src={resolvedSrc}
                {alt}
                class="vn-scene-img contain"
                draggable="false"
              />
            {/if}
          {/key}
        </div>
      {:else}
        <button
          type="button"
          class={['vn-image-hit', { 'fit-scroll': fitScroll }]}
          aria-label="Cycle image fit"
          onclick={handleCycleFit}
        >
          <img
            src={resolvedSrc}
            {alt}
            class={['vn-scene-img', { contain: !fitScroll, natural: fitScroll }]}
            draggable="false"
          />
        </button>
      {/if}
    {:else}
      <div class="vn-image-hit">
        {#key resolvedSrc}
          {#if backdrop === 'video'}
            <video
              src={resolvedSrc}
              class="vn-scene-video cover"
              muted
              loop
              autoplay
              playsinline
              preload="metadata"
              aria-label={alt}
            ></video>
          {:else}
            <img
              src={resolvedSrc}
              {alt}
              class={['vn-scene-img', 'cover']}
              draggable="false"
            />
          {/if}
        {/key}
      </div>
    {/if}
  </div>
{:else}
  <div class="vn-image-stage vn-image-stage--empty">
    {#if !explore}
      <div class="vn-nav-zones">
        <button
          type="button"
          class={['vn-nav-zone', 'vn-nav-zone--prev', { 'is-disabled': prevNavDisabled }]}
          aria-label="Previous scene"
          aria-disabled={prevNavDisabled ? 'true' : 'false'}
          onclick={handlePrevClick}
        >
          <span class="vn-nav-chevron" aria-hidden="true">‹</span>
        </button>
        <button
          type="button"
          class={['vn-nav-zone', 'vn-nav-zone--next', { 'is-disabled': nextNavDisabled }]}
          aria-label="Next scene"
          aria-disabled={nextNavDisabled ? 'true' : 'false'}
          onclick={handleNextClick}
        >
          <span class="vn-nav-chevron" aria-hidden="true">›</span>
        </button>
      </div>
    {/if}
    <div class="vn-scene-placeholder" aria-hidden="true"></div>
  </div>
{/if}

<style>
  .vn-image-stage {
    flex: 1;
    min-height: 0;
    position: relative;
    z-index: 1;
    background: #0a0a0a;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    padding: 0;
    margin: 0;
    width: 100%;
  }

  .vn-image-stage--empty {
    cursor: default;
  }

  .vn-image-stage.block-bg-pointer:not(.explore) .vn-image-hit {
    pointer-events: none;
  }

  .vn-image-stage.fit-scroll {
    overflow: auto;
    align-items: flex-start;
    justify-content: flex-start;
  }

  .vn-nav-zones {
    position: absolute;
    inset: 0;
    z-index: 12;
    pointer-events: none;
  }

  .vn-nav-zone {
    position: absolute;
    top: 12%;
    bottom: 12%;
    width: 38%;
    padding: 0;
    margin: 0;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.18);
    cursor: pointer;
    touch-action: manipulation;
    pointer-events: auto;
    opacity: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    user-select: none;
    outline: none;
    -webkit-tap-highlight-color: transparent;
    appearance: none;
    -webkit-appearance: none;
    box-shadow: none;
  }

  .vn-nav-zone.is-disabled {
    cursor: default;
    pointer-events: none;
  }

  .vn-nav-zone.is-disabled .vn-nav-chevron {
    opacity: 0.12;
  }

  .vn-nav-zone--prev {
    left: 0;
    padding-left: max(14px, env(safe-area-inset-left, 0px));
    justify-content: flex-start;
  }

  .vn-nav-zone--next {
    right: 0;
    padding-right: max(14px, env(safe-area-inset-right, 0px));
    justify-content: flex-end;
  }

  .vn-nav-chevron {
    font-size: 3rem;
    line-height: 1;
    opacity: 0.65;
    text-shadow: 0 0 14px rgba(0, 0, 0, 0.35);
  }

  .vn-nav-zone:focus,
  .vn-nav-zone:focus-visible,
  .vn-nav-zone:active {
    outline: none !important;
    box-shadow: none !important;
  }

  .vn-chromeless-btn,
  .vn-explore-close {
    position: absolute;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: none;
    background: rgba(0, 0, 0, 0.45);
    color: #fff;
    font-size: 1rem;
    line-height: 1;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 15;
    opacity: 0.75;
  }

  .vn-chromeless-btn:hover,
  .vn-explore-close:hover {
    opacity: 1;
  }

  .vn-chromeless-btn {
    top: 0.5rem;
    right: 0.5rem;
  }

  .vn-explore-close {
    top: 0.5rem;
    right: 0.5rem;
  }

  .vn-image-hit {
    flex: 1;
    min-height: 0;
    align-self: stretch;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    padding: 0;
    margin: 0;
    border: none;
    background: transparent;
    font: inherit;
    color: inherit;
    cursor: default;
  }

  .vn-image-stage.explore .vn-image-hit:not(.fit-scroll) {
    position: relative;
    display: block;
  }

  .vn-image-stage.explore .vn-image-hit:not(.vn-image-hit--coarse-explore) {
    cursor: pointer;
  }

  .vn-image-stage.explore.coarse-pointer .vn-image-hit--coarse-explore {
    touch-action: pan-x pan-y pinch-zoom;
    cursor: default;
  }

  .vn-image-stage.fit-scroll .vn-image-hit {
    display: flex;
    overflow: auto;
    align-items: flex-start;
    justify-content: flex-start;
  }

  /* Same fit as .vn-scene-img.cover: full height, intrinsic width; sides clip when wider */
  .vn-scene-video.cover {
    display: block;
    width: auto;
    max-width: none;
    height: 100%;
    max-height: 100%;
    flex-shrink: 0;
    border: none;
    pointer-events: none;
    user-select: none;
    background: #000;
  }

  .vn-image-stage.explore .vn-scene-video.contain {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    object-fit: contain;
    object-position: center;
    pointer-events: auto;
    user-select: none;
    border: none;
    background: #000;
  }

  .vn-scene-img.cover {
    display: block;
    width: auto;
    max-width: none;
    height: 100%;
    max-height: 100%;
    flex-shrink: 0;
    pointer-events: none;
    user-select: none;
  }

  .vn-image-stage.explore .vn-scene-img.contain {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    object-fit: contain;
    object-position: center;
    pointer-events: none;
    user-select: none;
  }

  .vn-image-stage.fit-scroll .vn-scene-img.natural {
    position: relative;
    width: auto;
    height: auto;
    max-width: none;
    max-height: none;
    object-fit: none;
    margin: 0;
    display: block;
    pointer-events: none;
    user-select: none;
  }

  .vn-scene-placeholder {
    width: 100%;
    height: 100%;
    opacity: 0.35;
    background: linear-gradient(160deg, #1a1a22, #0a0a12);
  }
</style>
