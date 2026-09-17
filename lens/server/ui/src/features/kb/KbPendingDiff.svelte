<script lang="ts">
  /**
   * The proposal standing over the object the viewer is showing.
   *
   * A pending change is a property of the object you are already looking at,
   * not a thing to interrupt you with, so this renders in place — no modal, no
   * second click. `KbDiffModal` stays where it is for the legacy ` ```kb `
   * fence path; this one works from the `base`/`proposed` pair the node route
   * already serves, which is correct for patches, tags and removals and not
   * only for whole bodies.
   *
   * Nothing shows when the viewer's id has no proposal, which is the usual
   * case — and away from the cursor there are never any, because the layer
   * itself follows the cursor.
   */
  import { pendingKb } from '../../stores/document'
  import { computeLineDiff, type DiffLine } from '../../utils/lineDiff'
  import { KB_CHANGE_LABEL, kbOpGlyph, opsForId, pendingObjectFor } from '../../utils/kbPending'

  type Props = { id: string }

  let { id }: Props = $props()

  const object = $derived(pendingObjectFor($pendingKb, id))
  /** Ops stack, so several of them can add up to one changed object. */
  const ops = $derived(opsForId($pendingKb, id))
  const failing = $derived(ops.filter((op) => op.status === 'error'))
  /**
   * A creation and a removal have only one side, and `''.split('\n')` is one
   * empty line, not none — so diffing against `''` would invent a stray `-` (or
   * `+`) row. Build the one-sided case directly instead.
   */
  const diffLines = $derived.by((): DiffLine[] => {
    if (!object) return []
    if (object.base === null) {
      return (object.proposed ?? '').split('\n').map((text) => ({ kind: 'insert', text }))
    }
    if (object.proposed === null) {
      return object.base.split('\n').map((text) => ({ kind: 'delete', text }))
    }
    return computeLineDiff(object.base, object.proposed)
  })
  const headline = $derived.by(() => {
    if (!object) return ''
    const parts = [KB_CHANGE_LABEL[object.change]]
    if (object.base_source) parts.push(`over ${object.base_source}`)
    return parts.join(' · ')
  })
</script>

{#if object}
  <details
    class="kb-pending"
    class:kb-pending--error={failing.length > 0}
    data-testid="kb-pending-diff"
    open
  >
    <summary class="kb-pending-summary">
      <span class="kb-pending-badge">{failing.length > 0 ? 'Proposal failing' : 'Proposed'}</span>
      <span class="kb-pending-headline">{headline}</span>
    </summary>
    <div class="kb-pending-body">
      <ul class="kb-pending-ops">
        {#each ops as op (op.index)}
          <li class:kb-pending-op--error={op.status === 'error'}>
            <span class="kb-pending-op-glyph">{kbOpGlyph(op.op)}</span>
            <span class="kb-pending-op-what">{op.op} — {op.summary}</span>
            <span class="kb-pending-op-line">node line {op.line_start}</span>
            {#if op.error}<span class="kb-pending-op-error">{op.error}</span>{/if}
          </li>
        {/each}
      </ul>
      <div class="kb-pending-legend">
        <span class="kb-pending-legend-del">— on disk</span>
        <span class="kb-pending-legend-ins">+ proposed</span>
      </div>
      <pre class="kb-pending-diff">{#each diffLines as line, i (i)}<span
          class="kb-pending-line kb-pending-line--{line.kind}"
        >{line.kind === 'insert' ? '+' : line.kind === 'delete' ? '-' : ' '} {line.text}
</span>{/each}</pre>
      <p class="kb-pending-note">
        Not written until the session closes. Edit or delete the
        <code>[kb-op …]: #</code> block at the node line above to change it.
      </p>
    </div>
  </details>
{/if}

<style>
  .kb-pending {
    margin: 0 0 0.75rem;
    border: 1px solid color-mix(in srgb, var(--pico-primary) 45%, transparent);
    border-left-width: 3px;
    border-radius: var(--pico-border-radius);
    background: color-mix(in srgb, var(--pico-primary) 6%, transparent);
    font-size: 0.8rem;
  }

  .kb-pending--error {
    border-color: var(--pico-del-color);
    background: color-mix(in srgb, var(--pico-del-color) 8%, transparent);
  }

  .kb-pending-summary {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.35rem 0.6rem;
    cursor: pointer;
  }

  .kb-pending-badge {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.68rem;
    color: var(--pico-primary);
  }

  .kb-pending--error .kb-pending-badge {
    color: var(--pico-del-color);
  }

  .kb-pending-headline {
    color: var(--pico-muted-color);
  }

  .kb-pending-body {
    padding: 0 0.6rem 0.5rem;
  }

  .kb-pending-ops {
    list-style: none;
    margin: 0 0 0.4rem;
    padding: 0;
  }

  .kb-pending-ops li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.1rem 0;
  }

  .kb-pending-op-glyph {
    font-family: var(--pico-font-family-monospace, monospace);
  }

  .kb-pending-op-line {
    color: var(--pico-muted-color);
    font-size: 0.72rem;
  }

  .kb-pending-op--error .kb-pending-op-what,
  .kb-pending-op-error {
    color: var(--pico-del-color);
  }

  .kb-pending-legend {
    display: flex;
    gap: 1rem;
    font-size: 0.72rem;
    padding-bottom: 0.2rem;
  }

  .kb-pending-legend-del {
    color: var(--pico-del-color, #c0392b);
  }

  .kb-pending-legend-ins {
    color: var(--pico-ins-color, #27ae60);
  }

  .kb-pending-diff {
    margin: 0;
    padding: 0.4rem 0;
    max-height: 22rem;
    overflow-y: auto;
    overflow-x: hidden;
    font-size: 0.78rem;
    line-height: 1.5;
    background: var(--pico-code-background-color, var(--pico-background-color));
    border-radius: var(--pico-border-radius);
  }

  .kb-pending-line {
    display: block;
    white-space: pre-wrap;
    word-break: break-word;
    padding: 0 0.6rem;
  }

  .kb-pending-line--insert {
    background: rgba(39, 174, 96, 0.18);
    color: #27ae60;
  }

  .kb-pending-line--delete {
    background: rgba(192, 57, 43, 0.18);
    color: #c0392b;
  }

  .kb-pending-line--equal {
    color: var(--pico-muted-color);
  }

  .kb-pending-note {
    margin: 0.4rem 0 0;
    font-size: 0.72rem;
    color: var(--pico-muted-color);
  }
</style>
