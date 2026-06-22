"""Shared help strings for CLI commands and options.

Externalized for consistency and to ease future localization.
All Typer ``help=`` strings for commands, sub-commands, options, and
arguments should be imported from this module so they are defined in
one place and can be translated without touching CLI logic.
"""

from __future__ import annotations

# ── Click context settings ──
# Enable -h as a shorthand for --help across every CLI entry point.
HELP_OPTS = ["-h", "--help"]

# ═══════════════════════════════════════════════════════════════════
#  App
# ═══════════════════════════════════════════════════════════════════
APP = "Lens: narrative engine with fractal summarization."

# ═══════════════════════════════════════════════════════════════════
#  Top-level commands  (lens <command>)
# ═══════════════════════════════════════════════════════════════════
CMD_INIT = "Initialize a Lens project in the current git repo."
CMD_USE = "Select the active narrative in lens.toml."
CMD_CHECK = "Verify lens.toml, API keys, mount, and paths."
CMD_STATS = "Count knowledge objects and narrative nodes."
CMD_COMMIT = "Stage all changes (git add -A)."
CMD_CHECKPOINT = (
    "Stage all changes, commit, and push if remote is configured."
)
CMD_REFRESH = "Fetch from remote and fast-forward the current branch."
CMD_REWIND = "Rewind the cursor to a node or line, deleting everything after."
CMD_ROLLBACK = "Discard the pending transaction."
CMD_KB = (
    "Manage knowledge objects "
    "(add, edit, get, tag, template, copy, rename, delete, with-tag, extract)."
)
CMD_PIN = "Pin knowledge, narrative vars, or operator params at narrative nodes."
CMD_PROMPT = "Manage operator prompts and project-local prompt overrides."
CMD_MEDIA = "Image generation, TTS, attachment, and related commands."
CMD_RENAME = "Rename a narrative node."
CMD_SERVE = "Build the frontend and start the Lens API server."
CMD_DEV = "Start the Vite dev server and Lens API with hot reload."
CMD_DEPLOY = "Manage Fly.io deployment."

# ═══════════════════════════════════════════════════════════════════
#  Operators  (lens <operator>)
# ═══════════════════════════════════════════════════════════════════
OP_WRITE = "Generate narrative text at the cursor."
OP_EDIT = (
    "Rewrite a line range in a narrative node using the LLM, "
    "or replace it directly."
)
OP_SECTION = "Start or end a section at the cursor."
OP_COLLATE = (
    "Carve a line range into a new child section at an arbitrary address."
)
OP_COMPRESS = (
    "Use AI to pick a range on the cursor node and collate it "
    "into a child section (provide a PROMPT or --aggressiveness)."
)
OP_CHAT = "Have the AI speak as a character in the current scene."
OP_PLAY = "Narrate a player-agency moment in GM voice."
OP_DESIGN = "Collaborative KB design session: think, look up, and propose changes."
OP_ADVANCE = "Advance time, update fronts, resolve consequences."

# ═══════════════════════════════════════════════════════════════════
#  Shared option help strings  (used across multiple commands)
# ═══════════════════════════════════════════════════════════════════

# --pin / -p
OPT_PIN = "Knowledge base ID to pin for this operator (repeatable)"
OPT_PIN_SECTION = (
    "KB ID to pin in the new section's front matter (repeatable)"
)
OPT_PIN_SUMMARY = "KB ID to pin for summary context (repeatable)"
OPT_PIN_PLAY = (
    "KB ID to pin (repeatable); at least one must be tagged 'pc'"
)

# --unpin / -u
OPT_UNPIN = "Knowledge base ID to unpin for this operator (repeatable)"
OPT_UNPIN_SECTION = (
    "KB ID to unpin in the new section's front matter (repeatable)"
)
OPT_UNPIN_SUMMARY = "KB ID to unpin for summary context (repeatable)"

# --llm / -l
OPT_LLM = "LLM ID to use (overrides project default)"
OPT_LLM_SUMMARY = (
    "LLM ID to use for summary (overrides project default)"
)

# --reasoning
OPT_REASONING = "Reasoning override: none, low, medium, high"

# --retry / -r
OPT_RETRY = "Discard generated text and regenerate"
OPT_RETRY_PROPOSE = "Re-propose with same or updated parameters"
OPT_RETRY_DESIGN = (
    "Retry (regenerate) the last design generation in the current session"
)

