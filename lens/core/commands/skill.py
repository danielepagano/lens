"""``lens skill``: what the installed Lens tells an agent about this project.

The tool and a content project move on different clocks. A campaign repository
can sit untouched for months while Lens gains commands, changes conventions and
ships new dataset modules, so anything *descriptive* committed into that
repository is wrong the moment Lens moves — and wrong silently, because nothing
re-reads it.

So the thing committed to the project is not the guidance. It is a pointer
(:func:`pointer_text`, installed as ``.claude/skills/lens/SKILL.md``) that says
where guidance comes from, which stays true across every Lens version; the
guidance itself (:func:`render_guidance`) is produced by the Lens that is
actually installed, at the moment it is asked. Knowing to ask the tool what it
can currently do is the durable skill. The answer is not.

Layering
--------
Composed, not shadowed — each layer owns a different half, so a later layer
appends rather than replacing:

===============  ==========================================================
Bundled          Invariants true in every Lens project (``lens/skill/``)
*(generated)*    Where the cursor is; which datasets merge in, from where
Dataset          Its gist (``<dataset>/skill/skill.md``, up to ``<!-- more -->``)
Project          House rules, last so they win the argument (``skill/skill.md``)
===============  ==========================================================

What it leaves out
------------------
The output is read once, before work starts, usually through a tool whose
output is truncated. So it holds what fails silently and nothing a command
already answers: the command surface is ``lens --help``, types and counts are
``lens stats``, tags are ``lens kb list-tags``, modules are ``lens kb list
--type design``. How to drive one command belongs in that command's help.

A dataset's full conventions are a *topic*: ``lens skill <dataset>`` prints the
whole file. They matter when writing that dataset's kind of content, and are
paid for only then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.operator_detect import detect_open_session_operator
from lens.core.project import (
    get_active_narrative,
    get_selected_datasets,
    is_dataset_root,
    resolve_dataset_path,
)
from lens.core.release.version import installed_version
from lens.core.storage import Storage

SKILL_RELPATH = Path(".claude") / "skills" / "lens" / "SKILL.md"
"""Where ``--install`` writes the pointer. Claude Code's convention; the body is
vendor-neutral markdown, only the frontmatter is host-specific."""

PROJECT_SKILL_RELPATH = Path("skill") / "skill.md"
"""The editable layer, alongside ``prompts/prompts.toml`` in spirit. Same path in
a project (house rules) and in a dataset (the conventions it ships)."""

GIST_BREAK = "<!-- more -->"
"""Ends a dataset's gist. Everything above it is emitted by ``lens skill``;
the whole file is ``lens skill <dataset>``. A file without it is emitted whole,
so a dataset that never adopted the split loses nothing."""


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillLayer:
    """One contribution to the emitted guidance, and where it came from."""

    source: str
    """``builtin`` | ``generated`` | ``dataset:<name>`` | ``project``."""
    path: Path | None
    """The file it was read from; ``None`` for the generated section."""
    text: str


def skill_root() -> Path:
    return Path(__file__).parent.parent.parent / "skill"


def builtin_guidance_file() -> Path:
    return skill_root() / "guidance.md"


def builtin_pointer_file() -> Path:
    return skill_root() / "pointer.md"


def dataset_skill_file(dataset_path: Path) -> Path:
    return dataset_path / "skill" / "skill.md"


def project_skill_file(project_root: Path) -> Path:
    return project_root / PROJECT_SKILL_RELPATH


def installed_skill_path(project_root: Path) -> Path:
    return project_root / SKILL_RELPATH


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _gist(name: str, text: str) -> str:
    """The part of a dataset's file ``lens skill`` emits, plus where the rest is."""
    head, sep, _rest = text.partition(GIST_BREAK)
    if not sep:
        return text
    return f"{head.rstrip()}\n\nFull conventions: `lens skill {name}`."


def _whole(text: str) -> str:
    head, sep, rest = text.partition(GIST_BREAK)
    return f"{head.rstrip()}\n\n{rest.lstrip()}" if sep else text


