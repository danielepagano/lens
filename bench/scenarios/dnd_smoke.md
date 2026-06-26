# lens-dnd dataset smoke test

Verifies that the bundled `lens-dnd` dataset registers correctly — KB content
is resolvable and the `balance_encounter` LLM command tool is visible via the
command registry.  No LLM invocation required (infrastructure layer only).

```config
datasets:
  - rpg
  - lens-dnd
```

**Prompt keys exercised:** none (tool registration, not LLM output)

## Setup

Create a bench project with both `rpg` and `lens-dnd` datasets enabled.

```bash
lens check
lens commit --allow-empty
```

## Steps

### `kb_content_available`

Stat blocks, spells, and equipment from the lens-dnd dataset must be resolvable
through the Lens KB.  At least one stat block and one spell should return body
content.

```bash
lens kb get stat.zombie
echo "---"
lens kb get spell.fire-bolt
```

### `tags_available`

Tag-based search must work against lens-dnd objects.

```bash
lens kb with-tag type:undead --type stat
```

### `balance_encounter_registered`

The `balance_encounter` command tool must be registered and dataset-gated.

```bash
python -c "
from lens.core.project import require_lens_context
from lens.core.command_tools import get_command_registry
from pathlib import Path

git_root, project_root = require_lens_context(Path.cwd())
registry = get_command_registry(project_root)

assert 'balance_encounter' in registry, 'balance_encounter NOT in command registry'
tool_def, fn = registry['balance_encounter']
assert 'lens-dnd' in tool_def.limited_to_datasets, (
    f'expected limited_to_datasets=[lens-dnd], got {tool_def.limited_to_datasets}'
)
assert tool_def.description, 'description is empty'
assert 'required' in tool_def.parameters.get('required', []), 'schema missing required fields'
assert callable(fn), 'handler is not callable'
print(f'balaŉce_encounter registered, limited_to_datasets={tool_def.limited_to_datasets}')
print(f'description: {tool_def.description[:80]}...')
"
```

## Evaluation criteria

1. **KB accessible** — `lens kb get` returns content for a known stat block and spell
2. **Tags work** — tag-based queries return results from the lens-dnd dataset
3. **Tool registered** — `balance_encounter` is present in the command registry with correct gating
4. **No errors** — every command exits 0 with meaningful output

## Prompt iteration guidance

Not applicable — this is an infrastructure smoke test with no LLM output.
