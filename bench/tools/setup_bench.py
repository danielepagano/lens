#!/usr/bin/env python3
"""Create a Lens benchmark project connected to a real LLM.

Usage::

    # From the repo root:
    python bench/tools/setup_bench.py --profile local_thinking
    python bench/tools/setup_bench.py --profile grok --scenario bench/scenarios/write_coherence.md
    python bench/tools/setup_bench.py --profile local_thinking --project-dir /tmp/mybench

The script creates a Lens project (git repo, lens.toml, narrative, KB, opening
passage) using the same ``setup_test_project()`` helper that powers the test
suite, then patches ``lens.toml`` to use a real LLM instead of the fake one.

The project directory is printed to stdout so a calling agent or script can
capture it.
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
import tomllib
from pathlib import Path

import tomli_w

# Ensure the repo root is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from lens.testing.fake_llm import FakeLLMServer  # noqa: E402
from lens.testing.project import setup_test_project  # noqa: E402


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

    Scenarios contain a fenced config block::

        ~~~config
        datasets: rpg, dnd
        ~~~

    An empty ``datasets:`` line (or no config block) means no extra datasets.
    """
    import re

    text = scenario_path.read_text(encoding="utf-8")
    m = re.search(r"~~~config\n(.*?)~~~", text, re.DOTALL)
    if not m:
        return []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("datasets:"):
            raw = line[len("datasets:") :].strip()
            if not raw:
                return []
            return [d.strip() for d in raw.split(",") if d.strip()]
    return []


def _patch_llm_config(project_dir: Path, profile: dict[str, object]) -> None:
    """Replace the mock [[llm]] entry in lens.toml with the real LLM config.

    Keeps the mock entry as a fallback (useful for setup_test_project's opening
    write which already ran against the mock).  The real LLM becomes the default
    (first entry) so operators use it by default.
    """
    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)

    real_entry: dict[str, object] = {"id": "bench"}
    for key in ("base_url", "model", "api_key_env", "temperature", "timeout_seconds"):
        if key in profile:
            real_entry[key] = profile[key]

    existing = cfg.get("llm", [])
    if not isinstance(existing, list):
        existing = []

    # Real LLM first (default), then any existing entries (mock).
    cfg["llm"] = [real_entry, *existing]

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

    # Determine datasets from scenario (if given).
    datasets = ["testing"]
    if scenario_path is not None:
        extra = _load_scenario_datasets(scenario_path)
        for ds in extra:
            if ds not in datasets:
                datasets.append(ds)

    # Create project directory.
    if project_dir is None:
        project_dir = Path(tempfile.mkdtemp(prefix="lens_bench_"))
    else:
        project_dir.mkdir(parents=True, exist_ok=True)

    # The opening write needs a working LLM.  Use the fake one for that step,
    # then patch in the real one afterward.
    server = FakeLLMServer()
    server.start()
    try:
        setup_test_project(project_dir, server.base_url, datasets=datasets)
    finally:
        server.stop()

    # Patch lens.toml with the real LLM config.
    _patch_llm_config(project_dir, profile)

    return project_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Lens benchmark project with a real LLM.",
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
        help="Directory to create the project in (default: temp dir)",
    )
    args = parser.parse_args()

    # Resolve profile path.
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


if __name__ == "__main__":
    main()
