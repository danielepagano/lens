<script lang="ts">
  import { tick } from 'svelte'

  // Native <select> popups mis-render inside <dialog> on mobile — the option
  // list opens as a tiny box pinned near the top-left of the viewport instead
  // of under the control. This renders its own listbox (same approach as
  // CliHistoryDrawer) so dropdowns behave the same everywhere.

  type Option = { value: string; label: string }

  // Callers size the trigger from their own stylesheet with
  // `.their-row :global(.select-menu-trigger) { … }`.
  type Props = {
    value: string
    options: Option[]
    onChange: (value: string) => void
    ariaLabel?: string
    disabled?: boolean
  }

  let { value, options, onChange, ariaLabel, disabled = false }: Props = $props()

  let open = $state(false)
  let menuStyle = $state('')
  let triggerEl = $state<HTMLButtonElement | null>(null)
  let menuEl = $state<HTMLDivElement | null>(null)

  const selectedLabel = $derived(options.find((o) => o.value === value)?.label ?? '')

  const GAP = 4
  const EDGE = 8
  const MIN_DROP = 140
  const MIN_WIDTH = 140

  // Fixed positioning (measured off the trigger) rather than an absolutely
  // positioned child: the menu then can't be clipped by a scrolling dialog
  // body, and still paints inside the dialog's top layer.
  //
  // The menu sizes to its widest option (at least as wide as the trigger, at
  // most the viewport) so long labels are not clipped. `max-content` rather
  // than plain shrink-to-fit: a shrink-to-fit fixed box is measured against
  // the space left of its own `left`, so its width and position would chase
  // each other. The measured width is only known after it renders, so
  // openMenu() places it a second time once it is on screen.
  function place() {
    if (!triggerEl) return
    const r = triggerEl.getBoundingClientRect()
    const below = window.innerHeight - r.bottom - GAP - EDGE
    const above = r.top - GAP - EDGE
    const dropUp = below < MIN_DROP && above > below
    const maxHeight = Math.max(96, Math.min(300, dropUp ? above : below))
    const maxWidth = window.innerWidth - 2 * EDGE
    const width = Math.min(menuEl?.offsetWidth ?? Math.max(r.width, MIN_WIDTH), maxWidth)
    // Right-align to the trigger when a left-aligned menu would run off screen.
    const left = Math.max(
      EDGE,
      r.left + width > window.innerWidth - EDGE ? r.right - width : r.left
    )
    const vertical = dropUp
      ? `bottom:${Math.round(window.innerHeight - r.top + GAP)}px`
      : `top:${Math.round(r.bottom + GAP)}px`
    menuStyle =
      `${vertical};left:${Math.round(left)}px;width:max-content` +
      `;min-width:${Math.round(Math.max(r.width, MIN_WIDTH))}px;max-width:${Math.round(maxWidth)}px` +
      `;max-height:${Math.round(maxHeight)}px`
  }

  // preventScroll + manual scrollTop: a plain focus() makes the browser reveal
  // the option in *every* scrollable ancestor, which scrolls the dialog behind
  // the menu — and that scroll would immediately dismiss the menu.
  function focusOption(el: HTMLElement | null | undefined) {
    if (!el || !menuEl) return
    el.focus({ preventScroll: true })
    const bottom = el.offsetTop + el.offsetHeight
    if (el.offsetTop < menuEl.scrollTop) menuEl.scrollTop = el.offsetTop
    else if (bottom > menuEl.scrollTop + menuEl.clientHeight) {
      menuEl.scrollTop = bottom - menuEl.clientHeight
    }
  }

  async function openMenu() {
    if (disabled) return
    place()
    open = true
    await tick()
    place()
    const current = menuEl?.querySelector<HTMLButtonElement>('[aria-selected="true"]')
    focusOption(current ?? menuEl?.querySelector<HTMLButtonElement>('.select-menu-option'))
  }

  function closeMenu(refocus = true) {
    if (!open) return
    open = false
    if (refocus) triggerEl?.focus()
  }

  function pick(next: string) {
    closeMenu()
    if (next !== value) onChange(next)
  }

  function moveFocus(from: HTMLElement, delta: number) {
    if (!menuEl) return
    const items = [...menuEl.querySelectorAll<HTMLButtonElement>('.select-menu-option')]
    const ix = items.indexOf(from as HTMLButtonElement)
    focusOption(items[Math.min(items.length - 1, Math.max(0, ix + delta))])
  }

  function handleMenuKeydown(e: KeyboardEvent) {
    const target = e.target as HTMLElement
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveFocus(target, 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveFocus(target, -1)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      closeMenu()
    } else if (e.key === 'Tab') {
      closeMenu(false)
    }
  }

  function handleTriggerKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      void openMenu()
    }
  }

  $effect(() => {
    if (!open) return
    const onPointerDown = (e: Event) => {
      const t = e.target as Node
      if (menuEl?.contains(t) || triggerEl?.contains(t)) return
      closeMenu(false)
    }
    // The menu is placed from the trigger's rect, so it has to follow the
    // trigger when anything moves — and only give up once the trigger is off
    // screen. (Dismissing on any scroll is not an option: focusing an option
    // makes the surrounding dialog emit one, which would close the menu the
    // instant it opened.)
    const onReflow = () => {
      if (!triggerEl) return
      const r = triggerEl.getBoundingClientRect()
      if (r.bottom < 0 || r.top > window.innerHeight) closeMenu(false)
      else place()
    }
    window.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('resize', onReflow)
    window.addEventListener('scroll', onReflow, true)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('resize', onReflow)
      window.removeEventListener('scroll', onReflow, true)
    }
  })
