<script lang="ts">
  import { formatShare, formatSize, type BlockSegment, type ExplainUnit } from './explainModel'

  type Props = {
    segments: BlockSegment[]
    unit: ExplainUnit
    /** Block id currently expanded, so the bar can mark it. */
    selected: string | null
    onSelect: (blockId: string) => void
  }

  let { segments, unit, selected, onSelect }: Props = $props()

  function segmentTitle(seg: BlockSegment): string {
    return `${seg.label} — ${formatSize(seg.value, unit)} (${formatShare(seg.share)})`
  }

  const summary = $derived(segments.map(segmentTitle).join('; '))
</script>

<div class="explain-bar-wrap">
  <div class="explain-bar" role="img" aria-label="Prompt composition by block: {summary}">
    {#each segments as seg (seg.id)}
      <button
        type="button"
        class={['explain-bar-seg', { 'is-selected': seg.id === selected }]}
        style="flex-basis: {seg.width}%; background: var({seg.colorVar});"
        title={segmentTitle(seg)}
        aria-label={segmentTitle(seg)}
        data-testid="explain-bar-segment"
        data-block={seg.id}
        onclick={() => onSelect(seg.id)}
      ></button>
    {/each}
  </div>

  <ul class="explain-legend" data-testid="explain-legend">
    {#each segments as seg (seg.id)}
      <li>
        <button
          type="button"
          class={['explain-legend-item', { 'is-selected': seg.id === selected }]}
          onclick={() => onSelect(seg.id)}
        >
          <span class="explain-swatch" style="background: var({seg.colorVar});"></span>
          <span class="explain-legend-label">{seg.shortLabel}</span>
          <span class="explain-legend-value">{formatSize(seg.value, unit)}</span>
          <span class="explain-legend-share">{formatShare(seg.share)}</span>
        </button>
      </li>
    {/each}
  </ul>
</div>

<style>
  .explain-bar-wrap {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  /* The 2px gaps are the surface showing through between fills. */
  .explain-bar {
    display: flex;
    gap: 2px;
    height: 18px;
    width: 100%;
    overflow: hidden;
  }

  .explain-bar-seg {
    flex-grow: 0;
    flex-shrink: 1;
    min-width: 0;
    height: 100%;
    padding: 0;
    margin: 0;
    border: none;
    border-radius: 0;
    cursor: pointer;
    transition: filter 0.15s, outline-color 0.15s;
    outline: 2px solid transparent;
    outline-offset: -2px;
  }

  .explain-bar-seg:first-child {
    border-radius: 4px 0 0 4px;
  }

  .explain-bar-seg:last-child {
    border-radius: 0 4px 4px 0;
  }

  .explain-bar-seg:hover {
    filter: brightness(1.12);
  }

  .explain-bar-seg.is-selected {
    outline-color: var(--pico-color);
  }

  .explain-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.75rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .explain-legend li {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .explain-legend-item {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    background: none;
    border: none;
    border-radius: 0.35rem;
    padding: 0.2rem 0.3rem;
    margin: 0;
    min-height: 32px;
    font-size: 0.78rem;
    line-height: 1.2;
    /* Pico redefines --pico-color inside `button`; inherit the article's ink. */
    color: inherit;
    cursor: pointer;
  }

  .explain-legend-item:hover,
  .explain-legend-item.is-selected {
    background: color-mix(in srgb, var(--pico-primary) 16%, transparent);
  }

  .explain-swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .explain-legend-label {
    white-space: nowrap;
  }

  .explain-legend-value,
  .explain-legend-share {
    color: var(--pico-muted-color);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
