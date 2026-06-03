<script lang="ts">
  type Props = {
    visible?: boolean
    prevDisabled?: boolean
    nextDisabled?: boolean
    onPrev?: () => void
    onNext?: () => void
  }

  let {
    visible = true,
    prevDisabled = false,
    nextDisabled = false,
    onPrev = undefined,
    onNext = undefined,
  }: Props = $props()

  function handlePrevClick(event: MouseEvent) {
    event.stopPropagation()
    if (prevDisabled) return
    onPrev?.()
  }

  function handleNextClick(event: MouseEvent) {
    event.stopPropagation()
    if (nextDisabled) return
    onNext?.()
  }
</script>

{#if visible}
  <div class="vn-nav-zones">
    <button
      type="button"
      class={['vn-nav-zone', 'vn-nav-zone--prev', { 'is-disabled': prevDisabled }]}
      aria-label="Previous scene"
      aria-disabled={prevDisabled ? 'true' : 'false'}
      onclick={handlePrevClick}
    >
      <span class="vn-nav-chevron" aria-hidden="true">‹</span>
    </button>
    <button
      type="button"
      class={['vn-nav-zone', 'vn-nav-zone--next', { 'is-disabled': nextDisabled }]}
      aria-label="Next scene"
      aria-disabled={nextDisabled ? 'true' : 'false'}
      onclick={handleNextClick}
    >
      <span class="vn-nav-chevron" aria-hidden="true">›</span>
    </button>
  </div>
{/if}

<style>
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
</style>
