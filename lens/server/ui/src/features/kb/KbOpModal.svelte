<script lang="ts">
  /**
   * A `[kb-op …]: #` block, read as itself.
   *
   * `KbDiffModal` and `KbPendingDiff` both need a live proposal (base vs.
   * proposed) to show anything, and away from the cursor there isn't one —
   * materialization leaves the block in the node but the pending layer that
   * would diff it is gone. This renders the block's own fields instead, which
   * is what survives on a historical node: not what changed, but what the beat
   * *asked for*. Shape mirrors `KbDiffModal` (dialog + store-driven $effect);
   * see that file before changing this one.
   */
  import { kbOpRequest } from '../../stores/ui'
  import { currentProject } from '../../stores/project'
  import { currentAddress, pendingKb } from '../../stores/document'
  import { kbOpGlyph, kbOpLabel } from '../../utils/kbPending'
  import { kbViewerHashBase, openKbItemInHash } from './kbViewerMarkdown'
  import KbOpPatchView from './KbOpPatchView.svelte'

  let dialog: HTMLDialogElement | undefined

  const op = $derived($kbOpRequest)
  const hashBase = $derived(kbViewerHashBase($currentProject, $currentAddress ?? ''))

  /**
   * Whether this block is still a proposal, which the verb cannot answer: an
   * `add` on a closed session's node has landed just as surely as the
   * `applied` record beside it, and telling the reader to hand-edit a block
   * that no longer feeds anything is worse than saying nothing at all.
   *
   * The pending layer is what knows. The store carries it for whichever node
   * is in view and is null off the cursor, which is the common case for a
   * block old enough to be worth reading this way.
   */
  const pending = $derived(
    op !== null &&
      op.op !== 'applied' &&
      ($pendingKb?.ops ?? []).some((o) => o.line_start === op.lineStart),
  )

  $effect(() => {
    if (!dialog) return

    if (op) {
      if (!dialog.open) {
        dialog.showModal()
      }
      return
    }

    if (dialog.open) {
      dialog.close()
    }
  })

  function handleClose() {
    kbOpRequest.set(null)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }

  /** A KB id inside the modal opens the object and gets out of the way. */
  function openId(id: string) {
    openKbItemInHash(hashBase, id)
    kbOpRequest.set(null)
  }
</script>

<dialog
  bind:this={dialog}
  class="kb-op-dialog"
  onclose={handleClose}
  onclick={handleBackdropClick}