# --node / -n
OPT_NODE = (
    "Narrative node address (default: cursor, "
    "same addressing rules as lens pin kb)"
)

# --end
OPT_END_SECTION = "Close the current section"
OPT_END_SESSION = "Close the current session"
OPT_END_CHAT = "Close the current chat session"
OPT_END_PLAY = "Close the current play session"
OPT_END_DESIGN = (
    "Close the current design session and extract KB entries"
)
OPT_END_ADVANCE = (
    "Apply KB/timeline updates and close the advance session"
)

# --slug / -s
OPT_SLUG = (
    "Sub-node id to use when starting a new session "
    "(default: auto-generated from prompt)"
)
OPT_SLUG_CHAT = (
    "Sub-node id for a new session "
    "(default: auto-generated from characters and prompt)"
)

# --module / -m
OPT_MODULE_PLAY = (
    "Rules module to activate (e.g. 'combat' => rules.combat); "
    "swaps previous module"
)
OPT_MODULE_DESIGN = (
    "Design module key to use "
    "(KB object under design.<key>, e.g. 'encounter')"
)

# --summary-guide / -g
OPT_SUMMARY_GUIDE = (
    "Optional extra instructions for the collate summary LLM"
)

# --pass
OPT_PASS = "Have the GM respond now (call the LLM)"

# --as
OPT_AS_CHAT = (
    "KB id of the character the AI will voice "
    "(e.g. npc.bob, pc.alice)"
)
OPT_AS_PLAY = (
    "PC key to attribute the prompt to (e.g. alice => [Alice]); "
    "must be a pinned pc.*"
)

# --with / -w
OPT_WITH = (
    "KB id of the counterpart character the user plays "
    "(e.g. pc.amy); triggers session mode"
)

# --narrate
OPT_NARRATE = (
    "In a session: append as blockquote prose only (no [Name] prefix)"
)

# --wait
OPT_WAIT = (
    "In a session: append the line only, do not request an AI reply"
)

# --replace
OPT_REPLACE = "Replace the selected text directly with PROMPT (no LLM)"

# --manual / -m  (write)
OPT_MANUAL_WRITE = (
    "Append text directly to the cursor node without AI"
)

# --aggressiveness / -a  (compress)
OPT_AGGRESSIVENESS = (
    "Without a prompt: low | medium | high "
    "(automated range selection)"
)

# --days / -d  (advance)
OPT_DAYS = "Number of days to advance (default: 1)"

# --skip-network  (check)
OPT_SKIP_NETWORK = (
    "Skip TCP reachability checks for LLM base_url "
    "(env and paths still verified)."
)

# --no-push  (checkpoint)
OPT_NO_PUSH = "Do not push to remote after committing."

# --verbose / -v  (stats)
OPT_VERBOSE = (
    "Show pending transaction diff and staged (checkpoint) diff."
)

# --yes / -y  (rollback - not yet used but potential)
OPT_YES = "Skip confirmation prompt."

# --reset  (refresh)
OPT_RESET = (
    "Match the remote branch exactly: discard unpushed commits, "
    "uncommitted work, and untracked files."
)

# ═══════════════════════════════════════════════════════════════════
#  Shared argument help strings
# ═══════════════════════════════════════════════════════════════════

