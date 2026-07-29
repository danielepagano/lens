<script lang="ts">
  type Props = {
    resolvedSrc?: string
    alt?: string
    backdrop?: 'image' | 'video' | 'layered'
    resolvedFgSrc?: string
    fgAlt?: string
    explore?: boolean
    fitScroll?: boolean
    coarsePointer?: boolean
    onCycleFit?: () => void
  }

  let {
    resolvedSrc = '',
    alt = '',
    backdrop = 'image',
    resolvedFgSrc = '',
    fgAlt = '',
    explore = false,
    fitScroll = false,
    coarsePointer = false,
    onCycleFit = undefined,
  }: Props = $props()
</script>

{#if explore}
  {#if coarsePointer || backdrop === 'video' || backdrop === 'layered'}
    <div class="vn-image-hit vn-image-hit--coarse-explore">
      {#key resolvedSrc + resolvedFgSrc}
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
        {:else if backdrop === 'layered'}
          <div class="vn-layered-wrap contain">
            <img src={resolvedSrc} alt={alt} class="vn-layer-bg contain" draggable="false" />
            <img src={resolvedFgSrc} alt={fgAlt} class="vn-layer-fg" draggable="false" />
          </div>
        {:else}
          <img src={resolvedSrc} {alt} class="vn-scene-img contain" draggable="false" />
        {/if}
      {/key}
    </div>
  {:else}
    <button
      type="button"
      class={['vn-image-hit', { 'fit-scroll': fitScroll }]}
      aria-label="Cycle image fit"
      onclick={() => onCycleFit?.()}
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
    {#key resolvedSrc + resolvedFgSrc}
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
      {:else if backdrop === 'layered'}
        <div class="vn-layered-wrap">
          <img src={resolvedSrc} alt={alt} class="vn-layer-bg cover" draggable="false" />
          <img src={resolvedFgSrc} alt={fgAlt} class="vn-layer-fg" draggable="false" />
        </div>
      {:else}
        <img src={resolvedSrc} {alt} class={['vn-scene-img', 'cover']} draggable="false" />
      {/if}
    {/key}
  </div>
{/if}

<style>
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
    position: relative;
  }
  :global(.vn-image-stage.explore) .vn-image-hit:not(.fit-scroll) {
    position: relative;
    display: block;
  }
  :global(.vn-image-stage.explore) .vn-image-hit:not(.vn-image-hit--coarse-explore) {
    cursor: pointer;
  }
  :global(.vn-image-stage.explore.coarse-pointer) .vn-image-hit--coarse-explore {
    touch-action: pan-x pan-y pinch-zoom;
    cursor: default;
  }
  :global(.vn-image-stage.fit-scroll) .vn-image-hit {
    display: flex;
    overflow: auto;
    align-items: flex-start;
    justify-content: flex-start;
  }
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
  :global(.vn-image-stage.explore) .vn-scene-video.contain {
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
  :global(.vn-image-stage.explore) .vn-scene-img.contain {
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
  :global(.vn-image-stage.fit-scroll) .vn-scene-img.natural {
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

  /* Background+foreground composite scene. */
  .vn-layered-wrap {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .vn-layer-bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    object-position: center;
    pointer-events: none;
    user-select: none;
  }
  .vn-layer-bg.cover {
    object-fit: cover;
  }
  .vn-layer-bg.contain {
    object-fit: contain;
    background: #000;
  }
  .vn-layer-fg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    object-position: center;
    pointer-events: none;
    user-select: none;
  }
</style>
