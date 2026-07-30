<script lang="ts">
  import { mediaCarouselRequest, mediaCompositeSession } from '../../stores/ui'
  import InfoTooltip from '../../components/InfoTooltip.svelte'
  import {
    buildChromakeyParams,
    defaultChromakeyOutputPath,
    round2,
    runChromakeyPreview,
    runChromakeySave,
    type ChromakeyOverrideInputs,
  } from './mediaCompositeHandlers'

  const TOOLTIPS = {
    key: 'Hex background color to key out (e.g. FF00FF). Auto-detected from the image corners if omitted.',
    coreTol:
      'Color-distance tolerance for the confident background core (auto-calibrated if omitted; the one worth hand-tuning).',
    residualThresh:
      'Edge alpha-blend fit tolerance. Unlike the others, this has a fixed default (10.0) rather than one calibrated per image — rarely needs changing.',
    // dilatePx: hidden -- see currentInputs() and the markup below.
    // 'Edge zone width in pixels around the background core (auto-scaled to resolution if omitted).',
  }

  let session = $derived($mediaCompositeSession)
  let busy = $derived(session?.status === 'previewing' || session?.status === 'saving')
  let outputPath = $derived(session ? defaultChromakeyOutputPath(session.path) : '')

  let keyInput = $state('')
  let coreTolInput = $state('')
  let residualThreshInput = $state('')
  // let dilatePxInput = $state('') -- hidden -- see currentInputs() below.
  let chromeless = $state(false)

  const FALLBACK_SWATCH = '#ff00ff'
  let keySwatch = $derived(
    /^#?[0-9a-fA-F]{6}$/.test(keyInput.trim())
      ? (keyInput.trim().startsWith('#') ? keyInput.trim() : `#${keyInput.trim()}`)
      : FALLBACK_SWATCH
  )
  function handleSwatchInput(e: Event) {
    keyInput = (e.currentTarget as HTMLInputElement).value
  }

  let seededForPath: string | null = null
  let syncedPreviewSeq = -1
  $effect(() => {
    if (!session) {
      seededForPath = null
      syncedPreviewSeq = -1
      return
    }
    if (session.path !== seededForPath) {
      seededForPath = session.path
      syncedPreviewSeq = -1
      keyInput = ''
      coreTolInput = ''
      residualThreshInput = ''
      chromeless = false
    }
    // A fresh preview landed: show what was actually used (auto or typed) in the boxes,
    // so clearing a box and re-previewing reverts it to the auto value, visibly.
    if (session.status === 'ready' && session.previewSeq !== syncedPreviewSeq) {
      syncedPreviewSeq = session.previewSeq
      keyInput = session.keyHex ?? ''
      coreTolInput = session.coreTol !== null ? String(round2(session.coreTol)) : ''
      residualThreshInput = session.residualThresh !== null ? String(session.residualThresh) : ''
    }
  })

  function close() {
    const returnToDir = session?.returnToDir ?? null
    mediaCompositeSession.set(null)
    if (returnToDir !== null) {
      mediaCarouselRequest.set({ mode: 'chromakey', dir: returnToDir })
    }
  }

  // A finished save has nothing left to do here — leaving a "Saved" button
  // behind just sits there inert, so close (or return to the browse carousel)
  // as soon as it lands.
  $effect(() => {
    if (session?.status === 'saved') close()
  })

  function currentInputs(): ChromakeyOverrideInputs {
    return {
      key: keyInput,
      coreTol: coreTolInput,
      residualThresh: residualThreshInput,
      // Never overridden -- the control is hidden (see markup below): a large
      // value blows up the morphology kernel and can peg the server CPU.
      dilatePx: '',
    }
  }

  function handlePreview() {
    if (!session || busy) return
    void runChromakeyPreview(buildChromakeyParams(session.path, currentInputs()))
  }

  function handleSave() {
    if (!session || busy || session.status !== 'ready') return
    void runChromakeySave()
  }
</script>

