<script lang="ts">
  import {
    addKvItem,
    addListItem,
    addRow,
    loadMetadataRows,
    mapKvItem,
    mapListItem,
    mapRow,
    removeKvItem,
    removeListItem,
    removeRow,
    resetRowForKind,
    saveMetadataRows,
  } from './mediaMetadataHandlers'
  import type { MetadataFieldRow, MetadataValueKind, ReservedMetadata } from './mediaMetadataTypes'
  import MediaMetadataListEditor from './MediaMetadataListEditor.svelte'
  import MediaMetadataKvEditor from './MediaMetadataKvEditor.svelte'

  type Props = {
    path?: string | null
    open?: boolean
    onClose?: () => void
  }

  let { path = null, open = false, onClose }: Props = $props()

  let dialog: HTMLDialogElement | undefined
  let loading = $state(false)
  let saving = $state(false)
  let error = $state<string | null>(null)
  let reserved = $state<ReservedMetadata | null>(null)
  let rows = $state<MetadataFieldRow[]>([])
  let savedKeys = $state<Set<string>>(new Set())

  let lastLoadedPath: string | null = null

  $effect(() => {
    if (!dialog) return
    if (open) {
      if (!dialog.open) dialog.showModal()
    } else if (dialog.open) {
      dialog.close()
      lastLoadedPath = null
    }
  })

  $effect(() => {
    if (!open || !path) return
    if (path === lastLoadedPath) return
    lastLoadedPath = path
    void load(path)
  })

  async function load(p: string) {
    loading = true
    error = null
    try {
      const result = await loadMetadataRows(p)
      reserved = result.reserved
      rows = result.rows
      savedKeys = result.savedKeys
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      reserved = null
      rows = []
    } finally {
      loading = false
    }
  }

  function handleClose() {
    onClose?.()
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }

  async function handleSave() {
    if (!path) return
    saving = true
    error = null
    try {
      await saveMetadataRows(path, rows, savedKeys)
      handleClose()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      saving = false
    }
  }

  function addField() {
    rows = addRow(rows)
  }
  function removeField(id: string) {
    rows = removeRow(rows, id)
  }
  function setFieldKey(id: string, key: string) {
    rows = mapRow(rows, id, (r) => ({ ...r, key }))
  }
  function setFieldText(id: string, text: string) {
    rows = mapRow(rows, id, (r) => ({ ...r, text }))
  }
  function setFieldKind(id: string, kind: MetadataValueKind) {
    rows = mapRow(rows, id, (r) => resetRowForKind(r, kind))
  }
  function addListItemTo(rowId: string) {
    rows = mapRow(rows, rowId, addListItem)
  }
  function removeListItemFrom(rowId: string, itemId: string) {
    rows = mapRow(rows, rowId, (r) => removeListItem(r, itemId))
  }
  function setListItemValue(rowId: string, itemId: string, value: string) {
    rows = mapRow(rows, rowId, (r) => mapListItem(r, itemId, (i) => ({ ...i, value })))
  }
  function addKvItemTo(rowId: string) {
    rows = mapRow(rows, rowId, addKvItem)
  }
  function removeKvItemFrom(rowId: string, itemId: string) {
    rows = mapRow(rows, rowId, (r) => removeKvItem(r, itemId))
  }
  function setKvItemKey(rowId: string, itemId: string, key: string) {
    rows = mapRow(rows, rowId, (r) => mapKvItem(r, itemId, (i) => ({ ...i, key })))
  }
  function setKvItemValue(rowId: string, itemId: string, value: string) {
    rows = mapRow(rows, rowId, (r) => mapKvItem(r, itemId, (i) => ({ ...i, value })))
  }

  const KIND_OPTIONS: { value: MetadataValueKind; label: string }[] = [
    { value: 'text', label: 'Text' },
    { value: 'number', label: 'Number' },
    { value: 'list', label: 'List' },
    { value: 'kv', label: 'KV' },
  ]
</script>