def _dataset_skill_texts(project_root: Path) -> list[tuple[str, Path, str]]:
    """``(name, path, text)`` for each active dataset that ships a skill file."""
    found: list[tuple[str, Path, str]] = []
    if is_dataset_root(project_root):
        return found
    for name in get_selected_datasets(project_root):
        dataset_path = resolve_dataset_path(project_root, name)
        if dataset_path is None:
            continue
        path = dataset_skill_file(dataset_path)
        text = _read(path)
        if text:
            found.append((name, path, text))
    return found


def collect_layers(project_root: Path | None) -> list[SkillLayer]:
    """Every layer that has text, in emission order.

    *project_root* may be ``None`` — ``lens skill`` run outside a project still
    emits the bundled invariants, which is the case where an agent needs them
    most.
    """
    layers: list[SkillLayer] = []
    builtin = _read(builtin_guidance_file())
    if builtin:
        layers.append(SkillLayer("builtin", builtin_guidance_file(), builtin))
    if project_root is None:
        return layers

    facts = describe_project(project_root)
    layers.append(SkillLayer("generated", None, render_facts(facts)))

    for name, path, text in _dataset_skill_texts(project_root):
        layers.append(SkillLayer(f"dataset:{name}", path, _gist(name, text)))

    # `skill/skill.md` sits at the same path in a dataset as in a project, which
    # is the point: a dataset checkout is a project an agent works in too, and
    # the conventions it ships are exactly the ones it is being edited against —
    # so there it is emitted whole, not as a gist.
    own_path = project_skill_file(project_root)
    project_text = _read(own_path)
    if project_text:
        label = "dataset:self" if facts.is_dataset else "project"
        layers.append(SkillLayer(label, own_path, _whole(project_text)))
    return layers


def render_guidance(project_root: Path | None) -> str:
    """The full text ``lens skill`` prints."""
    layers = collect_layers(project_root)
    return "\n\n".join(layer.text for layer in layers) + "\n"


def topic_names(project_root: Path) -> list[str]:
    """What ``lens skill <topic>`` accepts here: each active dataset with a skill file."""
    return [name for name, _path, _text in _dataset_skill_texts(project_root)]


def render_topic(project_root: Path, name: str) -> str:
    """A dataset's full conventions, gist included."""
    for dataset, _path, text in _dataset_skill_texts(project_root):
        if dataset == name:
            return _whole(text) + "\n"
    available = ", ".join(topic_names(project_root)) or "none"
    raise LensException(f"no skill topic '{name}' in this project (available: {available})")


# ---------------------------------------------------------------------------
# The generated half
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetFact:
    name: str
    path: Path | None
    inside_repo: bool


@dataclass
class ProjectFacts:
    """The half of the guidance that is only knowable at emit time.

    Only what orients: where the merged store's other halves live, and where
    in the narrative work would land. Inventories are left to the commands that
    own them (see the module docstring).
    """

    project_root: Path
    is_dataset: bool = False
    datasets: list[str] = field(default_factory=list[str])
    dataset_details: list[DatasetFact] = field(default_factory=list[DatasetFact])
    active_narrative: str | None = None
    cursor: str | None = None
    open_session: str | None = None
    """The session operator still open at the cursor, if any."""


def describe_project(project_root: Path) -> ProjectFacts:
    """Which datasets this project merges, and whether each lives in the repo."""
    facts = ProjectFacts(project_root=project_root)
    facts.is_dataset = is_dataset_root(project_root)
    facts.datasets = [] if facts.is_dataset else get_selected_datasets(project_root)
    for name in facts.datasets:
        path = resolve_dataset_path(project_root, name)
        inside = False
        if path is not None:
            try:
                path.resolve().relative_to(project_root.resolve())
                inside = True
            except ValueError:
                inside = False
        facts.dataset_details.append(DatasetFact(name=name, path=path, inside_repo=inside))
    if not facts.is_dataset:
        # The cursor is derived from the tail annotations on disk, so this is
        # the same answer every process gives; an open session's pending KB
        # proposals do not move it.
        narrative = get_active_narrative(project_root)
        if narrative is not None:
            cursor = narrative.find_cursor()
            facts.active_narrative = narrative.narrative_root.name
            facts.cursor = str(cursor.to_address())
            facts.open_session = detect_open_session_operator(cursor)
    return facts


