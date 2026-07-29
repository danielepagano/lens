<script lang="ts">
  import { onMount } from 'svelte'
  import { vnImageExplore, vnImageFitStep } from '../../stores/visualNovel'
  import { getMountFilePath } from '../../services/api'
  import { normalizeMountRelativePath } from '../../utils/mountPath'
  import { subscribeCoarsePointer } from '../../utils/coarsePointer'
  import VnNavZones from './VnNavZones.svelte'
  import VnStageMedia from './VnStageMedia.svelte'

  type Props = {
    url: string | null
    alt: string
    backdrop?: 'image' | 'video' | 'layered'
    fgUrl?: string
    fgAlt?: string
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
    fgUrl = undefined,
    fgAlt = '',
    blockBackgroundPointer = false,
    onPrev,
    onNext,
    prevDisabled = false,
    nextDisabled = false,
  }: Props = $props()

  let coarsePointer = $state(false)

  onMount(() =>
    subscribeCoarsePointer((coarse) => {
      coarsePointer = coarse
      if (coarse) vnImageFitStep.set(0)
    }),
  )

  let resolvedSrc = $derived(url ? getMountFilePath(normalizeMountRelativePath(url)) : '')
  let resolvedFgSrc = $derived(fgUrl ? getMountFilePath(normalizeMountRelativePath(fgUrl)) : '')
  let explore = $derived($vnImageExplore)
  let fitScroll = $derived(explore && $vnImageFitStep === 1 && !coarsePointer)

  let prevNavDisabled = $derived(prevDisabled || !onPrev)
  let nextNavDisabled = $derived(nextDisabled || !onNext)

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
    <VnNavZones
      visible={!explore}
      prevDisabled={prevNavDisabled}
      nextDisabled={nextNavDisabled}
      onPrev={onPrev}
      onNext={onNext}
    />
    {#if !explore}
      <button
        type="button"
        class="vn-chromeless-btn"
        aria-label={mediaFocusAriaLabel(backdrop)}
        onclick={(event) => {
          event.stopPropagation()
          enterExplore()
        }}
      >⛶</button>
    {:else}
      <button
        type="button"
        class="vn-explore-close"
        aria-label="Leave image exploration"
        onclick={(event) => {
          event.stopPropagation()
          exitExplore()
        }}
      >✕</button>
    {/if}
    <VnStageMedia
      {resolvedSrc}
      {alt}
      {backdrop}
      {resolvedFgSrc}
      {fgAlt}
      {explore}
      {fitScroll}
      {coarsePointer}
      onCycleFit={handleCycleFit}
    />
  </div>
{:else}
  <div class="vn-image-stage vn-image-stage--empty">
    <VnNavZones
      visible={!explore}
      prevDisabled={prevNavDisabled}
      nextDisabled={nextNavDisabled}
      onPrev={onPrev}
      onNext={onNext}
    />
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
  .vn-image-stage.block-bg-pointer:not(.explore) :global(.vn-image-hit) {
    pointer-events: none;
  }
  .vn-image-stage.fit-scroll {
    overflow: auto;
    align-items: flex-start;
    justify-content: flex-start;
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
  .vn-chromeless-btn,
  .vn-explore-close {
    top: 0.5rem;
    right: 0.5rem;
  }
  .vn-scene-placeholder {
    width: 100%;
    height: 100%;
    opacity: 0.35;
    background: linear-gradient(160deg, #1a1a22, #0a0a12);
  }
</style>
