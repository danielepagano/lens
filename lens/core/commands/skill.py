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
*(generated)*    This project's datasets, types, tags, modules and forks
Dataset          Its own conventions (``<dataset>/skill/skill.md``)
Project          House rules, last so they win the argument (``skill/skill.md``)
===============  ==========================================================

The generated half is the reason to emit rather than to write: it is the part
that cannot be known until someone asks, in a project nobody had in mind.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.module_requests import dataset_modules, dataset_own_modules
from lens.core.project import (
    get_active_narrative,
    get_selected_datasets,
    is_dataset_root,
    resolve_dataset_path,
)
from lens.core.release.version import installed_version
from lens.core.storage import Storage
from lens.core.storage_text import kb_headline

SKILL_RELPATH = Path(".claude") / "skills" / "lens" / "SKILL.md"
"""Where ``--install`` writes the pointer. Claude Code's convention; the body is
vendor-neutral markdown, only the frontmatter is host-specific."""

PROJECT_SKILL_RELPATH = Path("skill") / "skill.md"
"""The editable layer, alongside ``prompts/prompts.toml`` in spirit. Same path in
a project (house rules) and in a dataset (the conventions it ships)."""

_MAX_LISTED_TAGS = 60
"""Beyond this a tag list stops being a vocabulary and starts being a dump. A
reference dataset carries thousands of tags; the useful signal is which
*families* exist, which is reported separately and in full."""

_MAX_LISTED_IDS = 20
"""Same argument for id lists (forks, design modules)."""


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandEntry:
    """One command the running CLI accepts, as the CLI layer reports it.

    Deliberately not a click or Typer object: the emitted text is assembled in
    core, and core does not import the CLI. See
    :func:`lens.cli.command_inventory.collect_command_inventory`.
    """

    name: str
    summary: str
    panel: str = ""
    subcommands: tuple[str, ...] = ()


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


def collect_layers(
    project_root: Path | None,
    commands: Sequence[CommandEntry] = (),
) -> list[SkillLayer]:
    """Every layer that has text, in emission order.

    *project_root* may be ``None`` — ``lens skill`` run outside a project still
    emits the bundled invariants, which is the case where an agent needs them
    most.

    *commands* is the live CLI surface, supplied by the CLI layer because Typer
    lives there. Absent (a server, a test calling core directly), the command
    listing is omitted rather than guessed at.
    """
    layers: list[SkillLayer] = []
    builtin = _read(builtin_guidance_file())
    if builtin:
        layers.append(SkillLayer("builtin", builtin_guidance_file(), builtin))
    if project_root is None:
        if commands:
            layers.append(SkillLayer("commands", None, render_commands(commands)))
        return layers

    facts = describe_project(project_root)
    layers.append(SkillLayer("generated", None, render_facts(facts, commands)))

    for name in facts.datasets:
        dataset_path = resolve_dataset_path(project_root, name)
        if dataset_path is None:
            continue
        path = dataset_skill_file(dataset_path)
        text = _read(path)
        if text:
            layers.append(SkillLayer(f"dataset:{name}", path, text))

    # `skill/skill.md` sits at the same path in a dataset as in a project, which
    # is the point: a dataset checkout is a project an agent works in too, and
    # the conventions it ships are exactly the ones it is being edited against.
    own_path = project_skill_file(project_root)
    project_text = _read(own_path)
    if project_text:
        label = "dataset:self" if facts.is_dataset else "project"
        layers.append(SkillLayer(label, own_path, project_text))
    return layers


def render_guidance(
    project_root: Path | None,
    commands: Sequence[CommandEntry] = (),
) -> str:
    """The full text ``lens skill`` prints."""
    layers = collect_layers(project_root, commands)
    return "\n\n".join(layer.text for layer in layers) + "\n"


# ---------------------------------------------------------------------------
# The generated half
# ---------------------------------------------------------------------------


def _empty_str_list() -> list[str]:
    return []


def _empty_counts() -> list[tuple[str, int]]:
    return []


@dataclass(frozen=True)
class DatasetFact:
    name: str
    path: Path | None
    inside_repo: bool


@dataclass(frozen=True)
class ModuleFact:
    id: str
    dataset: str
    operators: tuple[str, ...]


@dataclass
class ProjectFacts:
    """The half of the guidance that is only knowable at emit time."""

    project_root: Path
    is_dataset: bool = False
    datasets: list[str] = field(default_factory=_empty_str_list)
    dataset_details: list[DatasetFact] = field(default_factory=list[DatasetFact])
    type_counts: list[tuple[str, int]] = field(default_factory=_empty_counts)
    object_count: int = 0
    project_owned: int = 0
    forks: list[str] = field(default_factory=_empty_str_list)
    """Project objects overriding a dataset copy: the copy-on-write forks."""
    overrides: list[str] = field(default_factory=_empty_str_list)
    """Dataset objects overriding an earlier dataset's copy of the same id."""
    plain_tags: list[str] = field(default_factory=_empty_str_list)
    tag_families: list[tuple[str, int]] = field(default_factory=_empty_counts)
    link_tag_count: int = 0
    design_modules: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    requestable_modules: list[ModuleFact] = field(default_factory=list[ModuleFact])
    narratives: list[str] = field(default_factory=_empty_str_list)
    active_narrative: str | None = None


