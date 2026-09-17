<script lang="ts">
  /**
   * One `patch` op's anchor + replacement, split out of `KbOpModal` because a
   * `patch` can carry a start selector, an end selector and content, each
   * optional, and inlining all three shapes made the parent unreadable.
   */
  import type { KbOpPatch, KbOpSelector } from '../../utils/kbOpBlocks'

  type Props = { patch: KbOpPatch; index: number }

  let { patch, index }: Props = $props()

  function hasSelector(sel: KbOpSelector | undefined): boolean {
    return !!sel && (!!sel.target || (sel.before?.length ?? 0) > 0 || (sel.after?.length ?? 0) > 0)
  }

  const hasShape = $derived(hasSelector(patch.start) || hasSelector(patch.end) || patch.content !== undefined)
</script>

<div class="kb-op-patch">
  <div class="kb-op-patch-index">Patch {index + 1}</div>
  {#if hasShape}
    {#if hasSelector(patch.start)}
      <div class="kb-op-selector">
        <div class="kb-op-selector-label">Anchor</div>
        {#if patch.start!.before?.length}
          <pre class="kb-op-context">{patch.start!.before!.join('\n')}</pre>
        {/if}
        {#if patch.start!.target}<div class="kb-op-target">{patch.start!.target}</div>{/if}
        {#if patch.start!.after?.length}
          <pre class="kb-op-context">{patch.start!.after!.join('\n')}</pre>
        {/if}
      </div>
    {/if}
    {#if hasSelector(patch.end)}
      <div class="kb-op-selector">
        <div class="kb-op-selector-label">End of range</div>
        {#if patch.end!.before?.length}
          <pre class="kb-op-context">{patch.end!.before!.join('\n')}</pre>
        {/if}
        {#if patch.end!.target}<div class="kb-op-target">{patch.end!.target}</div>{/if}
        {#if patch.end!.after?.length}
          <pre class="kb-op-context">{patch.end!.after!.join('\n')}</pre>
        {/if}
      </div>
    {/if}
    {#if patch.content !== undefined}
      <!-- Content may hold a ROT13 `ai:secret` block (encode_ai_secrets_for_persist,
           lens/core/annotations.py); it is meant to render as gibberish here. -->
      <div class="kb-op-selector-label">Replacement</div>
      <pre class="kb-op-patch-content">{patch.content}</pre>
    {/if}
  {:else}
    <pre class="kb-op-patch-content">{JSON.stringify(patch, null, 2)}</pre>
  {/if}
</div>

<style>
  .kb-op-patch {
    border: 1px solid var(--pico-muted-border-color);
    border-radius: var(--pico-border-radius);
    padding: 0.5rem 0.6rem;
    margin-bottom: 0.5rem;
  }

  .kb-op-patch-index {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--pico-muted-color);
    margin-bottom: 0.3rem;
  }

  .kb-op-selector {
    margin-bottom: 0.35rem;
  }

  .kb-op-selector-label {
    font-size: 0.72rem;
    color: var(--pico-muted-color);
  }

  .kb-op-context {
    margin: 0;
    padding: 0 0.4rem;
    font-size: 0.78rem;
    line-height: 1.4;
    color: var(--pico-muted-color);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .kb-op-target {
    padding: 0.1rem 0.4rem;
    font-family: var(--pico-font-family-monospace, monospace);
    font-size: 0.8rem;
    background: var(--pico-code-background-color, var(--pico-background-color));
    border-radius: var(--pico-border-radius);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .kb-op-patch-content {
    margin: 0.15rem 0 0;
    padding: 0.4rem 0.5rem;
    font-size: 0.8rem;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--pico-code-background-color, var(--pico-background-color));
    border-radius: var(--pico-border-radius);
  }
</style>
