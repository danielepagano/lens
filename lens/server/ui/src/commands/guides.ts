/**
 * Markdown guide strings for CLI commands.
 *
 * One entry per command trigger (matching CommandDefinition.guide or trigger).
 * A special `__general` key holds a general guide shown when no command is selected.
 *
 * Adapted from lens/cli/help_strings.py for presentation in the UI guide modal.
 */

export const GUIDES: Record<string, string> = {
  __general: `# Lens CLI

The CLI bar at the bottom of the screen is your primary way to interact with a Lens project. Type a command to invoke AI operators, manage knowledge, navigate the narrative tree, or handle transactions.

## How it works

- Start typing a command name — suggestions appear above the bar.
- Press **Tab** to cycle through available completions.
- Select a suggestion chip with a click or by pressing **Enter**.
- Flags (options) appear automatically as chips once a command is recognized.
- Prompts support **@type.key** to reference a knowledge object, **@var:key** for pinned variables, **@roll expr** for dice rolls, and **@now** for the current date.

## Command groups

| Group | Commands |
|-------|----------|
| **narrative** | \`write\`, \`design\`, \`chat\`, \`edit\`, \`kb-edit\` |
| **rpg** | \`play\`, \`advance\` |
| **structure** | \`structure-section\`, \`structure-collate\`, \`structure-compress\`, \`structure-rename\`, \`structure-rewind\`, \`structure-explain\` |
| **pin** | \`pin-kb\`, \`pin-var\`, \`pin-param\` |
| **transactions** | \`tx-commit\`, \`tx-rollback\`, \`tx-checkpoint\`, \`tx-refresh\`, \`tx-status\` |
| **media** | \`media-attach\`, \`media-manage\`, \`media-generate\` |
`,
  write: `## write

Generate narrative prose at the cursor. Provide an optional instruction or continue from where you left off.

### Usage

\`\`\`
write [prompt]
\`\`\`

Call without arguments to continue writing.

### Options

- \`--pin\` — KB object ID to include in AI context (repeatable)
- \`--unpin\` — KB object ID to exclude from inherited context (repeatable)
- \`--llm\` — LLM ID to use (overrides project default)
- \`--reasoning\` — Reasoning effort: none, low, medium, high (for models that support it)
- \`--retry\` — Discard generated text and regenerate
- \`--manual\` — Append text directly to the cursor node without AI

### Notes

- New content is appended at the cursor position in an open annotation tag.
- Use \`@type.key\` in the prompt to reference a knowledge object inline.
`,
  design: `## design

Collaborative KB design workspace. Think, look up knowledge objects, and propose changes.

### Usage

\`\`\`
design [prompt]
\`\`\`

The first call opens a new design sub-node. Subsequent calls continue the current session.

### Options

- \`--module\` — Design module key to use (KB object under \`design.<key>\`)
- \`--end\` — Close the current design session and extract KB entries
- \`--slug\` — Sub-node id to use when starting a new session (auto-generated from prompt by default)
- \`--pin\` — KB object ID to include in AI context (repeatable)
- \`--unpin\` — KB object ID to exclude from inherited context (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort
- \`--retry\` — Retry the last design generation

### Notes

- Use \`--end\` to close the session. All \`\`\`kb blocks in the sub-node are extracted into the knowledge store.
`,
  chat: `## chat

Have the AI speak as a specific character in the current scene.

### Usage

\`\`\`
chat [prompt]
\`\`\`

### Options

- \`--as\` — KB id of the character the AI will voice (e.g. \`npc.bob\`, \`pc.alice\`)
- \`--with\` — KB id of the counterpart character the user plays (e.g. \`pc.amy\`); triggers session mode
- \`--end\` — Close the current chat session
- \`--narrate\` — In a session: append as blockquote prose only (no [Name] prefix)
- \`--wait\` — In a session: append text only, do not request an AI reply
- \`--slug\` — Sub-node id for a new session
- \`--pin\` — KB object ID to include in AI context (repeatable)
- \`--unpin\` — KB object ID to exclude from inherited context (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort
- \`--retry\` — Discard generated text and regenerate

### Notes

- Without \`--with\`, this is a one-shot inline response written directly into the current node.
- With \`--with\`, opens a session sub-node for a back-and-forth conversation. Inside the session, typing text sends it as the \`--with\` character and the AI responds as \`--as\`.
- Subsequent calls without \`--with\` inside an open session continue that session automatically.
`,
  edit: `## edit

Rewrite a line range in a narrative node using the LLM, or replace it directly.

### Usage

\`\`\`
edit <address> <start> <end> [prompt]
\`\`\`

### Options

- \`--replace\` — Replace the selected text directly with PROMPT (no LLM)
- \`--retry\` — Re-propose with same or updated parameters
- \`--pin\` — KB object ID to include in AI context (repeatable)
- \`--unpin\` — KB object ID to exclude from inherited context (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort

### Notes

- In LLM mode (default), the selected lines are claim-wrapped, the AI proposes a replacement, and the result appears as an unstaged diff.
- Use \`tx-rollback\` to cancel or \`tx-commit\` to accept.
- \`--replace\` swaps text directly without the LLM.
`,
  'kb-edit': `## kb-edit

Edit or create a knowledge object using AI.

### Usage

\`\`\`
kb-edit <id> <instruction>
\`\`\`

### Options

- \`--context\` — Narrative context address (e.g. \`/chapter-1\`)
- \`--include-template\` — Include the type template
- \`--pin\` — KB object ID to pin (repeatable)
- \`--unpin\` — KB object ID to unpin (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort
- \`--retry\` — Retry the edit
`,
  play: `## play

Narrate a player-agency moment in GM voice, then pause for player response.

### Usage

\`\`\`
play [prompt]
\`\`\`

### Options

- \`--as\` — PC key to attribute the prompt to (e.g. \`alice\` => [Alice]); must be a pinned \`pc.*\`
- \`--module\` — Rules module to activate (e.g. \`combat\` => \`rules.combat\`); swaps previous module
- \`--pass\` — Have the GM respond now (call the LLM)
- \`--end\` — Close the current play session
- \`--slug\` — Sub-node id to use (auto-generated from prompt by default)
- \`--pin\` — KB object ID to pin (repeatable); at least one must be tagged \`pc\`
- \`--unpin\` — KB object ID to unpin (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort
- \`--retry\` — Discard generated text and regenerate

### Notes

- Opens a play session sub-node the first time, or continues the current session.
- By default, play appends only what the player says (no GM / LLM). Use \`--pass\` when you want the GM to respond.
- Requires at least one player character (KB object tagged \`pc\`) to be pinned.
- Requires the \`rpg\` dataset.
`,
  advance: `## advance

Advance time, update fronts, resolve consequences.

### Usage

\`\`\`
advance
\`\`\`

### Options

- \`--days\` — Number of days to advance (default: 1)
- \`--end\` — Apply KB/timeline updates and close the advance session
- \`--pin\` — KB object ID to pin (repeatable)
- \`--unpin\` — KB object ID to unpin (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort
- \`--retry\` — Discard generated text and regenerate

### Notes

- Creates an advance session sub-node tracking the time jump.
- Use \`--end\` to apply KB and timeline updates.
- Requires the \`rpg\` dataset.
`,
  'structure-section': `## structure-section

Create a child node for deeper detail, or close one and summarize back to the parent.

### Usage

\`\`\`
structure-section [id | --end]
\`\`\`

### Options

- \`--end\` — Close the current section: appends a summary and the closing tag, then moves the cursor back up
- \`--pin\` — KB object ID to pin for summary context (repeatable)
- \`--unpin\` — KB object ID to unpin for summary context (repeatable)
- \`--llm\` — LLM ID to use for summary (overrides project default)
- \`--reasoning\` — Reasoning effort

### Notes

- Provide an \`id\` (slug) to start a new section, or \`--end\` to close the current one.
- Sections structure the narrative tree into a hierarchy.
`,
  'structure-collate': `## structure-collate

Extract a range of existing lines into a new child section, replacing them with an AI summary.

### Usage

\`\`\`
structure-collate <id> <address> <start> <end>
\`\`\`

### Options

- \`--summary-guide\` — Optional extra instructions for the summary LLM
- \`--pin\` — KB object ID to pin (repeatable)
- \`--unpin\` — KB object ID to unpin (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort

### Notes

- The selected lines are moved into a new child node, an LLM summary is generated, and the range in the parent is replaced with the section annotation block.
`,
  'structure-compress': `## structure-compress

Use AI to find and extract a matching passage into a child section. Describe what to pull out.

### Usage

\`\`\`
structure-compress [prompt | --aggressiveness]
\`\`\`

### Options

- \`--aggressiveness\` — Without a prompt: \`low\` | \`medium\` | \`high\` (automated range selection)
- \`--node\` — Narrative node address (default: current cursor position)
- \`--summary-guide\` — Optional extra instructions for the summary LLM
- \`--pin\` — KB object ID to pin (repeatable)
- \`--unpin\` — KB object ID to unpin (repeatable)
- \`--llm\` — LLM ID to use
- \`--reasoning\` — Reasoning effort

### Notes

- Provide a PROMPT describing what to extract, or use \`--aggressiveness\` for automated range selection.
- If the model does not call the compress_collate tool, its explanation is printed instead.
`,
  'structure-rename': `## structure-rename

Rename a narrative node.

### Usage

\`\`\`
structure-rename <address> <new_slug>
\`\`\`

Changes the slug of a narrative node while preserving its content and children.
`,
  'structure-rewind': `## structure-rewind

Move the cursor backward in the narrative tree, discarding all content that comes after.

### Usage

\`\`\`
structure-rewind <address> [line]
\`\`\`

### Details

Without a line number, the cursor is placed at the end of the given node (its last closed section). Everything after that point — later siblings, their summaries, close tags, and their child nodes — is deleted.

With a line number, more precise truncation occurs:
- Line in front matter → node is cleared entirely.
- Line inside an annotation → annotation and everything after is deleted.
- Line inside a section body → the entire section block and child node are deleted (partial summaries are invalid).
- Line inside a write body → body is truncated there and the close tag is moved to that position.
- Otherwise (free text) → simple truncation.

Side effects such as knowledge-base objects created by design operators are never modified.
`,
  'structure-explain': `## structure-explain

Show what is in the prompt at a point in the narrative: every component with its size, the block it lands in, and why it is there.

### Usage

\`\`\`
structure-explain [address] [line]
\`\`\`

Call without arguments to explain the current cursor.

### Options

- \`--operator\` — Assemble as this operator instead of the detected one

### Details

The prompt is assembled exactly as an operator would assemble it — same pins, same modalities, same transforms — and then reported instead of sent. Nothing is written and no model is called, so this is safe to run at any time, including mid-session.

The report opens as a modal: a stacked bar of the prompt blocks, then each block broken down into its components with size, share, and provenance — a pin on a named ancestor, a \`+\` expansion, an \`@\` mention, a rules companion, a session module, or a modality.

### Notes

- Token counts are estimates from a byte count and a rough divisor; byte counts are exact.
- Switching \`--operator\` changes the answer: auto-pins and required modalities differ per operator.
- Rows marked *derived* follow from another pin — change what they derive from, not the row itself.
`,
  'pin-kb': `## pin-kb

Declare which knowledge objects apply, either for a whole node or from this point on.

### Usage

\`\`\`
pin-kb add|remove|block|unblock|mention|include <id> [ids...]
\`\`\`

### Actions
- \`add\` — Pin a KB object to a node so the AI includes it in prompt context
- \`remove\` — Unpin a KB object from a node
- \`block\` — Suppress a pin inherited from an ancestor node
- \`unblock\` — Restore an ancestor pin that was previously suppressed
- \`mention\` — Put an object in context *at this point* for one AI turn
- \`include\` — Put an object in context *at this point* for the rest of the node

### Options

- \`--node\` — Target node address (default: cursor)

### Notes

- Pins tell the AI what facts are "in frame" for a scene; they inherit from root to cursor.
- Mentions and includes are different: they expand where they were written, are never inherited
  by sub-nodes, and a mention stops expanding after one AI turn. Say it again to refresh it.
- \`mention\` and \`include\` are also available as \`--mention\` / \`--include\` on
  \`write\`, \`play\`, \`chat\`, and \`design\`; typing \`@type.key\` in a prompt is a
  one-turn mention.
`,
  'pin-var': `## pin-var

Set or unset key-value variables that prompts can reference as \`@var:key\`.

### Usage

\`\`\`
pin-var set|unset <key> [value]
\`\`\`

### Options

- \`--node\` — Target node address (default: cursor)

### Notes

- Useful for dynamic values like character mood, season, or scene location.
`,
  'pin-param': `## pin-param

Override operator defaults (LLM choice, reasoning level, temperature, etc.) at a specific node.

### Usage

\`\`\`
pin-param set|unset <scope> <key> [value]
\`\`\`

### Options

- \`--node\` — Target node address (default: cursor)

### Notes

- Use \`global\` scope for all operators or an operator slug (\`write\`, \`chat\`, etc.) for one.
`,
  'tx-commit': `## tx-commit

Save pending work by staging all changes.

### Usage

\`\`\`
tx-commit
\`\`\`

Run \`tx-checkpoint\` to commit and push.
`,
  'tx-rollback': `## tx-rollback

Undo the last AI operation and restore the narrative to its previous state.

### Usage

\`\`\`
tx-rollback
\`\`\`

### Details

- Inline operators (write, play, chat): unstaged changes are discarded.
- Mutation operators (edit, kb edit): a compensating transaction removes claim tags and restores the original text.
`,
  'tx-checkpoint': `## tx-checkpoint

Commit all staged changes with a message and push to the remote. Permanently saves your work.

### Usage

\`\`\`
tx-checkpoint [message]
\`\`\`

### Options

- \`--no-push\` — Do not push to remote after committing.
`,
  'tx-refresh': `## tx-refresh

Fetch from remote and fast-forward the current branch.

### Usage

\`\`\`
tx-refresh
\`\`\`

### Options

- \`--reset\` — Match the remote branch exactly: discard unpushed commits, uncommitted work, and untracked files.

### Notes

- Fails if the remote is ahead and there are uncommitted changes (unless \`--reset\` is given).
- When already up to date with the remote, refresh is a no-op even with local pending work.
`,
  'tx-status': `## tx-status

Count knowledge objects and narrative nodes. Shows pending transaction and staged (checkpoint) diff.

### Usage

\`\`\`
tx-status
\`\`\`

Displays unstaged files, staged files, incoming/outgoing commits, and remote status.
`,
  'media-attach': `## media-attach

Attach a media file from the mount to a narrative node.

### Usage

\`\`\`
media-attach [dir|file-path] [address] [line]
\`\`\`

### Notes

- If a file path is given, the file is attached immediately.
- If a directory is given (or nothing), opens a file browser carousel.
- The embed is inserted after the given line (default: end of node).
`,
  'media-manage': `## media-manage

Browse and manage media files on the mount.

### Usage

\`\`\`
media-manage [dir]
\`\`\`

Opens a file browser carousel for managing media files.
`,
  'media-search': `## Media search

Search matches file paths and metadata (prompts, tags, any sidecar field)
across the whole mount, ranked by relevance — not just the current folder.

### Query syntax

| Token | Meaning |
|-------|---------|
| \`word\` | Scored keyword — files containing it rank higher |
| \`"two words"\` | Exact phrase, kept together |
| \`key:value\` | Metadata match, e.g. \`type:image\` (ranked highest) |
| \`path/sub:value\` | Nested metadata match, e.g. \`composite/type:subject\` |
| trailing \`!\` | Required — hard-filters instead of just scoring |

Words next to each other score higher when they appear together in that
order, so word order matters. A bare key (like \`prompt\`) finds files that
have that field at all.

### Example

\`\`\`
amy! type:image! composite/type:subject "brown hair" couch
\`\`\`

Only images tagged \`amy\` with a \`subject\` composite layer, ranked by how
well they match "brown hair" and "couch".

### Notes

- Whole-word matches only — no partial/prefix matching.
- Results update automatically as you finish typing each word; press
  **Enter** to re-run a search after editing a word in place.
`,
  'media-generate': `## media-generate

Generate images via the configured backend and save them to the mount.

### Usage

\`\`\`
media-generate <prompt>
\`\`\`

### Options

- \`--model\` — Image backend ID from \`lens.toml\`
- \`--aspect\` — Aspect ratio
- \`--size\` — Resolution tier
- \`--batch\` — How many images to generate
- \`--slug\` — Folder name under \`generated/\`
- \`--negative\` — Optional negative prompt
- \`--from\` — Batch sidecar YAML path
- \`--ref\` — Reference image path (repeatable, S3 only)
`,
}