_BLURB_CHARS = 160


def _blurb(headline: str) -> str:
    """One skimmable line out of an object's three-line self-description.

    The first of those lines is almost always a title, which a listing keyed by
    id has already said. What a reader is choosing between is the line after it,
    truncated — the whole object is one `lens kb get` away.
    """
    lines = [ln.strip() for ln in headline.split("\n") if ln.strip()]
    body = [ln for ln in lines if not ln.startswith("#")]
    text = (body or lines or [""])[0]
    if len(text) <= _BLURB_CHARS:
        return text
    cut = text[:_BLURB_CHARS].rsplit(" ", 1)[0]
    return f"{cut}…"


def describe_project(project_root: Path) -> ProjectFacts:
    """Read the live shape of the project: datasets, store, tags, modules."""
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

    store = KnowledgeStore.for_project(project_root)
    index = store.resolved_index()
    counts: dict[str, int] = {}
    for entry in index.values():
        counts[entry.type] = counts.get(entry.type, 0) + 1
        if entry.source.kind == "project":
            facts.project_owned += 1
        if entry.source.shadows:
            # Two different stories share one mechanism. A *project* object over
            # a dataset copy is a fork somebody made by editing; a *dataset*
            # object over an earlier dataset's is the stack working as
            # configured. Calling both "forks" would send someone hunting for an
            # edit nobody made.
            if entry.source.kind == "project":
                facts.forks.append(entry.id)
            else:
                loser = ", ".join(entry.source.shadows)
                facts.overrides.append(f"{entry.id} ({entry.source.dataset} over {loser})")
    facts.object_count = len(index)
    # A type whose only file is a `_template.md` still exists as far as ids,
    # tags and `design --module` are concerned, and it is exactly the type
    # someone is about to create the first object of.  `resolved_index` skips
    # templates, so ask the store which directories are there.
    for type_name in store.list_types():
        counts.setdefault(type_name, 0)
    facts.type_counts = sorted(counts.items())
    facts.forks.sort()
    facts.overrides.sort()

    type_names = set(counts)
    families: dict[str, int] = {}
    for tag in store.list_unique_tags():
        if ":" in tag:
            prefix = tag.split(":", 1)[0]
            families[prefix] = families.get(prefix, 0) + 1
            continue
        if "." in tag:
            # A dot-tag is a link to another object, not vocabulary — there is
            # one per relationship, so listing them says nothing about the
            # project and buries what does.
            facts.link_tag_count += 1
            continue
        if tag in type_names:
            # A type name matches as a tag (get_ids_with_tag); the type listing
            # above already reports it, so repeating it here reads as a second
            # vocabulary that does not exist.
            continue
        facts.plain_tags.append(tag)
    facts.tag_families = sorted(families.items())

    for cid in sorted(index):
        if not cid.startswith("design."):
            continue
        facts.design_modules.append((cid, _blurb(kb_headline(_read(index[cid].path)))))

    declared = (
        dataset_own_modules(project_root)
        if facts.is_dataset
        else dataset_modules(project_root)
    )
    for decl in declared:
        facts.requestable_modules.append(
            ModuleFact(id=decl.kb_id, dataset=decl.dataset, operators=decl.operators)
        )

    if not facts.is_dataset:
        narrative_dir = project_root / "narrative"
        if narrative_dir.exists():
            facts.narratives = sorted(
                d.name for d in narrative_dir.iterdir() if d.is_dir()
            )
        active = get_active_narrative(project_root)
        facts.active_narrative = active.narrative_root.name if active is not None else None
    return facts


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _capped(items: list[str], limit: int) -> str:
    if len(items) <= limit:
        return ", ".join(items)
    head = ", ".join(items[:limit])
    return f"{head}, … (+{len(items) - limit} more)"


def render_commands(commands: Sequence[CommandEntry]) -> str:
    """The ``### Commands available here`` listing, grouped as ``--help`` groups it.

    Read off the running CLI (see
    :func:`lens.cli.command_inventory.collect_command_inventory`), so it cannot
    drift and it already reflects this project's dataset gating: an operator or
    an extension command that is not listed here does not exist here.
    """
    out: list[str] = ["### Commands available here\n"]
    out.append(
        "Generated from the CLI that is installed, so it is what `lens --help` "
        "would say. Options live behind `lens <command> --help`; sub-commands are "
        "named without their summaries for the same reason."
    )
    by_panel: dict[str, list[CommandEntry]] = {}
    for entry in commands:
        by_panel.setdefault(entry.panel or "Commands", []).append(entry)
    for panel, entries in by_panel.items():
        out.append(f"\n**{panel}**\n")
        for entry in entries:
            line = f"- `lens {entry.name}` — {entry.summary}" if entry.summary else f"- `lens {entry.name}`"
            out.append(line)
            if entry.subcommands:
                subs = ", ".join(f"`{name}`" for name in entry.subcommands)
                out.append(f"  - {subs}")
    return "\n".join(out)


