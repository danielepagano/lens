<script lang="ts">
  import { get } from 'svelte/store'
  import { stats } from '../stores/stats'
  import { currentAddress } from '../stores/document'
  import { currentProject } from '../stores/project'
  import { parsedHash } from '../stores/parsedHash'
  import { mediaCarouselRequest, transactionResult } from '../stores/ui'
  import { narrativePin } from '../services/api'
  import { setVisualNovelHash, resolveVisualNovelIndex, resolveVisualNovelTtsSettings } from '../utils/vnNavigate'
  import { readVnSession, writeVnSession } from '../utils/vnSessionStorage'
  import type { VnTtsSettings } from '../utils/vnTypes'

  type Props = {
    open?: boolean
    onClose?: () => void
  }

  let { open = false, onClose }: Props = $props()

  let dialog: HTMLDialogElement | undefined

  $effect(() => {
    if (!dialog) return
    if (open) {
      if (!dialog.open) dialog.showModal()
    } else if (dialog.open) {
      dialog.close()
    }
  })

  function handleClose() {
    onClose?.()
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }

  // ---- Text-to-speech (VN playback preference, client-side / URL-encoded) ----

  const vnTts = $derived(open ? resolveVisualNovelTtsSettings($parsedHash) : null)

  function applyVnTts(next: VnTtsSettings) {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (!slug || !addr) return
    const ix = resolveVisualNovelIndex(get(parsedHash), slug, addr)
    setVisualNovelHash(slug, addr, ix, next)
    const prev = readVnSession()
    if (prev?.projectSlug === slug && prev?.nodeAddress === addr) {
      writeVnSession({
        version: 2,
        projectSlug: slug,
        nodeAddress: addr,
        logicalStep: ix,
        settings: { ...next },
      })
    }
  }

  function toggleSpeak() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (cur.speak) {
      applyVnTts({ speak: false, autoAdvance: false, renderNew: false })
    } else {
      applyVnTts({ ...cur, speak: true })
    }
  }

  function toggleAutoAdvance() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (!cur.speak) return
    applyVnTts({ ...cur, autoAdvance: !cur.autoAdvance })
  }

  function toggleRenderNew() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (!cur.speak) return
    applyVnTts({ ...cur, renderNew: !cur.renderNew })
  }

  // ---- Server-persisted modality toggles (front matter at /@cursor) ----

  async function setModalityEnabled(modalityId: string, value: boolean): Promise<void> {
    try {
      const result = await narrativePin({
        kind: 'modality',
        operation: 'set',
        modality_id: modalityId,
        key: 'enabled',
        value,
        node: '/@cursor',
      })
      if (result.status !== 'ok') {
        transactionResult.set({ title: 'Pin error', message: result.detail ?? 'Unknown error' })
      }
    } catch (err) {
      transactionResult.set({
        title: 'Pin error',
        message: err instanceof Error ? err.message : String(err),
      })
    }
  }

  // media_attach: deliberately not tied to whichever address a VN player
  // might currently be showing — always the actual project cursor. Absent
  // from the dict entirely means "toggle off, anchor unset" (see
  // docs/design.md modality resolution).
  const mediaAttachAtCursor = $derived($stats?.modalities_at_cursor?.media_attach ?? null)
  const mediaAttachEnabled = $derived(
    mediaAttachAtCursor !== null && mediaAttachAtCursor.config.enabled !== false
  )
  const mediaAttachAnchor = $derived(
    typeof mediaAttachAtCursor?.config.anchor === 'string' ? mediaAttachAtCursor.config.anchor : ''
  )

  function openAnchorPicker() {
    onClose?.()
    mediaCarouselRequest.set({
      mode: 'anchor',
      dir: '',
      searchQuery: mediaAttachAnchor || 'facets!',
    })
  }

  const speechMarkupAtCursor = $derived($stats?.modalities_at_cursor?.speech_markup ?? null)
  const speechMarkupEnabled = $derived(
    speechMarkupAtCursor !== null && speechMarkupAtCursor.config.enabled !== false
  )
</script>

<dialog bind:this={dialog} class="modes-dialog" onclose={handleClose} onclick={handleBackdropClick}>
  {#if open}
    <article class="modes-article">
      <header class="modes-header">
        <strong>Scene Modes</strong>
        <button type="button" class="modes-close" aria-label="Close" onclick={handleClose}>✕</button>
      </header>

      {#if $stats?.tts_available && vnTts}
        <section class="modes-section">
          <h4>Text-to-Speech</h4>
          <label class="modes-row">
            <span>Speak passages aloud</span>
            <input type="checkbox" role="switch" checked={vnTts.speak} onchange={toggleSpeak} />
          </label>
          {#if vnTts.speak}
            <label class="modes-row">
              <span>Auto-advance when speech ends</span>
              <input type="checkbox" role="switch" checked={vnTts.autoAdvance} onchange={toggleAutoAdvance} />
            </label>
            <label class="modes-row">
              <span>Auto-generate companion speech</span>
              <input type="checkbox" role="switch" checked={vnTts.renderNew} onchange={toggleRenderNew} />
            </label>
            <p class="modes-hint">Voices the companion's lines only — narration and your own lines need manual play.</p>
          {/if}
        </section>

        <section class="modes-section">
          <h4>Speech Markup</h4>
          <label class="modes-row">
            <span>Insert TTS markup during generation</span>
            <input
              type="checkbox"
              role="switch"
              checked={speechMarkupEnabled}
              onchange={() => void setModalityEnabled('speech_markup', !speechMarkupEnabled)}
            />
          </label>
        </section>
      {/if}

      {#if $stats?.has_mount}
        <section class="modes-section">
          <h4>Auto-Attach Media</h4>
          <label class="modes-row">
            <span>Auto-attach at cursor</span>
            <input
              type="checkbox"
              role="switch"
              checked={mediaAttachEnabled}
              onchange={() => void setModalityEnabled('media_attach', !mediaAttachEnabled)}
            />
          </label>
          {#if mediaAttachEnabled}
            <button type="button" class="modes-anchor-btn" onclick={openAnchorPicker}>
              {mediaAttachAnchor ? `Anchor: ${mediaAttachAnchor}` : 'Set anchor search…'}
            </button>
          {/if}
        </section>
      {/if}
    </article>
  {/if}
</dialog>

<style>
  .modes-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }
  .modes-article {
    width: min(92vw, 420px);
    padding: 0.85rem 1rem;
  }
  .modes-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.5rem;
    font-size: 0.95rem;
  }
  .modes-close {
    background: none;
    border: none;
    font-size: 1rem;
    padding: 0.1rem 0.4rem;
    cursor: pointer;
    color: inherit;
    opacity: 0.75;
  }
  .modes-close:hover {
    opacity: 1;
  }
  .modes-section {
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .modes-section:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }
  .modes-section h4 {
    margin: 0 0 0.35rem 0;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    opacity: 0.6;
  }
  .modes-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin: 0 0 0.4rem 0;
    font-size: 0.88rem;
  }
  .modes-row:last-child {
    margin-bottom: 0;
  }
  .modes-row input[type='checkbox'] {
    flex-shrink: 0;
    margin: 0;
  }
  .modes-hint {
    margin: -0.15rem 0 0.4rem 0;
    font-size: 0.72rem;
    opacity: 0.65;
  }
  .modes-anchor-btn {
    width: 100%;
    font-size: 0.8rem;
    padding: 0.35rem 0.6rem;
    min-height: 34px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
