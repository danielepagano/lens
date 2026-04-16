# Lens Backlog

- **Revise non-companion system prompts using persona-prompting lessons**
  - Scope: `write`, `edit`, `section`, `design`, `play`, `advance`, `remember`, `session.summary`, `compress` / `compress.auto` in `lens/prompts/default.toml`. The chat/companion prompts are already covered by the companion-dataset work; these are the writing / summarization / RPG / design prompts. The companion-specific learnings (vibe / flirtation economy / provocation prompts) are *not* transferable — do not copy that energy into writing-side prompts.
  - Pick up after the companion voice layer has real usage feedback, so the lessons are validated before a cross-prompt pass. Plan file seed: `/Users/daniele/.claude/plans/partitioned-nibbling-stream.md` (Part E).
  - Transferable learnings from the persona-prompting research round (see research below):
    1. **Latent-space steering over rule lists.** `design.system`, `advance.system`, `play.system` lean on numbered procedural "HOW TO WORK" sections; long procedurals steal attention from the conceptual payload and can induce format-locking. Replace rule enumerations with dense conceptual attractors where the rule is load-bearing, drop restatements.
    2. **Format-locking audit.** Any prompt handing the model a repeating numbered template risks the Procrustean failure (pick format first, cram content in). Audit each for "did I give it a shape it will lock onto?" and loosen where the shape isn't required.
    3. **Anti-recitation paragraph port.** `write.system` already has a specific "avoid 'her green eyes' filler, make details do work" rule. Scale-adapted versions belong in `play.system` (GM scene beats) and anywhere else description can drift into lazy filler.
    4. **Few-shot negative/positive example pairs.** `write.system` uses one and it's effective. Most other prompts have zero examples. Adding one short pair per prompt — the specific failure we see in practice and the fix — is cheap and high-leverage. Start with `play.system` (generic NPC voice) and `advance.system` (too-much narrative prose in updates).
    5. **Demonstrative openers.** "Every prompt is both data and instruction on every level." The first paragraph should already be written in the register we want back. `design.system`/`play.system` open with flat descriptors — audit whether a voiced opener steers better.
    6. **Goal not topic.** Instruction templates just forward `{prompt}`. A docs/UX nudge toward goal-shaped prompts ("help me figure out why X is falling flat" rather than "write about X") — worth flagging even though it's a docs change, not a prompt change.
    7. **Name failure modes by shape.** A 2–3 line "what this is not" section actively steers away from the failure we see most often, and it's cheap. Add one to prompts that lack it.
    8. **Token budget.** Prompts over ~400 words are compression candidates. `design.system`, `advance.system`, and the `compress.*` family are the biggest; each likely 20–30% compressible without losing guidance. In particular since we changed chat from "full text" to [turns](lens/core/turns.py) we may not need so much "the blockquoted text is the user" guidance (just a quick mention may suffice)
   - **[stunspot — On Persona Prompting](https://medium.com/@stunspot/on-persona-prompting-8c37e8b2f58c)** *(via playwright)* — the load-bearing source for *how* the prompt should be written. Key claims I'm pulling on:
      - **"Latent space steering, not instruction writing."** Prompts don't control models the way code controls computers; they push the model into regions of concept-space. Practical consequence: invoke the vibe with dense, concrete reference points; don't write a rule list.
      - **Conceptual parallax.** A vibe defined by the intersection of 3–5 specific references ("Sassoon meets Hall by way of Vaynerchuk and Drucker") is tighter than any paragraph of adjectives. For a friend companion: a few anchor words ("a friend who texts in fragments", "the kind of tired that makes you honest", "half-finished drawings in the margin") define the region more tightly than "warm and witty".
      - **"Every prompt is both data and instruction on every level of informational encoding present."** The companion prompt's own prose *is* a demonstration of the vibe it wants. If it reads like marketing copy, the model will write like marketing copy. So the prompt itself must be written in the register we want back.
      - **Format-locking** is exactly what's happening in the user's output: the model picked "reply + physical description beat" as a template and crammed every response into it. Breaking format-lock is a direct goal of this change.
      - **Token budget / attention dilution.** Every sentence of rules steals from the conceptual payload. Keep it dense.
      - **"The way the model talks now changes how it will talk in the future."** The first exchange of a companion session sets the trajectory — the few-shot voice samples in `id.companion` are load-bearing.
   - **[jenova.ai — AI Roleplay Prompts](https://www.jenova.ai/en/resources/ai-roleplay-prompts)** *(via playwright)* — concrete character-sheet pattern. Five elements: (1) core identity with **internal conflict**, (2) specific speech patterns, (3) emotional triggers, (4) behavioral constraints, (5) few-shot voice samples. The Inspector Maren Solberg example is worth borrowing almost verbatim:
      - Internal conflict: *"You're brilliant at reading people because you understand darkness intimately — and you're not sure if that makes you good at your job or just broken."*
      - Speech patterns defined by what the character **does AND doesn't** do: *"She never says 'I feel' — she describes physical sensations instead. She interrupts when she's figured something out. She goes silent when she's wrong."*
      - Emotional triggers as situation→reaction pairs: *"Cases involving children make her hands shake. Being called 'cold' by colleagues makes her overcompensate with forced warmth."*
      - Few-shot samples: 2–3 short exchanges, each targeting a different mood.
      - Headline: *"The AI doesn't want small talk. It wants chaos."* — a character needs **tension** loaded into the sheet or it defaults to chatbot pleasantry.
   - **[aicompanionguides.com — Building My Perfect AI](https://aicompanionguides.com/blog/building-my-perfect-ai-custom-prompts/)** *(via playwright)* — practical, 500+ prompt tests. Key ideas:
      - **Goal, not topic.** "Let's talk about movies" is weak; "Help me understand why I keep rewatching comfort movies" is strong. 3× more engaging in their testing.
      - **Kill the vague.** "Be supportive" → fortune-cookie. "Respond like a friend who's been through similar struggles and isn't afraid to call me out on my BS" → transformed. Specificity is the biggest single lever.
      - **Strong opinions about specific things + curious about other perspectives** — the shape we want.


- **Public Release Readiness**
   - License
   - Clean up documentation
      - Focused main readme
      - Refreshed main design doc
      - Actual user manual for playing RPGs (dataset readme) with simpler bootstrap
   - Remove hard-coding of usage of gitlab/fly, make modular/CI-friendly
      - Remove reliance on specific env vars
   - Better "no desktop" usage
      - Better init tooling/docs
      - Run server one level above projects and support project switching in app
      - Streamline project creation/management (from app if above?)
      - Ensure manual editing is solid
      - Some way to have a hook in a repo toto trigger deploy automatically, maybe even on lens releases
   - Improve maintainability
      - Explicit contribution guidelines?
      - Git hook/CI/merge rules
      - Clean up of UI in particular: smaller modules, cleaner interfaces
   - Use and tweak usability over time
   - When ready
      - Force push to clean up history
      - Make repo public
      - Immediately add main branch protection