<dialog bind:this={dialog} class="meta-dialog" onclose={handleClose} onclick={handleBackdropClick}>
  {#if open}
    <article class="meta-article">
      <header class="meta-header">
        <strong>Metadata</strong>
      </header>

      {#if loading}
        <p class="meta-status">Loading…</p>
      {:else}
        {#if reserved}
          <div class="meta-readonly">
            <div class="meta-readonly-row">
              <span class="meta-ro-label">Path</span>
              <span class="meta-ro-value" title={reserved.relative_path}>{reserved.relative_path}</span>
            </div>
            <div class="meta-readonly-row">
              <span class="meta-ro-label">Name</span>
              <span class="meta-ro-value">{reserved.name}</span>
            </div>
            <div class="meta-readonly-row">
              <span class="meta-ro-label">Extension</span>
              <span class="meta-ro-value">{reserved.extension || '—'}</span>
            </div>
            <div class="meta-readonly-row">
              <span class="meta-ro-label">Type</span>
              <span class="meta-ro-value">{reserved.type}</span>
            </div>
          </div>
        {/if}

        <div class="meta-grid">
          {#each rows as row (row.id)}
            <div class="meta-field">
              <div class="meta-field-row1">
                <input
                  type="text"
                  class="meta-key"
                  value={row.key}
                  placeholder="key"
                  aria-label="Field key"
                  oninput={(e) => setFieldKey(row.id, (e.currentTarget as HTMLInputElement).value)}
                />
                <select
                  class="meta-kind-select"
                  aria-label="Field type"
                  value={row.kind}
                  onchange={(e) =>
                    setFieldKind(row.id, (e.currentTarget as HTMLSelectElement).value as MetadataValueKind)}
                >
                  {#each KIND_OPTIONS as opt (opt.value)}
                    <option value={opt.value}>{opt.label}</option>
                  {/each}
                </select>
                <button
                  type="button"
                  class="outline contrast meta-remove-field"
                  onclick={() => removeField(row.id)}
                  aria-label="Remove field"
                >✕</button>
              </div>

              <div class="meta-field-row2">
                {#if row.kind === 'text' || row.kind === 'number'}
                  <input
                    type="text"
                    inputmode={row.kind === 'number' ? 'decimal' : undefined}
                    class="meta-value"
                    value={row.text}
                    placeholder="value"
                    aria-label="Field value"
                    oninput={(e) => setFieldText(row.id, (e.currentTarget as HTMLInputElement).value)}
                  />
                {:else if row.kind === 'list'}
                  <MediaMetadataListEditor
                    items={row.list}
                    onAdd={() => addListItemTo(row.id)}
                    onRemove={(itemId) => removeListItemFrom(row.id, itemId)}
                    onChange={(itemId, value) => setListItemValue(row.id, itemId, value)}
                  />
                {:else}
                  <MediaMetadataKvEditor
                    items={row.kv}
                    onAdd={() => addKvItemTo(row.id)}
                    onRemove={(itemId) => removeKvItemFrom(row.id, itemId)}
                    onChangeKey={(itemId, key) => setKvItemKey(row.id, itemId, key)}
                    onChangeValue={(itemId, value) => setKvItemValue(row.id, itemId, value)}
                  />
                {/if}
              </div>
            </div>
          {/each}
        </div>

        <button type="button" class="outline meta-add-field" onclick={addField}>+ Add field</button>

        {#if error}
          <p class="meta-error" role="alert">{error}</p>
        {/if}
      {/if}

      <footer class="meta-footer">
        <button type="button" class="secondary" onclick={handleClose} disabled={saving}>Cancel</button>
        <button type="button" onclick={handleSave} disabled={saving || loading}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </footer>
    </article>
  {/if}
</dialog>

<style>
  .meta-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }
  .meta-article {
    width: min(92vw, 480px);
    padding: 0.85rem 1rem;
  }
  .meta-header {
    margin-bottom: 0.5rem;
    font-size: 0.95rem;
  }
  .meta-status {
    opacity: 0.65;
    font-size: 0.85rem;
    margin: 0 0 0.5rem 0;
  }
  .meta-readonly {
    display: flex;
    flex-direction: column;
    padding-bottom: 0.4rem;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .meta-readonly-row {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    font-size: 0.78rem;
    line-height: 1.5;
  }
  .meta-ro-label {
    flex: 0 0 4.5rem;
    opacity: 0.6;
  }
  .meta-ro-value {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  .meta-grid {
    display: flex;
    flex-direction: column;
  }
  .meta-field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .meta-field-row1,
  .meta-field-row2 {
    display: flex;
    gap: 0.3rem;
    align-items: center;
  }
  .meta-key,
  .meta-value {
    flex: 1 1 0%;
    min-width: 0;
    margin: 0;
    padding: 0.25rem 0.5rem;
    font-size: 0.82rem;
    height: 32px;
  }
  .meta-kind-select {
    flex: 0 0 auto;
    width: auto;
    min-width: 0;
    margin: 0;
    padding: 0.2rem 1.6rem 0.2rem 0.4rem;
    font-size: 0.76rem;
    height: 32px;
  }
  .meta-remove-field {
    flex: 0 0 auto;
    margin: 0;
    padding: 0;
    width: 28px;
    height: 28px;
    min-height: 28px;
    line-height: 1;
    font-size: 0.7rem;
  }
  .meta-add-field {
    margin: 0.5rem 0 0.5rem 0;
    padding: 0.25rem 0.6rem;
    font-size: 0.8rem;
    height: 32px;
  }
  .meta-footer {
    margin-top: 0.5rem;
  }
  .meta-footer button {
    padding: 0.2rem 0.3rem;
    font-size: 0.8rem;
    min-height: 32px;
  }
  .meta-error {
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.82rem;
    margin: 0.4rem 0 0 0;
  }
</style>
