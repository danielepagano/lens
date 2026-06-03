# Sandbox-human regression checklists (SH-*)

Use after `poe build-ui` and a prepared fixture:

```bash
poe e2e-sandbox --fixture remember_section --tokens 80 --tps 2
# or: poe mock-llm + bench project with profile llm_mock (see bench/llm_profiles/llm_mock.toml)
# Per-request: add tokens=N tps=Y to any operator prompt
```

## SH-01 — Workflow strip (`workflow_write_long`)

- [ ] Open printed URL; run `/write` with a long prompt.
- [ ] `[data-testid="workflow-steps"]` lists **Generate** and optional **Compress** (if eligible).
- [ ] Activity line (`workflow-activity`) updates during the run.
- [ ] **Skip** appears on optional steps before they start.

## SH-02 — Skip remember (`remember_section`)

- [ ] `/section --end` (or UI equivalent).
- [ ] Skip **Updating memory** while summarize runs.
- [ ] Parent shows summary; `knowledge/lore/testbench.md` unchanged.

## SH-03 — Cancel mid-remember (`remember_section`)

- [ ] Let remember start; click step **Cancel** (whole-preview discard).
- [ ] Preview discarded; no partial KB patch on lore.testbench.

## SH-04 — Skip vs Cancel auto-compress (`auto_compress_low_threshold`)

- [ ] `/write` on seeded large node → plan includes compress step.
- [ ] **Skip** compress: generation remains in preview.
- [ ] Separate run: **Cancel** during dirty compress step discards entire preview.

## SH-05 — Play GM voice (`rpg_play_pins`)

- [ ] `/play` with player intent; GM does not narrate PC choices.
- [ ] See [`bench/scenarios/play_gm_voice.md`](../../bench/scenarios/play_gm_voice.md) rubric.

## SH-06 — Design tools (`rpg` + design module)

- [ ] `/design` stream shows structured tool activity, not raw fence spam in preview.
- [ ] `/design --end` extracts KB blocks sensibly.