def render_facts(facts: ProjectFacts) -> str:
    """The ``## This project`` section: where things are, not what they hold."""
    out: list[str] = ["## This project\n"]
    version = installed_version()
    where = f"`{facts.project_root}`"
    if version:
        out.append(f"Reported by Lens {version} from {where}.")
    else:
        out.append(f"Reported from {where}.")

    if facts.cursor is not None:
        session = (
            f", inside an open `{facts.open_session}` session (opened on an ancestor "
            f"node; the `[{facts.open_session}]` blocks in this file are its turns, "
            f"and `lens {facts.open_session} --end` closes it)"
            if facts.open_session
            else ""
        )
        out.append(
            f"\nActive narrative `{facts.active_narrative}`; the cursor is "
            f"`{facts.cursor}`{session}. Operators, `lens spine` and `lens explain` "
            "work there unless given an address; `lens stats` shows the pins in "
            "effect."
        )
    elif not facts.is_dataset:
        out.append("\nNo active narrative (`lens use <slug>` selects or creates one).")

    if facts.is_dataset:
        out.append(
            "\nThis checkout is a **dataset**, not a content project: it ships "
            "knowledge for other projects to merge in. Objects here are read by "
            "every project that selects this dataset."
        )

    if facts.dataset_details:
        out.append("\n### Active datasets\n")
        out.append(
            "Later entries shadow earlier ones; this project's own `knowledge/` "
            "beats all of them. Those outside this repository are invisible to "
            "`grep` here."
        )
        for detail in facts.dataset_details:
            if detail.path is None:
                out.append(f"- `{detail.name}` — **unresolved** (nothing to read)")
            elif detail.inside_repo:
                out.append(f"- `{detail.name}` — `{detail.path}` (inside this repository)")
            else:
                out.append(f"- `{detail.name}` — `{detail.path}`")
    elif not facts.is_dataset:
        out.append("\n### Active datasets\n\nNone. Every object resolves from this repository.")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# The committed pointer
# ---------------------------------------------------------------------------


def pointer_text() -> str:
    """The ``SKILL.md`` this Lens would install.

    Deliberately free of project facts. The pointer is compared byte for byte by
    :func:`check_skill`, so drift has to mean "Lens changed what it says", not
    "somebody added a knowledge object".
    """
    text = _read(builtin_pointer_file())
    if not text:
        raise LensException("bundled skill pointer is missing or unreadable")
    return text + "\n"


@dataclass(frozen=True)
class SkillCheck:
    """Result of comparing the installed pointer with what this Lens writes."""

    path: Path
    installed: bool
    current: bool

    @property
    def ok(self) -> bool:
        return self.installed and self.current

    def message(self) -> str:
        if not self.installed:
            return f"not installed ({self.path}); run 'lens skill --install'"
        if not self.current:
            return f"stale ({self.path}); run 'lens skill --install'"
        return f"up to date ({self.path})"


def check_skill(project_root: Path) -> SkillCheck:
    path = installed_skill_path(project_root)
    if not path.exists():
        return SkillCheck(path=path, installed=False, current=False)
    return SkillCheck(path=path, installed=True, current=_read(path) == pointer_text().strip())


def install_skill(
    project_root: Path,
    *,
    storage: Storage | None = None,
    git_root: Path | None = None,
) -> Path:
    """Write the pointer into the project, returning its path.

    Uses a direct-edit storage by default: the pointer is a generated file the
    user is the reviewer of, and staging somebody else's in-flight operator work
    to write it would be a surprise.
    """
    path = installed_skill_path(project_root)
    text = pointer_text()
    if storage is None:
        storage = Storage.for_direct_edit(git_root or project_root)
    storage.write_file(path, text)
    return path
