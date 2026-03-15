# Lens Backlog

## Operators  

- Iterate on `play`: make it functional and fun
- Add dedicated aspects as needed:
  - **`encounter`** for combat
  - **`converse`** for chatting if needed
  - **`advance`** to maitnain front
  - **`design`** is always expanding for more use cases
- **`attach`** — Attach media (images, maps, references) within a node. 
  - Store the media under a mount location specified in the project.
  - App can upload to mount (or content can already be prrsent)
  - Support drive mounts or cloud storage (s3 etc as needed) via adapters
  - Attaching an uploaded file creates an appropriate viewer: img tag, video player, etc. in the given spot of the markdown doc
  - Can browse directories and files in mount to provide autocomplete when attaching orselecting upload location

## Platform

- **Direct editing** of markdown nodes; also surfaces line numbers 
- Remaining UI for **KB operations**
- *Cloud Deployment**: See [Deployment Design](./deployment-design.md). Local machine deploy wirh dynamic dns and caddy already implemented.

## Ideas

### **Background KB extraction**

Faceted context compression: the write-side complement to RAG. A cheap/fast model (8B or equivalent) runs over recently committed narrative and updates opted-in KB objects using per-type extraction instructions. Extraction at checkpoint makes them stick into the right KB objects. Key design decisions: 

- **Trigger**: checkpoint. Runs when the user commits a checkpoint, which already has the right semantics (deliberate, meaningful boundary). Produces a single transaction with all proposed KB changes for user review — same audit pattern as the `edit` operator.
- **Opt-in via dot-tag**: an object is eligible for extraction only if it carries a `remember.*` dot-tag (e.g. `remember.person` on `person.alice`). The `remember.person` KB object contains the extraction instructions and template hints for that type. One tag solves both the locking problem (only explicitly opted-in objects are touched) and the hint delivery problem (instructions live in the linked object, not in the object being updated).
- **In-narrative signal**: the AI can emit `<!-- ai:remember:type.key -->` as a plain HTML comment in narrative output to flag that a specific object should be queued for extraction at the next checkpoint. This is a deterministic Lens trigger, not a tool call — Lens detects it on parse and queues accordingly.
- **Diffed, not overwritten**: the cheap model returns a full proposed object; Lens uses git transactions to effectively diff it against the current version and gives a human-reviewable audit trail.