ARG_ID = "Object ID (type.key)"
ARG_ID_OR_NONE = "Object ID (type.key); omit to see usage"
ARG_ADDRESS = "Narrative node address (e.g. /chapter-1)"
ARG_LINE_1 = "1-based line number (inclusive)"
ARG_PROMPT = "Prompt text (may contain @-mentions for KB, vars, rolls)"
ARG_PROMPT_OPT = (
    "Prompt text. May contain @-mentions. Omit if using --from."
)
ARG_PROMPT_WRITE = "Writing direction / instruction (omit to continue)"
ARG_PROMPT_EDIT = "Editing instruction or replacement text"
ARG_PROMPT_CHAT = (
    "Stage directions (one-shot or fresh session) "
    "or the character's dialog (inside session)"
)
ARG_PROMPT_PLAY = (
    "Scene direction or situation for the player-facing moment "
    "(e.g. what the player says or does)"
)
ARG_PROMPT_DESIGN = "Design task or question"
ARG_PROMPT_COMPRESS = (
    "What to collate into a child section "
    "(omit if using --aggressiveness)"
)
ARG_FEEDBACK = "Feedback for --retry (ignored otherwise)"
ARG_MESSAGE = "Commit message (default: lens checkpoint <timestamp>)"
ARG_SLUG_NARRATIVE = (
    "Narrative slug (alphanumeric, underscores, hyphens)"
)
ARG_NODE_ADDR = (
    "Node address to rewind to.  "
    "Use '/' for the narrative root or '/@cursor' for the current cursor."
)
ARG_LINE_NUM = (
    "Line number within the node (1-based, inclusive).  "
    "When omitted, the cursor is placed at the end of the node."
)
ARG_ADDRESS_EDIT = (
    "Narrative node address (e.g. /chapter-1, my-story/chapter-1)"
)
ARG_SOURCE_ID = "Source object ID (type.key)"
ARG_TARGET_ID = "Target object ID (must be valid and unused)"
ARG_OLD_ID = "Current object ID"
ARG_NEW_ID = "New object ID (must be valid and unused)"
ARG_PROMPT_KEY = "Prompt key (e.g. write.system)"
ARG_PROMPT_CONTENT = "Override prompt content"
ARG_INSTRUCTION = "AI instructions for what to write or change"
ARG_CONTENT_OPT = (
    "Object content (omit to create empty or no-op)"
)
ARG_TYPE_NAME = "Object type (e.g. person, location, stat)"
ARG_TYPE_FILTER = "Only tags on objects of this type"
ARG_TAG_PREFIX = "Only tags starting with this prefix"
ARG_TAGS = (
    "Tag(s) to query. AND across args; "
    "use (a b c) for OR within, e.g. type:undead (cr:1 cr:2)"
)
ARG_PATH = "Mount-relative file path (e.g. 'photo.jpg', not a filesystem path)"
ARG_MEDIA_ADDR = (
    "Narrative node address (default: /@cursor). "
    "Use e.g. '/' or '/chapter-1'."
)
ARG_MEDIA_LINE = (
    "1-based line to insert after "
    "(default: append after last line of the node)."
)
ARG_TTS_ADDR = (
    "Narrative node address (e.g. /@cursor, /chapter-1). "
    "Optional line slice @N or @N:M (physical lines in the node file)."
)
ARG_MEDIA_SOURCE = (
    "Markdown file or folder containing ```kb blocks"
)
ARG_APP_NAME = "Fly app name"
ARG_REGION = "Fly region (e.g. lax, ams)"
ARG_USERNAME = "Basic Auth username"
ARG_PASSWORD = "Basic Auth password"
ARG_DEPLOY_KEY = "Path to SSH deploy key for the project repo"
ARG_PROJECT_SLUG = "Project directory name (slug)"
ARG_RENAME_ADDR = (
    "Address of the node to rename (e.g. /chapter-1/design-old)"
)
ARG_NEW_SLUG = "New slug (alphanumeric, underscores, hyphens only)"
ARG_PACK_NAME = (
    "Pack name from lens/prompts/packs/<name>.toml"
)
ARG_SCOPE = "'global' or operator slug (e.g. write)"
ARG_PARAM_KEY = "Canonical param name (e.g. llm_id)"
ARG_VAR_KEY = "Var key"
ARG_VAR_VALUE = "Value (multiple words join with spaces)"
ARG_PARAM_VALUE = (
    "Value (booleans/numbers coerced; multiple words join with spaces)"
)

# ═══════════════════════════════════════════════════════════════════
#  Sub-command help  (shown as "Usage: lens <group> <subcmd> ...")
# ═══════════════════════════════════════════════════════════════════

# kb subcommands
KB_ADD = "Upsert a single knowledge object."
KB_TEMPLATE = "Get or set the type template (_template.md)."
KB_TAG = "Add or remove tags on an object."
KB_DELETE = "Delete an object and its tag references."
KB_COPY = "Copy an object to a new ID. Target type may differ."
KB_RENAME = "Rename an object to a new ID. New type may differ."
KB_EDIT = "Edit or create a knowledge object using AI."
KB_GET = "Fetch and print knowledge objects."
KB_LIST_TAGS = (
    "List unique tag values, optionally filtered by type or prefix."
)
KB_WITH_TAG = (
    "List object IDs matching tag groups; "
    "optionally expand or recurse by dot-tags."
)
KB_EXTRACT = (
    "Extract and upsert KB objects from structured markdown "
    "(single transaction)."
)

