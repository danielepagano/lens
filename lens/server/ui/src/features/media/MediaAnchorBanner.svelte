<script lang="ts">
  type Props = {
    onConfirm?: () => void
  }

  let { onConfirm }: Props = $props()
</script>

<div class="carousel-anchor-banner">
  <button type="button" class="carousel-anchor-confirm" onclick={() => onConfirm?.()}
    >Use search as anchor</button
  >
</div>

<style>
  .carousel-anchor-banner {
    display: flex;
    padding: 0.4rem 0.9rem;
    background: var(--pico-mark-background-color, rgba(255, 200, 0, 0.15));
    flex-shrink: 0;
  }
  .carousel-anchor-confirm {
    width: 100%;
    margin: 0;
    font-size: 0.8rem !important;
    padding: 0.35rem 0.6rem !important;
    min-height: 34px !important;
  }
</style>
