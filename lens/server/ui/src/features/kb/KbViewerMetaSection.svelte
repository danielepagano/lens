<script lang="ts">
  import { openKbItemFromLinkClick } from './kbViewerMarkdown'
  import type { KbSource } from '../../services/api'

  type Props = {
    tags: string[]
    source: KbSource | null
    linkedFrom: string[]
    metaOpen: boolean
    metaSummary: string
    tagsEditMode: boolean
    tagInput: string
    actionError: string
    viewerHashBase: string
    onMetaOpenChange: (open: boolean) => void
    onRemoveTag: (tag: string) => void
    onAddTagFromInput: () => void
    onStopTagsEdit: () => void
    onEnterTagsEdit: () => void
    onTagInputChange: (value: string) => void
    onActionInputKeydown: (event: KeyboardEvent, action: () => void) => void
  }

  let {
    tags,
    source,
    linkedFrom,
    metaOpen,
    metaSummary,
    tagsEditMode,
    tagInput,
    actionError,
    viewerHashBase,
    onMetaOpenChange,
    onRemoveTag,
    onAddTagFromInput,
    onStopTagsEdit,
    onEnterTagsEdit,
    onTagInputChange,
    onActionInputKeydown,
  }: Props = $props()

  function isDotTag(tag: string): boolean {
    return tag.includes('.')
  }

  // A dataset item is read-only until edited: saving forks a project copy.
  // Saying which dataset, and what a project copy overrides, is the whole point.
  const sourceText = $derived.by(() => {
    if (!source) return ''
    if (source.kind === 'dataset') return `From dataset ${source.dataset}`
    if (source.shadows.length > 0) {
      return `In this project · overrides ${source.shadows.join(', ')}`
    }
    return 'In this project'
  })
</script>

<details class="kb-meta-section" open={metaOpen} ontoggle={(event) => onMetaOpenChange((event.currentTarget as HTMLDetailsElement).open)}>
  <summary class="kb-meta-summary">{metaSummary}</summary>
  <div class="kb-meta-body">
    {#if tagsEditMode}
      <div class="kb-tags-edit-area">
        {#each tags as tag (tag)}
          <button type="button" class="kb-tag-delete-pill" onclick={() => onRemoveTag(tag)} title="Remove tag">{tag} ×</button>
        {/each}
      </div>
      <div class="kb-tags-edit-input-row">
        <input
          type="text"
          class="kb-viewer-tag-input"
          placeholder="Add tag…"
          value={tagInput}
          oninput={(event) => onTagInputChange((event.currentTarget as HTMLInputElement).value)}
          onkeydown={(event) => onActionInputKeydown(event, onAddTagFromInput)}
          onblur={onAddTagFromInput}
        />
        <button type="button" class="kb-meta-small-btn" onclick={onStopTagsEdit}>Done</button>
      </div>
      {#if actionError}
        <p class="error-state kb-save-error">{actionError}</p>
      {/if}
    {:else}
      <div class="kb-meta-tags-row">
        <span class="kb-meta-tags-list">
          {#if tags.length > 0}
            {#each tags as tag, i (tag)}
              {#if i > 0}<span class="kb-viewer-tag-sep"> · </span>{/if}
              {#if isDotTag(tag)}
                <a
                  class="kb-viewer-tag kb-viewer-tag-link"
                  href="#{tag}"
                  onclick={(event) => openKbItemFromLinkClick(event, viewerHashBase, tag)}
                >{tag}</a>
              {:else}
                <span class="kb-viewer-tag">{tag}</span>
              {/if}
            {/each}
          {:else}
            No tags
          {/if}
        </span>
        <button type="button" class="kb-meta-small-btn" onclick={onEnterTagsEdit}>Edit tags</button>
      </div>
      {#if sourceText}
        <div class="kb-meta-source-row">
          <span class="kb-meta-source-label">Source:</span>
          <span class="kb-meta-source-value" class:kb-meta-source-dataset={source?.kind === 'dataset'}
            >{sourceText}</span
          >
        </div>
      {/if}
      {#if linkedFrom.length > 0}
        <div class="kb-meta-linked-row">
          <span class="kb-linked-from-label">Linked from:</span>
          {#each linkedFrom as linkedId, i (linkedId)}
            {#if i > 0}<span class="kb-linked-from-sep">, </span>{/if}
            <a
              class="kb-linked-from-link"
              href="#{linkedId}"
              onclick={(event) => openKbItemFromLinkClick(event, viewerHashBase, linkedId)}
            >{linkedId}</a>
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</details>