# pin sub-commands
PIN_KB = "Pin or unpin knowledge objects (kb_pin / kb_unpin)."
PIN_VAR = (
    "Set or unset vars in node front matter "
    "(string substitution via @var:)."
)
PIN_PARAM = (
    "Set or unset operator params under params.global "
    "or params.<operator>."
)
PIN_KB_ADD = "Add knowledge objects to kb_pin at the target node."
PIN_KB_REMOVE = "Remove knowledge objects from kb_pin."
PIN_KB_BLOCK = (
    "Add knowledge objects to kb_unpin (cancel ancestor pins)."
)
PIN_KB_UNBLOCK = "Remove knowledge objects from kb_unpin."
PIN_VAR_SET = "Set a var in front matter at the target node."
PIN_VAR_UNSET = "Remove a var from front matter at the target node."
PIN_PARAM_SET = "Set a param under params.<scope> at the target node."
PIN_PARAM_UNSET = (
    "Remove a param key from params.<scope> at the target node."
)

# prompt sub-commands
PROMPT_LIST = "List available prompt keys."
PROMPT_GET = "Print the effective prompt and its source layer."
PROMPT_SET = "Set or update a project-local prompt override."
PROMPT_CLEAR = "Remove a project-local prompt override."
PROMPT_PATH = (
    "Print prompt file path for project or builtin prompts."
)
PROMPT_PACKS = "List available prompt packs and current selection."
PROMPT_USE_PACK = "Select a prompt pack in lens.toml."
PROMPT_CLEAR_PACK = "Clear the selected prompt pack in lens.toml."

# media sub-commands
MEDIA_GENERATE = (
    "Generate images via the configured backend "
    "and save them to the mount."
)
MEDIA_TTS = (
    "Synthesize a narrative node line-by-line; "
    "MP3s live under tts-cache/ on the mount."
)
MEDIA_ATTACH = (
    "Attach a media embed after the given line in the given node "
    "(defaults: cursor, end of file)."
)

# deploy sub-commands
DEPLOY_INIT = (
    "Create Fly app, volume, set secrets, and generate fly.toml."
)
DEPLOY_PUSH = (
    "Deploy (or redeploy) the Lens application image to Fly.io."
)
DEPLOY_ADD = (
    "Add a project to an existing multi-project deployment."
)
DEPLOY_REMOVE = (
    "Remove a project from an existing multi-project deployment."
)

# ═══════════════════════════════════════════════════════════════════
#  Extended description texts  (shown in --help body, multi-line)
# ═══════════════════════════════════════════════════════════════════

DESC_USE = "Select narrative and create folder / _node.md if needed."

DESC_CHECK = (
    "Verify lens.toml, API keys, optional mount, "
    "and related paths for this project."
)

DESC_COMMIT = "Stage all changes in the project (git add -A)."

DESC_CHECKPOINT = (
    "Stage all changes, create a git commit, and push to the remote "
    "if one is configured."
)

DESC_REFRESH = (
    "Fetch from the remote and fast-forward the current branch "
    "(no merge commits).\n\n"
    "Fails if the remote is ahead and there are uncommitted changes "
    "(unless --reset is given). When already up to date with the remote, "
    "refresh is a no-op even with local pending work.\n"
    "Use --reset to recover when checkpoint or a normal refresh "
    "cannot proceed."
)

DESC_REWIND = (
    "Rewind the cursor to a node or line, deleting everything after.\n\n"
    "Without a line number, the cursor is placed at the end of the given "
    "node (its last closed section).  Everything after that point "
    "\u2014 later siblings, their summaries, close tags, and their child "
    "nodes \u2014 is deleted.\n\n"
    "With a line number, the node\u2019s file is truncated at that line "
    "with structural adjustments:\n"
    "\n"
    "\u2022 Line in front matter        \u2192 node is cleared entirely.\n"
    "\u2022 Line inside an annotation   \u2192 annotation and everything "
    "after is deleted.\n"
    "\u2022 Line inside a section body  \u2192 the entire section block "
    "and child node are deleted (partial summaries are invalid).\n"
    "\u2022 Line inside a write body    \u2192 body is truncated there "
    "and the close tag is moved to that position.\n"
    "\u2022 Otherwise (free text)       \u2192 simple truncation.\n\n"
    "Side effects such as knowledge-base objects created by design "
    "operators are never modified."
)

