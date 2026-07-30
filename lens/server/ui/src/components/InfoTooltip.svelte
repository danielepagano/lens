<script lang="ts">
  /**
   * Dashed-underline "?" info tooltip, tap/click-toggled (works on both mouse
   * and touch — hover-only tooltips never fire on touch devices).
   *
   * The panel is portaled to `document.body` (see `portal` below) and
   * positioned `fixed` from the trigger's measured rect. A plain nested
   * `position: fixed` descendant is NOT enough: flex/grid items paint as an
   * implicit stack ordered by DOM position (CSS Flexbox / Grid — this holds
   * even with z-index: auto), so a later sibling's plain, unpositioned
   * content still paints over an earlier sibling's entire subtree, including
   * an inner fixed + high-z-index tooltip. Moving the panel out of the flex
   * row entirely sidesteps that regardless of what layout a future caller
   * drops this into. It also lets the tooltip clamp itself inside the
   * viewport on narrow (mobile) screens instead of running off the right edge.
   */
  const TIP_WIDTH_PX = 208 // keep in sync with .info-tip max-width (13rem @ 16px root)
  const VIEWPORT_MARGIN_PX = 8

  function portal(node: HTMLElement) {
    document.body.appendChild(node)
    return {
      destroy() {
        node.remove()
      },
    }
  }

  let { label, text }: { label: string; text: string } = $props()

  let open = $state(false)
  let btnEl: HTMLButtonElement | null = $state(null)
  let tipEl: HTMLSpanElement | null = $state(null)
  let coords = $state({ top: 0, left: 0 })

  function position() {
    if (!btnEl) return
    const rect = btnEl.getBoundingClientRect()
    const maxLeft = window.innerWidth - TIP_WIDTH_PX - VIEWPORT_MARGIN_PX
    coords = {
      top: rect.bottom + 4,
      left: Math.max(VIEWPORT_MARGIN_PX, Math.min(rect.left, maxLeft)),
    }
  }

  function toggle() {
    open = !open
    if (open) position()
  }

  // Checked against this instance's own trigger/panel only -- a click on a
  // *different* InfoTooltip's trigger must still close this one, not just
  // clicks entirely outside all tooltip UI (otherwise open tooltips stack up).
  function handleWindowClick(e: MouseEvent) {
    if (!open) return
    const target = e.target as Node | null
    if (btnEl?.contains(target) || tipEl?.contains(target)) return
    open = false
  }

  function handleResize() {
    if (open) position()
  }
</script>

<svelte:window onclick={handleWindowClick} onresize={handleResize} />

<span class="info-tip-wrap">
  <button
    type="button"
    class="info-tip-btn"
    bind:this={btnEl}
    aria-expanded={open}
    onclick={toggle}
  >{label}</button>
</span>
{#if open}
  <span
    class="info-tip"
    role="tooltip"
    bind:this={tipEl}
    use:portal
    style="top: {coords.top}px; left: {coords.left}px;"
  >
    {text}
  </span>
{/if}

<style>
  .info-tip-wrap {
    display: inline-block;
  }
  .info-tip-btn {
    all: unset;
    font-size: inherit;
    color: inherit;
    opacity: 0.85;
    cursor: help;
    text-decoration: underline dashed;
    text-decoration-thickness: 1px;
    text-underline-offset: 3px;
  }
  .info-tip {
    position: fixed;
    width: max-content;
    max-width: 13rem;
    background: var(--pico-card-background-color, #222);
    color: var(--pico-color, #eee);
    border: 2px dotted var(--pico-muted-color);
    border-radius: 4px;
    padding: 0.35rem 0.5rem;
    font-size: 1rem;
    line-height: 1.3;
    z-index: 2000;
  }
</style>
