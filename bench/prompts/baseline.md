# Use Case: Develop & Baseline

Run a scenario end-to-end, verify it works, establish baseline scores.

Prerequisite: read `core.md` for setup and scoring mechanics.

## Steps

1. **Create the project** with `bench/tools/setup_bench.py` (see core.md)
2. **`cd` into the project directory**
3. **Run setup commands** from the scenario's Setup section, in order
4. **Run each benchmark step:**
   - Execute the command from the step
   - Read the output (streams to stdout; also check `narrative/story/_node.md`)
   - Do **not** commit between steps — operators auto-progress within a transaction
5. **Evaluate** each step against the scenario's evaluation criteria using the 1–5 scale
6. **Write the report JSON** to `bench/reports/` and render to HTML

## What to look for

- Do the setup commands run without errors?
- Does each step produce non-trivial output?
- Are baseline scores reasonable (≥3 on most criteria)?
- Any criteria consistently scoring 1–2? That's a bug or a prompt problem.