DESC_ROLLBACK = (
    "Discard the pending operator transaction.\n\n"
    "Inline operators (write): unstaged changes are discarded.\n"
    "Mutation operators (edit, kb edit): a compensating transaction "
    "removes claim tags and restores the original text."
)

DESC_SERVE = (
    "Build the frontend and serve the bundle from FastAPI "
    "(no hot-reload)."
)

DESC_DEV = (
    "Start the Vite dev server (HMR) and Lens API "
    "for the current project."
)

DESC_INIT = "Initialize a Lens project in the current git repo."

DESC_WRITE = (
    "Stream generated narrative text into the cursor node.\n\n"
    "Call without arguments to continue writing. Use --retry to "
    "discard the current output and regenerate.  "
    "Pin knowledge objects with -p or use @type.key in the prompt."
)

DESC_EDIT = (
    "Rewrite a line range in a narrative node.\n\n"
    "In LLM mode (default), the selected lines are claim-wrapped, "
    "the AI proposes a replacement, and the result appears as an "
    "unstaged diff.  Use --replace to swap text directly without "
    "the LLM.  Run lens rollback to cancel or lens commit to accept."
)

DESC_SECTION = (
    "Create a child node at the cursor and open a section tag.\n\n"
    "With --end, close the current section: appends a summary and "
    "the closing tag, then moves the cursor back up."
)

DESC_COLLATE = (
    "Carve a section out of already-written prose at an arbitrary "
    "node by specifying a line range.\n\n"
    "The selected lines are moved into a new child node, an LLM "
    "summary is generated, and the range in the parent is replaced "
    "with the section annotation block."
)

DESC_COMPRESS = (
    "Use the LLM to pick a contiguous line range matching your "
    "description and collate it into a child section.\n\n"
    "Provide a PROMPT describing what to extract, or use "
    "--aggressiveness for automated range selection.  "
    "If the model does not call the compress_collate tool, "
    "its explanation is printed instead."
)

DESC_CHAT = (
    "Have the AI speak as a specific character in the current scene.\n\n"
    "Use --as <kb.id> to specify which character the AI voices.  "
    "Without --with, this is a one-shot inline response written "
    "directly into the current node.\n\n"
    "With --with <kb.id>, opens a session sub-node for a "
    "back-and-forth conversation.  Inside the session, typing "
    "text sends it as the --with character and the AI responds "
    "as --as.  Subsequent calls without --with inside an open "
    "session continue that session automatically.\n\n"
    "In-session only: --narrate formats the line as a plain "
    "blockquote (no [Character] prefix).  --wait appends without "
    "calling the LLM.\n\n"
    "Use --end to close the session with a prose summary."
)

DESC_PLAY = (
    "Narrate a player-agency moment in GM voice, "
    "then pause for player response.\n\n"
    "Opens a play session sub-node the first time, or continues "
    "the current session.  Use --module to activate a rules "
    "module (e.g. combat, downtime).  Use --end to close.\n\n"
    "By default, play appends only what the player says "
    "(no GM / LLM). Use --pass when you want the GM to respond.\n\n"
    "Requires at least one player character (KB object tagged 'pc') "
    "to be pinned.  Use -as <key> to attribute the prompt to a "
    "specific pinned PC."
)

DESC_DESIGN = (
    "Collaborative KB design workspace.\n\n"
    "The first call opens a new design sub-node.  Subsequent calls "
    "continue the current session.  Use --module to activate a "
    "design module.  Use --end to close the session and extract all "
    "kb blocks from the sub-node into the knowledge store."
)

DESC_ADVANCE = (
    "Advance time, update fronts, and resolve consequences.\n\n"
    "Creates an advance session sub-node tracking the time jump.  "
    "Use --days to set how many days pass.  --end applies KB and "
    "timeline updates."
)

DESC_DEPLOY_INIT = (
    "Create Fly app, volume, set secrets, and generate fly.toml.\n\n"
    "Run from a project directory (lens.toml present) for "
    "single-project mode, or from a parent directory for "
    "multi-project mode (use slug=path for each --deploy-key "
    "to select which projects to deploy)."
)

