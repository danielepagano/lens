#!/usr/bin/env python3
"""Create an empty Lens benchmark project with a real LLM profile.

Usage::

    # From the repo root:
    python bench/tools/setup_bench.py --profile local_thinking
    python bench/tools/setup_bench.py --profile deepseek --scenario bench/scenarios/write_coherence.md
    python bench/tools/setup_bench.py --profile local_thinking --project-dir path/to/mybench
    python bench/tools/setup_bench.py --profile deepseek --print-env   # stderr: export PROJECT='…'

Without ``--project-dir``, the project is created under ``bench/projects/`` (gitignored),
still with a unique ``lens_bench_*`` directory name.

The script creates a git repo, runs ``lens init``, applies the profile's ``[[llm]]``
and optional datasets from the scenario's ``config`` block, then ``lens use default``
(equivalent: active narrative ``default`` with an empty root ``_node.md``).

**Bench scenarios** own narrative and KB setup — see each scenario's **Setup** section.

The project directory is printed to stdout so a calling agent or script can
capture it.
"""

from __future__ import annotations

import argparse
import io
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, cast

import tomli_w

# Ensure the repo root is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BENCH_PROJECTS_PARENT = _REPO_ROOT / "bench" / "projects"
sys.path.insert(0, str(_REPO_ROOT))

from lens.core.commands.init import init_project  # noqa: E402
from lens.core.commands.use import use_narrative_for_project  # noqa: E402
from lens.core.storage import Storage  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def _load_profile(profile_path: Path) -> dict[str, object]:
    """Read an LLM profile TOML and return the ``[llm]`` table."""
    with profile_path.open("rb") as fh:
        data = tomllib.load(fh)
    llm = data.get("llm")
    if not isinstance(llm, dict):
        raise SystemExit(f"Profile {profile_path} must contain a [llm] table")
    result: dict[str, object] = dict(llm)  # type: ignore[arg-type]
    return result


def _load_scenario_datasets(scenario_path: Path) -> list[str]:
    """Read a scenario Markdown and return the ``datasets`` list from its config block.

    Scenarios contain a fenced config block in one of two forms::

        ```config
        datasets: rpg
        ```

        ```config
        datasets:
          - rpg
          - companion
        ```

    An empty ``datasets:`` line with no list items means no extra datasets.
    """
    import re

    text = scenario_path.read_text(encoding="utf-8")
    m = re.search(r"```config\n(.*?)```", text, re.DOTALL)
    if not m:
        return []
    lines = m.group(1).splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("datasets:"):
            raw = stripped[len("datasets:"):].strip()
            if raw:
                # Inline form: datasets: rpg, companion
                return [d.strip() for d in raw.split(",") if d.strip()]
            # YAML list form: collect following "- item" lines
            result: list[str] = []
            for follow in lines[i + 1:]:
                fs = follow.strip()
                if fs.startswith("- "):
                    result.append(fs[2:].strip())
                elif fs and not fs.startswith("#"):
                    break
            return result
    return []


def _load_scenario_include_testing(scenario_path: Path) -> bool:
    """Read ``include_testing`` from a scenario's config block (default ``True``).

    The ``testing`` dataset is added to every bench project because most scenarios
    rely on its cast (``pc.elena`` and friends).  It also registers
    ``rules.skirmish`` as a ``play`` module, which contaminates any scenario that
    tests *which* module a model chooses on a different dataset: the model is
    offered a foreign entry whose description matches the same trigger.  Such a
    scenario opts out with::

        ```config
        datasets:
          - rpg
          - lens-dnd
        include_testing: false
        ```
    """
    import re

    text = scenario_path.read_text(encoding="utf-8")
    m = re.search(r"```config\n(.*?)```", text, re.DOTALL)
    if not m:
        return True
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("include_testing:"):
            value = stripped[len("include_testing:"):].strip().lower()
            return value not in {"false", "no", "0"}
    return True


def _apply_bench_lens_config(
    project_dir: Path,
    profile: dict[str, object],
    datasets: list[str],
) -> None:
    """Set ``[project].datasets`` and a single ``[[llm]]`` entry from the profile."""
    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg: dict[str, Any] = tomllib.load(fh)
    raw_project = cfg.get("project")
    project: dict[str, Any] = (
        dict(cast(dict[str, Any], raw_project)) if isinstance(raw_project, dict) else {}
    )
    project["datasets"] = datasets
    cfg["project"] = project

    bench_entry: dict[str, object] = {"id": "bench"}
    for key in (
        "base_url",
        "model",
        "api_key_env",
        "temperature",
        "timeout_seconds",
        "first_token_timeout_seconds",
    ):
        if key in profile:
            bench_entry[key] = profile[key]
    cfg["llm"] = [bench_entry]

    with io.BytesIO() as buf:
        tomli_w.dump(cfg, buf)
        lens_toml.write_bytes(buf.getvalue())


def setup_project(
    profile_path: Path,
    *,
    scenario_path: Path | None = None,
    project_dir: Path | None = None,
) -> Path:
    """Create and configure a benchmark project.  Returns the project directory."""
    profile = _load_profile(profile_path)

    include_testing = (
        _load_scenario_include_testing(scenario_path)
        if scenario_path is not None
        else True
    )
    datasets = ["testing"] if include_testing else []
    if scenario_path is not None:
        extra = _load_scenario_datasets(scenario_path)
        for ds in extra:
            if ds not in datasets:
                datasets.append(ds)

    if project_dir is None:
        _BENCH_PROJECTS_PARENT.mkdir(parents=True, exist_ok=True)
        project_dir = Path(
            tempfile.mkdtemp(prefix="lens_bench_", dir=_BENCH_PROJECTS_PARENT)
        )
    else:
        project_dir.mkdir(parents=True, exist_ok=True)

    project_dir = project_dir.resolve()
    orig_cwd = Path.cwd()
    os.chdir(project_dir)
    try:
        _git(project_dir, "init")
        _git(project_dir, "config", "user.email", "bench@lens.local")
        _git(project_dir, "config", "user.name", "Lens Bench")
        _git(project_dir, "config", "commit.gpgsign", "false")
        (project_dir / ".gitkeep").write_text("")
        _git(project_dir, "add", "-A")
        _git(project_dir, "commit", "-m", "root")

        init_project()
        _apply_bench_lens_config(project_dir, profile, datasets)
        use_narrative_for_project("default", project_dir, project_dir)

        Storage(project_dir).stage_all()
        _git(project_dir, "commit", "-m", "bench: init project")
    finally:
        os.chdir(orig_cwd)

    return project_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an empty Lens benchmark project with a real LLM.",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="LLM profile name (file in bench/llm_profiles/) or path to a TOML file",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario Markdown file (reads datasets from it)",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Directory to create the project in (default: bench/projects/lens_bench_*)",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="Also print a shell-safe 'export PROJECT=…' line to stderr (stdout is still the path)",
    )
    args = parser.parse_args()

    profile_path = Path(args.profile)
    if not profile_path.exists():
        profile_path = _REPO_ROOT / "bench" / "llm_profiles" / f"{args.profile}.toml"
    if not profile_path.exists():
        raise SystemExit(f"LLM profile not found: {args.profile}")

    scenario_path = Path(args.scenario) if args.scenario else None
    project_dir = Path(args.project_dir) if args.project_dir else None

    result = setup_project(
        profile_path,
        scenario_path=scenario_path,
        project_dir=project_dir,
    )
    print(result)
    if args.print_env:
        print(f"export PROJECT={shlex.quote(str(result))}", file=sys.stderr)


if __name__ == "__main__":
    main()
