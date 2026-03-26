# Lens Backlog

- **Direct editing** of markdown nodes via CodeMirror 6 (see details below)
- **AI KB edit in UI** mirrors `kb edit`
- **KB Diffs**: design operators can change KB files, but it's hard to see this in their kb fenced blocks outputs. Then after they are run we DO NOT currently have a way to see pending KB changes like we do for narrative! So the UI could actually detect kb fenced blocks, fetch the current version, do a diff, and actually show us what changed! This could be on-demand.

---

## CodeMirror 6 Integration — Direct Narrative Editing

### Goal
Replace the line-picker + CLI-typed-replacement flow for `edit --replace` with inline CodeMirror editing. Also upgrade KB editing from plain textarea to CodeMirror.

### Architecture

**Single CodeMirror component** at `src/features/editor/CodeMirrorEditor.svelte` (per CLAUDE.md constraint: "CodeMirror is configured only in the editor component"). Props:
- `content: string` — full document text
- `editableRange: { fromLine: number; toLine: number } | null` — 1-based inclusive; null = fully editable
- `lang: 'markdown' | 'plain'`

**Editable range enforcement**: Use `EditorState.transactionFilter` that rejects changes touching characters outside `[doc.line(fromLine).from, doc.line(toLine).to]`. Must reference current doc state (not cached offsets) since edits shift line positions. Non-editable regions styled via `Decoration.line` with a read-only CSS class.

**Packages**: `codemirror` (meta-package), `@codemirror/lang-markdown`, `@codemirror/language`. The meta-package bundles `@codemirror/state`, `@codemirror/view`, `@codemirror/commands`.

### Inline Replace Editing

**New stores** in `stores/ui.ts`:
```typescript
interface InlineEditState {
  address: string
  startLine: number
  endLine: number
  originalText: string
}
const inlineEditMode = writable<InlineEditState | null>(null)
const inlineEditResult = writable<string | null>(null)
```

**New component** `src/features/editor/InlineEditView.svelte` (~120 lines):
- Renders CodeMirrorEditor with full node content + editableRange for the selected lines
- OK/Cancel toolbar below the editor
- OK: sets `inlineEditResult` if content changed, clears `inlineEditMode`
- Cancel: clears `inlineEditMode`

**Integration into MarkdownView.svelte**: conditional branch — when `$inlineEditMode` is active and address matches, show `InlineEditView` instead of rendered markdown or line picker.

**Command flow** (`operators.ts` edit handler):
1. `edit /chapter-1 5 12 --replace` with no prompt text → handler sets `inlineEditMode`
2. Awaits result via Promise that resolves on `inlineEditResult` or `inlineEditMode` clearing
3. On OK with changes: calls `runEdit({ prompt: editedText, replace: true, ... })`
4. On cancel: returns `{ clearInput: false }`
5. No server changes needed — `EditBody.prompt` with `replace: true` already handles multiline via JSON

**Navigation**: clearing `inlineEditMode` when address changes. Re-engaging requires re-entering the CLI command.

### KB Editing

Replace `<textarea>` in `KbViewer.svelte` (lines 304-308) with `<CodeMirrorEditor content={editContent} on:change={...} />`. Fully editable, markdown highlighting.

### Known Risks
- **Pico CSS conflicts**: Pico's aggressive base styles may need `:global(.cm-editor)` overrides
- **Undo across boundary**: transaction filter silently drops out-of-range changes; partial selection spanning boundary deletes only in-range portion
- **Svelte lifecycle**: CodeMirror manages its own DOM; must use `bind:this` + `onMount` for `EditorView`, explicit `view.dispatch()` for reactive content updates