DESC_DEPLOY_PUSH = (
    "Deploy (or redeploy) the Lens application image to Fly.io.\n\n"
    "Run from the directory containing fly.toml (the project "
    "directory for single-project mode, or the parent directory "
    "for multi-project mode)."
)

DESC_DEPLOY_ADD = (
    "Add a project to an existing multi-project deployment.\n\n"
    "Run from the parent directory that contains fly.toml and "
    "the project subdirectory.  Updates fly.toml and sets the "
    "project's secrets on the Fly app.  Run 'lens deploy push' "
    "afterwards to apply."
)

DESC_DEPLOY_REMOVE = (
    "Remove a project from an existing multi-project deployment.\n\n"
    "Run from the parent directory that contains fly.toml.  "
    "Updates fly.toml and removes the project's secrets from "
    "the Fly app.  Run 'lens deploy push' afterwards to apply."
)

# ═══════════════════════════════════════════════════════════════════
#  Media-generate / media-tts option help strings
# ═══════════════════════════════════════════════════════════════════

MEDIA_MODEL = (
    "[[image]] id from lens.toml "
    "(default: first block, shown as [default] when id is omitted)."
)
MEDIA_ASPECT = (
    "Aspect ratio; must be one of the backend's aspect_ratios "
    "in lens.toml (default: first listed value, "
    "or sidecar when using --from)."
)
MEDIA_SIZE = (
    "Resolution tier; must be one of the backend's sizes "
    "in lens.toml (default: first listed value, "
    "or sidecar when using --from)."
)
MEDIA_BATCH = (
    "How many images (default: 1; capped by the backend's max_batch, "
    "or sidecar batch_size when using --from)."
)
MEDIA_SLUG = (
    "Folder name under generated/ "
    "(default: slug derived from the resolved prompt, "
    "or sidecar folder when using --from)."
)
MEDIA_NEGATIVE = (
    "Optional negative prompt "
    "(default: none, or sidecar when using --from)."
)
MEDIA_FROM = (
    "Batch sidecar YAML: mount-relative "
    "(e.g. generated/<slug>/b_1.yaml) "
    "or absolute path inside mount_point.  "
    "Pre-fills prompt and flags; CLI args override."
)
MEDIA_REF = (
    "Mount-relative reference image path if supported (repeatable).  "
    "Requires s3:// mount_point."
)

TTS_MODEL = (
    "[[speech]] id from lens.toml "
    "(default: first block, shown as [default] when id is omitted)."
)
TTS_VOICE = (
    "Voice id (xAI: eve, ara, rex, sal, leo).  "
    "Default: [[speech]] default_voice if set, else eve."
)
TTS_LANG = "BCP-47 language code (e.g. en, auto)."
TTS_SILENT = (
    "Do not auto-play with ffplay after each chunk."
)

# Image / speech shared
MEDIA_SERVER_HOST = "Bind host"
MEDIA_SERVER_PORT = "Bind port"

# ═══════════════════════════════════════════════════════════════════
#  Deploy option help strings
# ═══════════════════════════════════════════════════════════════════

DEPLOY_MODE = (
    "fly: Fly remote builder without Depot (--depot=false).  "
    "depot: Depot remote builder (--depot=true).  "
    "local: build on this machine (--local-only)."
)
DEPLOY_KEY_HELP = (
    "SSH deploy key.  "
    "Single-project: path to key file (slug derived from directory name).  "
    "Multi-project: slug=path, repeated for each project "
    "(e.g. --deploy-key proj-a=~/.ssh/key_a "
    "--deploy-key proj-b=~/.ssh/key_b).  "
    "The slugs determine which projects are included."
)

# ═══════════════════════════════════════════════════════════════════
#  Pin sub-command argument & option help
# ═══════════════════════════════════════════════════════════════════

PIN_KB_ID = "Knowledge object ID (type.key)"
PIN_KB_ID_OPT = "Knowledge object ID (type.key); omit to see usage"
PIN_NODE = "Target node address (default: cursor)"
PIN_EXTRA_IDS = "Additional ID(s) (repeatable)"
PIN_NODE_OPT = "Target node address (use the positional argument instead)"
