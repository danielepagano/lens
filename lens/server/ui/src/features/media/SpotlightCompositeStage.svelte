<script lang="ts">
  import { onMount } from 'svelte'

  type Props = {
    bgSrc?: string
    fgSrc?: string
  }

  let { bgSrc = '', fgSrc = '' }: Props = $props()

  let stageEl = $state<HTMLDivElement | null>(null)
  let bgEl = $state<HTMLImageElement | null>(null)
  // The foreground has to sit exactly over the background's *rendered* box
  // (object-fit: contain may letterbox it either way), which CSS alone
  // can't express without knowing the container's pixel size up front —
  // so it's measured from the actual laid-out bg element instead, the same
  // idea as `.lens-vn-composite` in app.css but computed at preview time
  // rather than baked into a fixed-width reading-mode column.
  let fgBox = $state<{ top: number; left: number; height: number } | null>(null)

  function updateFgBox() {
    if (!bgEl || !stageEl) {
      fgBox = null
      return
    }
    const bgRect = bgEl.getBoundingClientRect()
    const stageRect = stageEl.getBoundingClientRect()
    if (bgRect.width === 0 || bgRect.height === 0) {
      fgBox = null
      return
    }
    fgBox = {
      top: bgRect.top - stageRect.top,
      left: bgRect.left - stageRect.left + bgRect.width / 2,
      height: bgRect.height,
    }
  }

  $effect(() => {
    void bgSrc
    void fgSrc
    fgBox = null
  })

  onMount(() => {
    const ro = new ResizeObserver(updateFgBox)
    if (bgEl) ro.observe(bgEl)
    return () => ro.disconnect()
  })
</script>

<div class="spotlight-composite-stage" bind:this={stageEl}>
  <img
    bind:this={bgEl}
    src={bgSrc}
    alt=""
    class="spotlight-composite-bg"
    onload={updateFgBox}
  />
  {#if fgBox}
    <img
      src={fgSrc}
      alt=""
      class="spotlight-composite-fg"
      style="top: {fgBox.top}px; left: {fgBox.left}px; height: {fgBox.height}px;"
      onload={updateFgBox}
    />
  {/if}
</div>

<style>
  /* `.carousel-spotlight.spotlight-has-image` (column layout, no padding)
     is declared globally in SpotlightImageStage.svelte, which is always
     bundled alongside this component and applies to the same class
     regardless of which of the two stages is actually rendered. */
  .spotlight-composite-stage {
    position: relative;
    flex: 1;
    min-height: 0;
    min-width: 0;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  .spotlight-composite-bg {
    display: block;
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    border-radius: 4px;
  }
  .spotlight-composite-fg {
    position: absolute;
    width: auto;
    max-width: none;
    transform: translateX(-50%);
    pointer-events: none;
  }
</style>