{#if session}
  <div
    class={['carousel-overlay', chromeless && 'carousel-image-only']}
    role="dialog"
    aria-modal="true"
    aria-label="Chromakey preview"
  >
    <div class="carousel-header">
      <div class="carousel-header-top">
        <span class="carousel-title">Chromakey — {session.path}</span>
        <button type="button" class="carousel-close" aria-label="Close" onclick={close}>✕</button>
      </div>
    </div>

    <div class="carousel-body">
      <div class="composite-controls">
        <div class="composite-field">
          <InfoTooltip label="Key" text={TOOLTIPS.key} />
          <div class="composite-key-row">
            <input
              type="text"
              placeholder="auto"
              bind:value={keyInput}
              disabled={busy}
              aria-label="Key"
            />
            <input
              type="color"
              class="composite-key-swatch"
              value={keySwatch}
              oninput={handleSwatchInput}
              disabled={busy}
              aria-label="Pick background color"
            />
          </div>
        </div>
        <div class="composite-field">
          <InfoTooltip label="Core tol" text={TOOLTIPS.coreTol} />
          <input
            type="text"
            inputmode="decimal"
            placeholder="auto"
            bind:value={coreTolInput}
            disabled={busy}
            aria-label="Core tol"
            data-testid="composite-core-tol-input"
          />
        </div>
        <div class="composite-field">
          <InfoTooltip label="Residual thresh" text={TOOLTIPS.residualThresh} />
          <input
            type="text"
            inputmode="decimal"
            placeholder="10.0"
            bind:value={residualThreshInput}
            disabled={busy}
            aria-label="Residual thresh"
          />
        </div>
        <!--
          Dilate px hidden: a large value blows up the morphology kernel
          (2 * dilate_px + 1 squared) and can peg the server CPU. See
          currentInputs() above -- it's never sent as an override, so the
          server always auto-scales it from the image resolution.
          <div class="composite-field">
            <InfoTooltip label="Dilate px" text={TOOLTIPS.dilatePx} />
            <input
              type="text"
              inputmode="numeric"
              placeholder="auto"
              bind:value={dilatePxInput}
              disabled={busy}
              aria-label="Dilate px"
            />
          </div>
        -->
        <button type="button" class="composite-preview-btn" onclick={handlePreview} disabled={busy}>
          {session.status === 'previewing' ? 'Previewing…' : 'Preview'}
        </button>
      </div>

      {#if session.error}
        <div class="carousel-error" role="alert">{session.error}</div>
      {/if}

      <div class="carousel-spotlight">
        {#if session.previewSrc}
          <!--
            No built-in "1:1 view" toggle here (deliberately): a second,
            in-app zoom mechanism stacked on top of the browser's own
            pinch/ctrl-scroll zoom just adds another button that can end up
            scrolled out of frame once the user zooms the page itself. This
            toggle only ever does one simple thing -- go full-bleed / go back
            -- identically on desktop and mobile; from there the user zooms
            with native gestures.
          -->
          <button
            type="button"
            class="composite-image-toggle"
            aria-label={chromeless ? 'Show controls' : 'Focus image'}
            aria-pressed={chromeless}
            onclick={() => {
              chromeless = !chromeless
            }}
          >
            <img src={session.previewSrc} alt="Chromakey preview" />
          </button>
          {#if chromeless}
            <button
              type="button"
              class="composite-chromeless-close"
              aria-label="Show controls"
              onclick={() => {
                chromeless = false
              }}
            >✕</button>
          {/if}
        {:else}
          <span class="carousel-spotlight-placeholder">Previewing…</span>
        {/if}
      </div>

      <div class="carousel-actions">
        {#if session.status === 'ready' || session.status === 'saving'}
          <span class="composite-saved-path">Saves as {outputPath}</span>
        {/if}
        <button
          type="button"
          class="action-primary"
          disabled={session.status !== 'ready'}
          onclick={handleSave}
        >
          {session.status === 'saving' ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* Not global (app.css) — Svelte scopes <style> per component, so this mirrors
     MediaCarouselHeader.svelte's rule rather than inheriting it. */
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
  /* Chromeless ("focus image") mode: app.css already hides .carousel-header
     for .carousel-overlay.carousel-image-only -- these two rows are specific
     to this component, so hide them here too. */
  .carousel-overlay.carousel-image-only .composite-controls,
  .carousel-overlay.carousel-image-only .carousel-actions {
    display: none;
  }
  .composite-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: flex-end;
    padding: 0.5rem 0.9rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .composite-field {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    font-size: 0.7rem;
    opacity: 0.85;
    margin: 0;
  }
  .composite-controls input {
    width: 4rem;
    height: 32px;
    font-size: 0.8rem;
    padding: 0.2rem 0.5rem;
    margin: 0;
  }
  .composite-key-row {
    display: flex;
    gap: 0.3rem;
  }
  .composite-key-row input[type='text'] {
    width: 4.5rem;
  }
  .composite-key-swatch {
    width: 32px !important;
    height: 32px;
    padding: 2px !important;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 4px;
    background: none;
    cursor: pointer;
  }
  .composite-preview-btn {
    height: 32px;
    padding: 0.2rem 0.6rem;
    margin: 0;
    font-size: 0.8rem;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid var(--pico-muted-border-color);
    background: transparent;
    color: inherit;
  }
  .composite-preview-btn:hover:not(:disabled) {
    background: var(--pico-secondary-background, #333);
  }
  .composite-preview-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .composite-saved-path {
    font-size: 0.78rem;
    opacity: 0.75;
    margin-right: auto;
  }
  .carousel-error {
    padding: 0.75rem 1rem;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
  }
  .composite-image-toggle {
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    cursor: zoom-in;
  }
  /* Chromeless: original pixel size, not scaled to fit -- scaled-down-then-
     browser-zoomed just magnifies interpolated pixels, useless for judging a
     chroma-key edge. Show it 1:1 and let the panel scroll (it's already
     overflow: auto, see .carousel-spotlight in app.css); start-aligned
     rather than centered so the top-left corner is reachable by scrolling
     (a centered flex item that overflows can strand its far edge). */
  .carousel-overlay.carousel-image-only .carousel-spotlight {
    align-items: flex-start;
    justify-content: flex-start;
  }
  .carousel-overlay.carousel-image-only .composite-image-toggle {
    width: auto;
    height: auto;
    cursor: zoom-out;
  }
  .carousel-overlay.carousel-image-only .composite-image-toggle img {
    max-width: none;
    max-height: none;
    width: auto;
    height: auto;
  }
  /* Escape exits chromeless too, but that's invisible on touch devices --
     mirrors MediaSpotlight.svelte's .spotlight-close for the same affordance.
     `fixed`, not `absolute`: the image at native size makes .carousel-spotlight
     scroll, and an absolutely positioned descendant scrolls right along with
     it -- fixed anchors to the viewport instead, so it stays put. */
  .composite-chromeless-close {
    position: fixed;
    top: 0.5rem;
    right: 0.5rem;
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
  }
  .composite-chromeless-close:hover {
    opacity: 1;
  }
</style>