>
  {#if op}
    <article class="kb-op-article">
      <header class="kb-op-header">
        <strong class="kb-op-title">
          <span class="kb-op-title-glyph">{kbOpGlyph(op.op)}</span>
          {kbOpLabel(op.op)}{#if op.id}&nbsp;—
            <button type="button" class="kb-op-link" onclick={() => openId(op.id)}>{op.id}</button>
          {/if}
          <span class="kb-op-state" class:kb-op-state--pending={pending}>
            {pending ? 'proposed' : 'written'}
          </span>
        </strong>
        <button type="button" class="kb-op-close" onclick={handleClose} aria-label="Close">✕</button>
      </header>

      <div class="kb-op-body">
        <dl class="kb-op-fields">
          {#if op.id}
            <dt>id</dt>
            <dd><button type="button" class="kb-op-link" onclick={() => openId(op.id)}>{op.id}</button></dd>
          {/if}
          {#if op.at}
            <dt>at</dt>
            <dd>{op.at}</dd>
          {/if}
          {#if op.session}
            <dt>session</dt>
            <dd>{op.session}</dd>
          {/if}
          <dt>node line</dt>
          <dd>
            {op.lineStart} —
            {#if pending}
              hand-edit the <code>[kb-op …]: #</code> block there to change this proposal
            {:else if op.op === 'applied'}
              the <code>[kb-op …]: #</code> block recording what the close wrote
            {:else}
              where the block sits. Nothing is pending here any more, so editing it
              changes nothing.
            {/if}
          </dd>
        </dl>

        {#if op.op === 'add'}
          {#if op.body !== null}
            <!-- Body may hold a ROT13 `ai:secret` block (encode_ai_secrets_for_persist,
                 lens/core/annotations.py); it is meant to render as gibberish here. -->
            <pre class="kb-op-pre">{op.body}</pre>
          {/if}
        {:else if op.op === 'patch'}
          {#each op.patches as patch, i (i)}
            <KbOpPatchView {patch} index={i} />
          {/each}
        {:else if op.op === 'tag'}
          <div class="kb-op-pills">
            {#each op.tags as tag (tag)}
              <span class="kb-op-pill kb-op-pill--add">+{tag}</span>
            {/each}
            {#each op.removeTags as tag (tag)}
              <span class="kb-op-pill kb-op-pill--remove">-{tag}</span>
            {/each}
          </div>
        {:else if op.op === 'applied'}
          {#if op.ids.length > 0}
            <div class="kb-op-applied-group">
              <div class="kb-op-selector-label">Written</div>
              <ul class="kb-op-id-list">
                {#each op.ids as id (id)}
                  <li><button type="button" class="kb-op-link" onclick={() => openId(id)}>{id}</button></li>
                {/each}
              </ul>
            </div>
          {/if}
          {#if op.removed.length > 0}
            <div class="kb-op-applied-group">
              <div class="kb-op-selector-label">Deleted</div>
              <ul class="kb-op-id-list">
                {#each op.removed as id (id)}
                  <li><button type="button" class="kb-op-link" onclick={() => openId(id)}>{id}</button></li>
                {/each}
              </ul>
            </div>
          {/if}
        {:else if op.op === 'remove'}
          <p class="kb-op-note">
            {pending ? 'This session proposes deleting' : 'This session deleted'}
            <strong>{op.id}</strong>.
          </p>
        {/if}

        <details class="kb-op-raw">
          <summary>Block as written</summary>
          <pre class="kb-op-pre">{op.raw}</pre>
        </details>
      </div>
    </article>
  {/if}
</dialog>

<style>
  .kb-op-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .kb-op-article {
    margin: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .kb-op-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
    flex-shrink: 0;
  }

  .kb-op-title {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    min-width: 0;
  }

  /* The one thing a reader has to know before anything else in here: is this
   * still going to happen, or did it already? */
  .kb-op-state {
    padding: 0.05rem 0.35rem;
    border-radius: 999px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--pico-muted-color);
    background: color-mix(in srgb, var(--pico-muted-color) 14%, transparent);
  }

  .kb-op-state--pending {
    color: var(--explain-series-2);
    background: color-mix(in srgb, var(--explain-series-2) 18%, transparent);
  }

  .kb-op-title-glyph {
    font-family: var(--pico-font-family-monospace, monospace);
    color: var(--pico-muted-color);
  }

  .kb-op-close {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    width: auto;
    margin: 0;
    color: var(--pico-muted-color);
  }

  .kb-op-close:hover {
    color: var(--pico-color);
  }

  .kb-op-body {
    padding: 0.75rem 1rem;
    overflow-y: auto;
    overflow-x: hidden;
    flex: 1;
  }

  .kb-op-fields {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.2rem 0.75rem;
    margin: 0 0 0.75rem;
    font-size: 0.82rem;
  }

  .kb-op-fields dt {
    color: var(--pico-muted-color);
    font-weight: 600;
  }

  .kb-op-fields dd {
    margin: 0;
  }

  .kb-op-link {
    background: none;
    border: none;
    padding: 0;
    color: var(--pico-primary);
    text-decoration: underline;
    cursor: pointer;
    font: inherit;
  }

  .kb-op-link:hover {
    color: var(--pico-primary-hover);
  }

  .kb-op-pre {
    margin: 0;
    padding: 0.5rem 0.6rem;
    font-size: 0.82rem;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--pico-code-background-color, var(--pico-background-color));
    border-radius: var(--pico-border-radius);
  }

  .kb-op-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }

  .kb-op-pill {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-family: var(--pico-font-family-monospace, monospace);
  }

  .kb-op-pill--add {
    color: #27ae60;
    background: rgba(39, 174, 96, 0.15);
  }

  .kb-op-pill--remove {
    color: #c0392b;
    background: rgba(192, 57, 43, 0.15);
  }

  .kb-op-applied-group {
    margin-bottom: 0.5rem;
  }

  .kb-op-selector-label {
    font-size: 0.72rem;
    color: var(--pico-muted-color);
  }

  .kb-op-id-list,
  .kb-op-id-list li {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .kb-op-id-list li::marker {
    content: '';
  }

  .kb-op-note {
    font-size: 0.85rem;
  }

  .kb-op-raw {
    margin-top: 0.75rem;
    font-size: 0.8rem;
  }

  .kb-op-raw summary {
    cursor: pointer;
    color: var(--pico-muted-color);
  }

  .kb-op-raw .kb-op-pre {
    margin-top: 0.4rem;
  }
</style>
