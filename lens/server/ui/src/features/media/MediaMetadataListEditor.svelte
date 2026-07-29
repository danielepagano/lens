<script lang="ts">
  import type { MetadataListItem } from './mediaMetadataTypes'

  type Props = {
    items: MetadataListItem[]
    onAdd: () => void
    onRemove: (id: string) => void
    onChange: (id: string, value: string) => void
  }

  let { items, onAdd, onRemove, onChange }: Props = $props()
</script>

<div class="meta-items">
  {#each items as item (item.id)}
    <div class="meta-item-row">
      <input
        type="text"
        value={item.value}
        placeholder="value"
        oninput={(e) => onChange(item.id, (e.currentTarget as HTMLInputElement).value)}
        aria-label="List value"
      />
      <button
        type="button"
        class="outline contrast meta-item-remove"
        onclick={() => onRemove(item.id)}
        aria-label="Remove item"
      >✕</button>
    </div>
  {/each}
  <button type="button" class="meta-add-item" onclick={onAdd}>+ item</button>
</div>

<style>
  .meta-items {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    width: 100%;
    padding-left: 0.6rem;
    margin-left: 0.15rem;
    border-left: 2px solid var(--pico-muted-border-color);
    box-sizing: border-box;
  }
  .meta-item-row {
    display: flex;
    gap: 0.3rem;
    align-items: center;
  }
  .meta-item-row input {
    flex: 1 1 0%;
    min-width: 0;
    margin: 0;
    padding: 0.25rem 0.5rem;
    font-size: 0.82rem;
    height: 32px;
  }
  .meta-item-remove {
    flex: 0 0 auto;
    margin: 0;
    padding: 0;
    width: 28px;
    height: 28px;
    min-height: 28px;
    line-height: 1;
    font-size: 0.7rem;
  }
  .meta-add-item {
    align-self: flex-start;
    margin: 0;
    padding: 0.15rem 0.4rem;
    font-size: 0.75rem;
    min-height: 24px;
    background: none;
    border: 1px dashed var(--pico-muted-border-color);
    color: var(--pico-muted-color);
  }
  .meta-add-item:hover {
    color: var(--pico-color);
  }
</style>
