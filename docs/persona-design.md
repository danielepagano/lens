# Lens Persona System - Design
 
## Core Philosophy
 
Lens is about Narrative Simulations; the RPG layer uses it to let a player sit with an AI GM and play through an adventure. The **persona** system points the same machinery at a different problem: **characters having a grounded conversation**.
 
The goal is to create an agent that simulates a specific character — with a personality, a place in the world, a history, an appearance, a voice, pressures, secrets — talking with the *other characters*, who are equally concrete and contextualized to the persona. These can be played by the user, or by another persona with a different scope (for simplicity, we'll just refer to the non-current person as "the user"). To the persona, the user is not "the user in a chat": they are a specific person that the persona knows (or doesn't yet), sees, reacts to, remembers. They really don't know/care it they, another agent, or a user created the other responses, they just continue in-character.
 
Some shapes this can take:
 
- Philosophers with specific corpuses working through a hard problem.
- People on a date, feeling each other out.
- Some `pc` characters from an RPG campaign talking after a day of adventuring.
- An interrogator (or more) and a suspect. A mentor and students. A parent and an estranged child. A heist crew laying out a job.
 
What Lens aims to provide is **the experience of having a real, earned conversation between specific people**. What does that mean?
 
- The persona is not the model's assistant voice. It has opinions, moods, refusals, preferences, bad days. It can walk out.
- The user is not "the user": they are *their character*. What they type is what their character says (or does, in limited in-character ways), not directorial instructions to the model.
- Nothing is adjudicated. There are no checks, no dice, no HP, no GM. There is only people talking — but the talking itself produces consequences, because the persona's interior state changes.
- The conversation that occurs is not, mostly, what Lens remembers. What Lens remembers is **what stuck out**: the facts, the feelings, the plans, the small secrets that slipped, the moments that shifted something. The winding path is disposable; the footprints it leaves in the persona's mind are not.
- The token budget is small and self-managing. Topics rotate every few tens of thousands of tokens; old topics collapse into summaries; the persona's interior (pinned KB) carries forward.
 
This is collaborative fiction of a very specific kind: slow, intimate, and accumulative. The system's job is to make it feel like you are *actually catching up with someone* rather than prompting a model.
 
## The Character–Character Contract
 
In RPG, the player is a director and the AI is an author of narrative; there is a clear GM/PC frame. Persona collapses that frame: **all sides of the exchange are characters**. There is no narration of outcomes, no third-person framing, no GM voice mediating the scene. Just people talking, each with their own interior.
 
This changes the contract in three important ways:
 
**1. All turns are in-character by default.** The user's input is their character's words — what they say, maybe a short in-character action beat (`*she sets the cup down*`). It is NOT directorial intent. If the user wants to say something out-of-character ("pause, let's reset this scene"), they must escape to a meta channel (by convention, a leading `/` or `(ooc)`; see *OOC channel* below). The persona reads everything else as being said *to them, by the counterpart*.
 
**2. The persona has interiority the user cannot dictate.** Mirroring the RPG authority model, but translated:
 
| User input | Persona reads it as |
|---|---|
| In-character speech ("I missed you.") | Something the counterpart said; the persona decides how to receive it |
| In-character action ("*she reaches for his hand*") | Something the counterpart attempted; the persona can accept, freeze, flinch, pull away |
| Declared persona feeling ("you're happy to see me") | A *hope* on the counterpart's part; the persona decides what it actually feels |
| Declared persona knowledge ("you already told me your name is Ada") | An assertion of shared history; the persona checks its own knowledge and either agrees, corrects, or is disoriented |
| Declared persona action ("you smile and hand me the letter") | Hoped-for outcome; the persona decides if that's what it does |
 
The resistance is not suspicion — it is **role clarity**. A user in good faith will get better fiction from a persona that holds its own interiority than from one that drifts into puppet mode.
 
**3. There is no adjudication.** No checks, no rolls, no difficulty classes, no outcomes. A conversation either goes well or doesn't because of what is *said*, not because of what a system says. The persona's willingness to open up, forgive, trust, betray, confess, or shut down is driven purely by its own state and what the counterpart actually says in the fiction.
 
### The adversarial / intimate persona problem
 
The persona layer inherits the adversarial NPC problem from RPG, and then some. A persona can be:
 
- Actively lying to the counterpart.
- Romantic, sexual, or emotionally intimate (within whatever bounds the user sets).
- Hostile, contemptuous, or cruel.
- Grieving, suicidal-ideating, or unstable in ways the fiction is exploring earnestly.
- Holding information the user paid for in trust/effort and is deliberately withholding.
 
