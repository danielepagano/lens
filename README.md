# Lens

Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

## Setup

```bash
cd /path/to/lens && poetry install
```

To run `lens` from any directory (e.g. your content repos):

**Option A — In-project venv + PATH** (recommended):

Poetry uses a global venv cache by default. Create an in-project venv so the path is stable:

```bash
cd /path/to/lens
poetry config virtualenvs.in-project true
poetry install
```

Then add to your `~/.zshrc`:
```bash
export PATH="/path/to/lens/.venv/bin:$PATH"
```

**Option B — Use Poetry's venv path** (if you didn't use in-project):

```bash
poetry -C /path/to/lens env info
```
Add the `Path` + `/bin` to your PATH (e.g. `.../lens-LtL4t6e--py3.14/bin`). Note: this path can change if Poetry recreates the venv.

**Option C — Use poetry -C** (no PATH change):
```bash
poetry -C /path/to/lens run lens init
```

## Usage

1. Create a git repo with your lens project data
2. Initialize the Lens project (creates `lens.toml`, `knowledge/`, `narrative/`, etc.):

```bash
lens init
```
3. Select a narrative (creates the folder and root `_node.md` if needed):

```bash
lens use my-campaign
```
4. Run lens commands!

```bash
lens stats # counts objects and lists narratives
```


## Development

```bash
poe pyright  # Type checking
poe lint     # Linting
poe test     # Run tests
```
