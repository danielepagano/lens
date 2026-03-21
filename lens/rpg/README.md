# RPG (core dataset)

The **`rpg`** bundled dataset is the ruleset-agnostic layer for tabletop-style play in Lens: `rules.rpg`, a default `rules.system` stub, templates (`pc`, `loc`, `npc`, …), and `design.*` modules. Operators **`play`** and **`advance`** are gated on this dataset.

See [RPG Design Doc](../../docs/rpg-design.md) and the main [CLI reference](../cli/README.md).

## Enabling

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg"]
```

List **`dnd` after `rpg`** when you want D&D 2024 reference content and a full `rules.system` override:

```toml
datasets = ["rpg", "dnd"]
```

(Later entries in `datasets` shadow earlier ones.)

## Pins for `lens play`

- `rules.system` and `rules.rpg`
- At least one `pc.*` object pinned

With `["rpg", "dnd"]`, `rules.system` resolves to the D&D rules body from the `dnd` dataset.