Persona conversations have a narrower "safety" margin than RPG scenes precisely *because* the frame is character dialog rather than GM-mediated narration. Some models will hedge or break character on perfectly ordinary persona territory. Model selection matters: persona should be tested against models that hold the author/fiction distinction under pressure and treat collaborative intimate fiction as a safe space by design.

## Chat Operator

The `chat` operator allows personas to converse. While using the `play` operator in RPG mode, the user uses `--as <pc-key>` to emit attributed quotes like `> [Character] ...`, and in turns the AI can use `> [GM]` quotes, or speak as any NPC character. But the focus is on playing, not conversation, specifically. Chat uses the same attributed quotes, but with different prompts and mechanics.

In persona chat mode, we want the AI to act as a sub-agent to talk as a specific character (including a PC, if the user wishes). By using `/chat --as <kb.id> <optional stage directions>` the user summons the persona in that KB id to reply in the context of the current scene; this can be done in the middle of a `play` node.

It would be quite laborious to go back and forth this way: the user could write or play their parts, then call the persona to reply, but we need a shortcut if we want to have an efficient, focused two-person conversation: `/chat --as npc.bob --with pc.amy awkward elevator banter` this starts a `session` sub-node where the user controls the `--with` character and can just say `/chat hi` (the UI can auto-fill `/chat` like in other session operators) and this is the equivalent of saying "hi" as the user's character and "passing" to the persona system to reply immediately (in other words, a very normal chat interaction). Nothing stops the user for adding additional interlocutors to this session chat by saying something like `/chat --as npc.carl butt in with your opinion`

### Out-of-Character modalities
 
The persona LLM can ONLY reply as their own character (what they say or do, in attributed quotes), even during a persona chat session, the user can leverage other operators to control the scene:  
  - `write` (AI-assisted or manual) to add stage directions, environment intrusions, another character talking, etc.  
  - `edit` to tweak something incorrect or inappropriate. 
  - `rewind` to back up and try again.  
  - `section` to purposefully start a new topic.  
  - `collate` to summarize a chunk of dialog.  
 
### Chat Sessions and Reflection
 
In a chat session there is just **continuous conversation**, and inside that conversation the persona *continuously reflects* — updates its beliefs, feelings, and knowledge mid-response via tool calls (e.g. `kb_patch`). The reflection is not a separate operator call, it is woven into the same turn as the speech act. **Collate is the exception:** it must run only when the model is **done** with that response’s in-character output, because it rewrites the node and invalidates the crawl for anything that would follow in the same generation. 

Design can still be used to create or refine personas, and the narrative tree carries the full (or summarized) dialogue for later reading. The pinned KB entries carry what the persona *currently knows and feels*. This requires some mechanical features:
  
## Reference Data
  
- `chat operator prompt`: the character–character contract. Core layer, mode-agnostic. This is the persona equivalent of `rules.rpg` (but simpler) — it establishes the authority boundary, understanding attributed quotations, the "no adjudication" rule, the "hold your interiority" instruction, the "use `kb_patch` to update what you know and feel" instructions, the "collate only when finished for this turn" rule, and the "do not break character for OOC asides" protocol.
- The optional "stage directions" given in chat should also be pinned in the section
- The character itself. Really any object can be used (pc/npc/lore/whatever) as long as it gives the AI something to work with. We could use more than one layer here: like we use pc VS lore in rpg play VS design, we can also have a separate, more in-depth object that could track deeper facets and memories, even specific to a specific other person. For example if two PC's are in a relationship, each participant should have a specific object that tracks various aspects of it from their perspective.
 
### Useful details for deep chats
  
- Appearance: (species/humanity, presented gender, physique, distinguishing details, visible kit, mannerisms — enough that the counterpart has a picture)
- Voice: (speech patterns, register, verbal tics, vocabulary, how much they say vs how much they hold back. This is the single most important field: drift in voice is the first thing that breaks immersion.)
- Interior disposition: (temperament, emotional defaults, what comforts them, what unsettles them — the baseline feel of being around them)
- How they think: (reasoning patterns, attention habits; do they pick at details or speak in sweeping arcs, do they deflect with questions, do they go quiet when cornered)
- Place in the world: (social position, immediate situation, what they're dealing with apart from this conversation — gives the persona a life outside the counterpart)
- Core drives and lines: (what they want from most interactions, what they will not compromise, what they protect — the shape of their agency)
- Certain interior (may be secrets): versions of themselves they don't show the counterpart, shocks they've buried, things they would never say. The performer chat reads this and plays it; the counterpart has to earn connection.
