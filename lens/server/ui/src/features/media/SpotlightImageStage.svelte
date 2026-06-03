<script lang="ts">
  import { onMount } from 'svelte'
  import { subscribeCoarsePointer } from '../../utils/coarsePointer'

  type Props = {
    imageSrc?: string
    filename?: string
    chromeless?: boolean
    onToggleChromeless?: () => void
  }

  let {
    imageSrc = '',
    filename = '',
    chromeless = false,
    onToggleChromeless = undefined,
  }: Props = $props()

  let imageFullRes = $state(false)
  let coarsePointer = $state(false)
  let imageStageEl = $state<HTMLDivElement | null>(null)

  onMount(() => {
    return subscribeCoarsePointer((coarse) => {
      coarsePointer = coarse
      if (coarse) imageFullRes = false
    })
  })

  $effect(() => {
    void imageSrc
    imageFullRes = false
  })

  function toggleImageFullRes() {
    imageFullRes = !imageFullRes
    if (imageFullRes) {
      requestAnimationFrame(() => {
        if (!imageStageEl) return
        imageStageEl.scrollTop = 0
        imageStageEl.scrollLeft = 0
      })
    }
  }

  function handleImageKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggleImageFullRes()
    } else if (e.key === 'Escape' && imageFullRes && !chromeless) {
      e.preventDefault()
      imageFullRes = false
    }
  }

  function handleChromelessButtonClick(event: MouseEvent) {
    event.stopPropagation()
    onToggleChromeless?.()
  }

  function handleChromelessWindowKey(e: KeyboardEvent) {
    if (!chromeless || e.key !== 'Escape') return
    if (imageFullRes) {
      imageFullRes = false
      e.preventDefault()
      return
    }
    onToggleChromeless?.()
    e.preventDefault()
  }
</script>

<svelte:window onkeydown={handleChromelessWindowKey} />

{#if !chromeless}
  <button
    type="button"
    class="spotlight-chromeless-btn"
    aria-label="Focus image — hide carousel"
    onclick={handleChromelessButtonClick}
  >⛶</button>
{/if}
{#if coarsePointer}
  <div class="spotlight-image-stage">
    <div class="spotlight-image-static">
      <img src={imageSrc} alt={filename} />
    </div>
  </div>
{:else}
  <div bind:this={imageStageEl} class={['spotlight-image-stage', { fullres: imageFullRes }]}>
    <button
      type="button"
      class="spotlight-image-btn"
      aria-label={imageFullRes ? 'Exit full resolution view' : 'View at full resolution'}
      aria-pressed={imageFullRes}
      onclick={toggleImageFullRes}
      onkeydown={handleImageKeyDown}
    >
      <img src={imageSrc} alt={filename} />
    </button>
  </div>
{/if}

<style>
  :global(.carousel-spotlight.spotlight-has-image) {
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    overflow: hidden;
    padding: 0px;
  }
  .spotlight-image-stage {
    flex: 1;
    min-height: 0;
    min-width: 0;
    width: 100%;
    display: flex;
    flex-direction: row;
    align-items: stretch;
    overflow: hidden;
  }
  .spotlight-image-static {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    width: 100%;
    align-self: stretch;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
  }
  .spotlight-image-static :global(img) {
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
    border-radius: 4px;
  }
  .spotlight-image-stage:not(.fullres) .spotlight-image-btn {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    width: 100%;
    align-self: stretch;
  }
  .spotlight-image-stage.fullres {
    flex-direction: row;
    align-items: flex-start;
    justify-content: flex-start;
    overflow: auto;
  }
  .spotlight-image-btn {
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: zoom-in;
    outline: none;
    border-radius: 4px;
  }
  .spotlight-image-btn:focus-visible {
    outline: 2px solid var(--pico-primary);
    outline-offset: 2px;
  }
  .spotlight-image-stage.fullres .spotlight-image-btn {
    max-width: none;
    max-height: none;
  }
  .spotlight-image-btn :global(img) {
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
    border-radius: 4px;
    cursor: zoom-in;
  }
  .spotlight-image-stage.fullres .spotlight-image-btn :global(img) {
    max-width: none;
    max-height: none;
    cursor: zoom-out;
  }
  .spotlight-chromeless-btn {
    position: absolute;
    top: 0.5rem;
    left: 0.5rem;
    background: rgba(0, 0, 0, 0.45);
    border: none;
    color: #fff;
    font-size: 1rem;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
    opacity: 0.75;
    line-height: 1;
    padding: 0;
  }
  .spotlight-chromeless-btn:hover {
    opacity: 1;
  }
</style>
