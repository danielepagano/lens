<script lang="ts">
  import type { VnChunkMediaKind } from '../../utils/vnPlaybackNav'

  type Props = {
    kind: VnChunkMediaKind
    onPick?: () => void
  }

  let { kind, onPick }: Props = $props()

  let label = $derived(
    kind === 'current' ? 'Replace scene media' : 'Attach scene media for this line'
  )

  function handleClick(event: MouseEvent) {
    event.stopPropagation()
    onPick?.()
  }
</script>

<button
  type="button"
  class="vn-scene-media"
  aria-label={label}
  title={label}
  onclick={handleClick}
>
  {#if kind === 'current'}
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M23 4v6h-6" />
      <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 15a9 9 0 0 0 14.85 3.36L23 14" />
    </svg>
  {:else}
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
    </svg>
  {/if}
</button>

<style>
  .vn-scene-media {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    padding: 0;
    margin: 0;
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 0.45rem;
    background: rgba(12, 14, 22, 0.55);
    color: rgba(255, 255, 255, 0.88);
    cursor: pointer;
    touch-action: manipulation;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(8px);
  }

  .vn-scene-media:hover {
    background: rgba(22, 26, 38, 0.72);
    color: #fff;
  }
</style>
