<script lang="ts">
  type Props = {
    actionsOpen: boolean
    deleteConfirm: boolean
    showRenameInput: boolean
    showCopyInput: boolean
    renameId: string
    copyTargetId: string
    actionError: string
    onToggleMenu: () => void
    onDelete: () => void
    onRename: () => void
    onCopy: () => void
    onCancelDelete: () => void
    onCancelRename: () => void
    onCancelCopy: () => void
    onStartDeleteConfirm: () => void
    onStartRename: () => void
    onStartCopy: () => void
    onRenameIdChange: (value: string) => void
    onCopyTargetIdChange: (value: string) => void
    onActionInputKeydown: (event: KeyboardEvent, action: () => void) => void
  }

  let {
    actionsOpen,
    deleteConfirm,
    showRenameInput,
    showCopyInput,
    renameId,
    copyTargetId,
    actionError,
    onToggleMenu,
    onDelete,
    onRename,
    onCopy,
    onCancelDelete,
    onCancelRename,
    onCancelCopy,
    onStartDeleteConfirm,
    onStartRename,
    onStartCopy,
    onRenameIdChange,
    onCopyTargetIdChange,
    onActionInputKeydown,
  }: Props = $props()
</script>

<div class="kb-viewer-menu-wrap">
  <button
    type="button"
    class="kb-action-btn kb-action-btn-icon"
    aria-haspopup="true"
    aria-expanded={actionsOpen}
    onclick={onToggleMenu}
  >…</button>
  {#if actionsOpen}
    <div class="kb-viewer-menu" role="menu">
      {#if deleteConfirm}
        <div class="kb-menu-delete-confirm">
          <span>Delete this item?</span>
          <button type="button" class="kb-menu-confirm-btn" onclick={onDelete}>Delete</button>
          <button type="button" onclick={onCancelDelete}>Cancel</button>
        </div>
      {:else if showRenameInput}
        <div class="kb-menu-rename">
          <input
            type="text"
            placeholder="New ID"
            value={renameId}
            oninput={(event) => onRenameIdChange((event.currentTarget as HTMLInputElement).value)}
            onkeydown={(event) => onActionInputKeydown(event, onRename)}
          />
          <button type="button" onclick={onRename}>Rename</button>
          <button type="button" onclick={onCancelRename}>Cancel</button>
        </div>
      {:else if showCopyInput}
        <div class="kb-menu-copy">
          <input
            type="text"
            placeholder="Target ID"
            value={copyTargetId}
            oninput={(event) => onCopyTargetIdChange((event.currentTarget as HTMLInputElement).value)}
            onkeydown={(event) => onActionInputKeydown(event, onCopy)}
          />
          <button type="button" onclick={onCopy}>Copy</button>
          <button type="button" onclick={onCancelCopy}>Cancel</button>
        </div>
      {:else}
        <button type="button" role="menuitem" onclick={onStartDeleteConfirm}>Delete</button>
        <button type="button" role="menuitem" onclick={onStartRename}>Rename</button>
        <button type="button" role="menuitem" onclick={onStartCopy}>Copy</button>
      {/if}
      {#if actionError}
        <p class="kb-menu-error">{actionError}</p>
      {/if}
    </div>
  {/if}
</div>