def render_facts(
    facts: ProjectFacts, commands: Sequence[CommandEntry] = ()
) -> str:
    """The ``## This project`` section: inventory, not advice."""
    out: list[str] = ["## This project\n"]
    version = installed_version()
    where = f"`{facts.project_root}`"
    if version:
        out.append(f"Reported by Lens {version} from {where}.")
    else:
        out.append(f"Reported from {where}.")

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
            "beats all of them."
        )
        for detail in facts.dataset_details:
            if detail.path is None:
                out.append(f"- `{detail.name}` — **unresolved** (nothing to read)")
            elif detail.inside_repo:
                out.append(f"- `{detail.name}` — `{detail.path}`")
            else:
                out.append(
                    f"- `{detail.name}` — `{detail.path}` (outside this repository; "
                    "`grep` here will not find it)"
                )
    elif not facts.is_dataset:
        out.append("\n### Active datasets\n\nNone. Every object resolves from this repository.")

    if commands:
        out.append("\n" + render_commands(commands))

    out.append("\n### Knowledge store\n")
    out.append(
        f"{facts.object_count} objects, {facts.project_owned} of them stored in this "
        "repository."
    )
    populated = [(n, c) for n, c in facts.type_counts if c]
    empty = [n for n, c in facts.type_counts if not c]
    if populated:
        types_text = ", ".join(f"{name} ({count})" for name, count in populated)
        out.append(f"\nTypes: {types_text}")
    if empty:
        out.append(
            "\nTypes with no objects yet (a directory and usually a template): "
            + ", ".join(empty)
        )
    if facts.forks:
        out.append(
            f"\nCopy-on-write forks ({len(facts.forks)}): "
            f"{_capped(facts.forks, _MAX_LISTED_IDS)}. This project holds its own copy; "
            "the dataset's version is no longer read, and edits to it will not arrive."
        )
    if facts.overrides:
        out.append(
            f"\nDataset-over-dataset overrides ({len(facts.overrides)}): "
            f"{_capped(facts.overrides, _MAX_LISTED_IDS)}."
        )

    out.append("\n### Tag vocabulary\n")
    if facts.plain_tags:
        out.append(
            f"{_plural(len(facts.plain_tags), 'plain tag')}: "
            f"{_capped(facts.plain_tags, _MAX_LISTED_TAGS)}"
        )
    else:
        out.append("No plain tags.")
    if facts.tag_families:
        families = ", ".join(f"`{name}:` ({count})" for name, count in facts.tag_families)
        out.append(f"\n`key:value` families: {families}")
    if facts.link_tag_count:
        out.append(
            f"\n{_plural(facts.link_tag_count, 'dot-tag')} link objects to each other; "
            "`lens kb refs <id>` reads them in both directions."
        )
    out.append(
        "\nType names also match as tags, so `lens kb with-tag <type>` finds every "
        "object of a type without a tag anyone has to maintain."
    )

    if facts.design_modules:
        out.append("\n### Design modules\n")
        out.append(
            "Run one with `lens design --module <key>`; read the whole module with "
            "`lens kb get design.<key>`."
        )
        for cid, headline in facts.design_modules[:_MAX_LISTED_IDS]:
            key = cid.split(".", 1)[1]
            out.append(f"- `{key}` — {headline}" if headline else f"- `{key}`")
        if len(facts.design_modules) > _MAX_LISTED_IDS:
            out.append(f"- … (+{len(facts.design_modules) - _MAX_LISTED_IDS} more)")

    if facts.requestable_modules:
        out.append("\n### Model-requestable modules\n")
        out.append(
            "Registered by a dataset (`[[dataset.modules]]`); the model pulls one "
            "into scope mid-reply. The catalog entry is the object's own first three "
            "lines, so an edit to the top of these files changes when they are asked "
            "for."
        )
        for module in facts.requestable_modules:
            ops = ", ".join(module.operators)
            out.append(f"- `{module.id}` — for {ops} (from `{module.dataset}`)")

    if facts.narratives:
        listed = ", ".join(
            f"`{name}`" + (" (active)" if name == facts.active_narrative else "")
            for name in facts.narratives
        )
        out.append(f"\n### Narratives\n\n{listed}")
    elif not facts.is_dataset:
        out.append("\n### Narratives\n\nNone yet (`lens use <slug>` creates one).")

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
