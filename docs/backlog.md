# Lens Backlog

## Operators  

- Iterate on `play`: make it functional and fun
- Add dedicated aspects as needed:
  - **`encounter`** for combat
  - **`converse`** for chatting if needed
  - **`advance`** to maitnain front
  - **`design`** is always expanding for more use cases
- **`attach`** — Attach media (images, maps, references) within a node. Store the media in an S3 bucket.

## Platform

- **UI for cursor operators**: invoke from UI so we can stream content to markdown, not just console output 
- **UI for editing operators**: Implement the "After-the-fact sectioning", "Rewind", and "Edit range" UI (selecting lines/ranges from CLI is not practical).
- Additional UI for **KB operations**
- Any other commands
- **Deployment & Security**: See [Deployment Design](./deployment-design.md).

## Ideas

### **Background KB extraction**

Faceted context compression: the write-side complement to RAG. A cheap/fast model (8B or equivalent) runs over recently committed narrative and updates opted-in KB objects using per-type extraction instructions. Extraction at checkpoint makes them stick into the right KB objects. Key design decisions: 

- **Trigger**: checkpoint. Runs when the user commits a checkpoint, which already has the right semantics (deliberate, meaningful boundary). Produces a single transaction with all proposed KB changes for user review — same audit pattern as the `edit` operator.
- **Opt-in via dot-tag**: an object is eligible for extraction only if it carries a `remember.*` dot-tag (e.g. `remember.person` on `person.alice`). The `remember.person` KB object contains the extraction instructions and template hints for that type. One tag solves both the locking problem (only explicitly opted-in objects are touched) and the hint delivery problem (instructions live in the linked object, not in the object being updated).
- **In-narrative signal**: the AI can emit `<!-- ai:remember:type.key -->` as a plain HTML comment in narrative output to flag that a specific object should be queued for extraction at the next checkpoint. This is a deterministic Lens trigger, not a tool call — Lens detects it on parse and queues accordingly.
- **Diffed, not overwritten**: the cheap model returns a full proposed object; Lens uses git transactions to effectively diff it against the current version and gives a human-reviewable audit trail.
