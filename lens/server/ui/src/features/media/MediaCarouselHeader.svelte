<script lang="ts">
  type Crumb = { label: string; path: string }

  type Props = {
    title?: string
    breadcrumbs?: Crumb[]
    onClose?: () => void
    onNavigate?: (path: string) => void
  }

  let {
    title = '',
    breadcrumbs = [],
    onClose = undefined,
    onNavigate = undefined,
  }: Props = $props()
</script>

<div class="carousel-header">
  <div class="carousel-header-top">
    <span class="carousel-title">{title}</span>
    <button type="button" class="carousel-close" aria-label="Close" onclick={() => onClose?.()}>✕</button>
  </div>
  <nav class="carousel-path" aria-label="Folder path">
    <button type="button" onclick={() => onNavigate?.('')}>Root</button>
    {#each breadcrumbs as crumb (crumb.path)}
      <span aria-hidden="true"> / </span>
      <button type="button" onclick={() => onNavigate?.(crumb.path)}>{crumb.label}</button>
    {/each}
  </nav>
</div>

<style>
  .carousel-close {
    background: none;
    border: none;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 0.2rem 0.5rem;
    opacity: 0.7;
    min-height: 34px;
  }
  .carousel-close:hover {
    opacity: 1;
  }
</style>
