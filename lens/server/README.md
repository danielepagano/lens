# Lens API server

FastAPI server that exposes the current Lens project (or dataset) over HTTP.

## Starting the server

Run from a directory inside a Lens project (a repo that contains `lens.toml`):

```bash
lens serve
# optional: --host 0.0.0.0 --port 8080
# development: --reload to restart when lense code changes (default to true)
```

The server binds to `127.0.0.1:8000` by default. It uses the project (or dataset) rooted at the nearest `lens.toml` above the current working directory.

- **Project mode**: Full API. Narrative tree and node content are available; `active_narrative` and cursor come from `lens.toml`.
- **Dataset mode**: If `lens.toml` declares a `[dataset]`, the server still runs but narrative routes return empty or 404 (no narrative nodes in a dataset).

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness; returns `{"status": "ok"}`. |
| GET | `/stats` | Project stats: active narrative, cursor, pending state, dataset, KB counts. |
| GET | `/tree` | Narrative tree: list of root nodes with recursive `children` (address, key, is_folder). Empty in dataset mode. |
| GET | `/node/{address}` | Node by address (e.g. `design-test/dragon-kurmat`). Returns `address`, `content`, `is_folder`, `children`. 404 in dataset mode or if node not found. |

All routes use the same `ProjectSession` (project/dataset and active narrative) fixed when the server starts.
