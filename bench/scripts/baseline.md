# Use Case: Develop & Baseline

Run a scenario end-to-end, verify it works, establish baseline scores.

Prerequisite: read `bench/agent.md` for setup and scoring mechanics.

## Steps

1. **Create the project** with `bench/tools/setup_bench.py` (see `bench/agent.md`) and **`export PROJECT`**.
2. **Run Setup** — from the **repo root**, `bash bench/scenarios/<scenario>_setup.sh` if that file exists; otherwise run the Setup commands from the scenario `.md` in order.
3. **`cd` into the project directory** — all benchmark `lens` steps run from `$PROJECT`.
4. **`lens check`** (optional but recommended; required in `bench/agent.md`).
5. **Run each benchmark step:**
   - Execute the command from the step
   - Capture output from stdout. For `write`/`play`, the written text also appears in the narrative node file. For `edit`, the proposal is in stdout and the staged diff (`git diff`) — the node file still shows the original until accepted.
   - Do **not** commit between steps — operators auto-progress within a transaction
6. **Evaluate** each step against the scenario's evaluation criteria using the 1–5 scale
7. **Report (required):** run `report.py init --scenario … --profile … --project-dir "$PROJECT"` (see `bench/agent.md`).
8. **Complete the report:** fill `steps` and `evaluation` — preferably **`python bench/tools/report.py merge bench/reports/your_report.json < patch.json`** (updates JSON and HTML together), or hand-edit JSON then **`report.py render`** or **`report.py sync`** so HTML is never stale.

## What to look for

- Do the setup commands run without errors?
- Does each step produce non-trivial output?
- Are baseline scores reasonable (≥3 on most criteria)?
- Any criteria consistently scoring 1–2? That's a bug or a prompt problem.
