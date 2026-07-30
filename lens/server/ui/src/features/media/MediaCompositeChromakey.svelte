<script lang="ts">
  import { mediaCarouselRequest, mediaCompositeSession } from '../../stores/ui'
  import {
    buildChromakeyParams,
    defaultChromakeyOutputPath,
    runChromakeyPreview,
    runChromakeySave,
    type ChromakeyOverrideInputs,
  } from './mediaCompositeHandlers'

  const TOOLTIPS = {
    coreTol:
      'Color-distance tolerance for the confident background core (auto-calibrated if omitted; the one worth hand-tuning).',
    residualThresh:
      'Edge alpha-blend fit tolerance. Unlike the others, this has a fixed default (10.0) rather than one calibrated per image — rarely needs changing.',
    dilatePx: 'Edge zone width in pixels around the background core (auto-scaled to resolution if omitted).',
  }

  let session = $derived($mediaCompositeSession)
  let busy = $derived(session?.status === 'previewing' || session?.status === 'saving')
  let outputPath = $derived(session ? defaultChromakeyOutputPath(session.path) : '')

  let keyInput = $state('')
  let coreTolInput = $state('')
  let residualThreshInput = $state('')
  let dilatePxInput = $state('')

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
      dilatePxInput = ''
    }
    // A fresh preview landed: show what was actually used (auto or typed) in the boxes,
    // so clearing a box and re-previewing reverts it to the auto value, visibly.
    if (session.status === 'ready' && session.previewSeq !== syncedPreviewSeq) {
      syncedPreviewSeq = session.previewSeq
      coreTolInput = session.coreTol !== null ? String(session.coreTol) : ''
      residualThreshInput = session.residualThresh !== null ? String(session.residualThresh) : ''
      dilatePxInput = session.dilatePx !== null ? String(session.dilatePx) : ''
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
      dilatePx: dilatePxInput,
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
  <div class="carousel-overlay" role="dialog" aria-modal="true" aria-label="Chromakey preview">
    <div class="carousel-header">
      <div class="carousel-header-top">
        <span class="carousel-title">Chromakey — {session.path}</span>
        <button type="button" class="carousel-close" aria-label="Close" onclick={close}>✕</button>
      </div>
    </div>

    <div class="carousel-body">
      <div class="composite-controls">
        <label>
          Key
          <input type="text" placeholder="auto" bind:value={keyInput} disabled={busy} />
        </label>
        <label class="composite-field">
          <span class="composite-tip-wrap">
            <button type="button" class="composite-label-btn">Core tol</button>
            <span class="composite-tip" role="tooltip">{TOOLTIPS.coreTol}</span>
          </span>
          <input type="text" inputmode="decimal" placeholder="auto" bind:value={coreTolInput} disabled={busy} />
        </label>
        <label class="composite-field">
          <span class="composite-tip-wrap">
            <button type="button" class="composite-label-btn">Residual thresh</button>
            <span class="composite-tip" role="tooltip">{TOOLTIPS.residualThresh}</span>
          </span>
          <input
            type="text"
            inputmode="decimal"
            placeholder="10.0"
            bind:value={residualThreshInput}
            disabled={busy}
          />
        </label>
        <label class="composite-field">
          <span class="composite-tip-wrap">
            <button type="button" class="composite-label-btn">Dilate px</button>
            <span class="composite-tip" role="tooltip">{TOOLTIPS.dilatePx}</span>
          </span>
          <input type="text" inputmode="numeric" placeholder="auto" bind:value={dilatePxInput} disabled={busy} />
        </label>
        <button type="button" class="composite-preview-btn" onclick={handlePreview} disabled={busy}>
          {session.status === 'previewing' ? 'Previewing…' : 'Preview'}
        </button>
      </div>

      {#if session.error}
        <div class="carousel-error" role="alert">{session.error}</div>
      {/if}

      <div class="carousel-spotlight">
        {#if session.previewSrc}
          <img src={session.previewSrc} alt="Chromakey preview" />
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
  .composite-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: flex-end;
    padding: 0.5rem 0.9rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .composite-controls label {
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
  .composite-tip-wrap {
    position: relative;
    display: inline-block;
  }
  .composite-label-btn {
    all: unset;
    font-size: inherit;
    color: inherit;
    opacity: 0.85;
    cursor: help;
    text-decoration: underline dashed;
    text-decoration-thickness: 1px;
    text-underline-offset: 3px;
  }
  .composite-tip {
    visibility: hidden;
    opacity: 0;
    position: absolute;
    bottom: 100%;
    left: 0;
    margin-bottom: 0.3rem;
    width: max-content;
    max-width: 13rem;
    background: var(--pico-card-background-color, #222);
    color: var(--pico-color, #eee);
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 4px;
    padding: 0.35rem 0.5rem;
    font-size: 0.68rem;
    line-height: 1.3;
    z-index: 20;
    transition: opacity 0.1s ease;
    pointer-events: none;
  }
  /* :focus (not just :hover) so tapping the label works on touch devices. */
  .composite-label-btn:hover + .composite-tip,
  .composite-label-btn:focus + .composite-tip {
    visibility: visible;
    opacity: 1;
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
</style>