</script>

<button
  bind:this={triggerEl}
  type="button"
  class="select-menu-trigger"
  aria-haspopup="listbox"
  aria-expanded={open}
  aria-label={ariaLabel}
  {disabled}
  onclick={() => (open ? closeMenu() : void openMenu())}
  onkeydown={handleTriggerKeydown}
>
  <span class="select-menu-label">{selectedLabel}</span>
  <!-- viewBox hugs the glyph (rather than a square box the chevron sits low
       in) so flex centring lands it on the label's optical middle. -->
  <svg class="select-menu-caret" viewBox="0 0 12 8" aria-hidden="true" focusable="false">
    <path d="M1 1.5L6 6.5L11 1.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</button>

{#if open}
  <div
    bind:this={menuEl}
    class="select-menu-list"
    role="listbox"
    aria-label={ariaLabel}
    tabindex="-1"
    style={menuStyle}
    onkeydown={handleMenuKeydown}
  >
    {#each options as opt (opt.value)}
      <button
        type="button"
        class="select-menu-option"
        role="option"
        aria-selected={opt.value === value}
        onclick={() => pick(opt.value)}
      >
        {opt.label}
      </button>
    {/each}
  </div>
{/if}

<style>
  /* Pico's button rule rebinds --pico-color / --pico-background-color to the
     primary-button palette, so these must be re-pointed at the form-element
     tokens — this control stands in for a <select>, not for a button. */
  .select-menu-trigger,
  .select-menu-option {
    --pico-color: var(--pico-form-element-color);
    --pico-background-color: var(--pico-form-element-background-color);
    box-shadow: none;
    font-weight: normal;
  }

  .select-menu-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
    width: auto;
    margin: 0;
    padding: 0.2rem 0.5rem;
    min-height: 32px;
    font-size: 0.82rem;
    line-height: 1.2;
    text-align: left;
    color: var(--pico-color);
    background: var(--pico-background-color);
    border: 1px solid var(--pico-form-element-border-color);
    border-radius: 4px;
    cursor: pointer;
  }

  .select-menu-trigger:disabled {
    cursor: default;
    opacity: 0.5;
  }

  .select-menu-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .select-menu-caret {
    flex: 0 0 auto;
    width: 0.95em;
    height: auto;
    opacity: 0.75;
  }

  .select-menu-list {
    position: fixed;
    box-sizing: border-box;
    z-index: 400;
    overflow-y: auto;
    padding: 0.15rem 0;
    background: var(--pico-form-element-background-color);
    border: 1px solid var(--pico-form-element-border-color);
    border-radius: 4px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
  }

  .select-menu-option {
    display: block;
    width: 100%;
    margin: 0;
    padding: 0.45rem 0.6rem;
    text-align: left;
    font-size: 0.85rem;
    line-height: 1.3;
    color: var(--pico-color);
    background: none;
    border: none;
    border-radius: 0;
    cursor: pointer;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .select-menu-option:hover,
  .select-menu-option:focus {
    background: var(--pico-secondary-hover-background, var(--pico-muted-border-color));
    color: var(--pico-secondary-inverse, var(--pico-form-element-color));
    outline: none;
  }

  .select-menu-option[aria-selected='true'] {
    font-weight: 600;
  }
</style>
