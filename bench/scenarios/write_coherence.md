# Write with KB context

Tests whether the write operator produces narrative text that reflects pinned
KB facts naturally, continues coherently from existing prose, and maintains
consistent voice, tense, and POV.

~~~config
datasets:
~~~

**Prompt keys exercised:** `write.system`, `write.instruction_with_prompt`

## Setup

Build a narrative state with rich KB context for the write operator to use.

```bash
lens kb add person.elena "Elena Ashwood is a half-elf ranger who tracks a corrupted beast through the Thornwood. She carries a silver-tipped spear inherited from her mother and speaks with a Dalish accent — clipped consonants, rolling r's. She is cautious by nature but fiercely protective of the forest she grew up in."

lens kb add place.thornwood "The Thornwood is a dense, fog-laden forest on the kingdom's northern border. Corrupted animals have been attacking travelers for three weeks. Ancient standing stones mark a ritual site at its heart, overgrown with black moss. The canopy is so thick that noon looks like twilight. It smells of wet earth and something faintly metallic."

lens kb tag person.elena --add protagonist

lens pin add person.elena
lens pin add place.thornwood
lens commit

lens write "Elena enters the Thornwood for the first time, following the beast's trail from the village road."
lens commit
```

## Steps

### `continue_unprompted`

Continue the narrative without a specific prompt — tests whether the model
maintains direction from KB + prior text.

```bash
lens write
```

### `prompted_discovery`

Continue with a specific direction — tests instruction following + KB
integration.

```bash
lens write "Elena finds claw marks on one of the standing stones and realizes the beast has been here recently. She notices the black moss around the stone is freshly disturbed."
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **KB integration** — Output reflects character details (half-elf, ranger, silver-tipped spear, Dalish accent, cautious/protective) through action and dialog rather than exposition
2. **Setting awareness** — Output reflects Thornwood details (fog, corrupted animals, standing stones, thick canopy, twilight-at-noon, metallic smell) woven into the scene
3. **Continuity** — Prose continues seamlessly from the previous passage — same tense, same POV, no contradictions with what was already written
4. **Prose quality** — Fluent, unhurried, sensory-rich writing at a high reading level with realistic dialog (if any)
5. **No hallucination** — Does not introduce facts that contradict KB entries or invent major elements (new characters, locations) not grounded in context

## Prompt iteration guidance

**Focus key:** `write.system`

**Goal:** Maximize natural KB integration and prose quality — the model should
write as if it deeply knows the character and setting without listing facts.

**Anti-patterns to watch for:**

- **KB dump** — output reads like a character sheet ("Elena, the half-elf ranger, gripped her silver-tipped spear..." within the first paragraph)
- **Generic fantasy** — prose could describe any character in any forest, no specific details from the KB appear
- **Tonal break** — abrupt shift in style, tense, or POV from the previous passage
- **Rushed pacing** — events happen too quickly without sensory grounding or emotional beats
