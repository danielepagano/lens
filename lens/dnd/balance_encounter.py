import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lens.core.command_tools import CommandToolDef, register_command_tool
from lens.core.knowledge import KnowledgeStore

CR_TAG_ORDER: list[tuple[float, str]] = [
    (0, "cr:0"),
    (0.125, "cr:1-8"),
    (0.25, "cr:1-4"),
    (0.5, "cr:1-2"),
    (1.0, "cr:1"),
    (2.0, "cr:2"),
    (3.0, "cr:3"),
    (4.0, "cr:4"),
    (5.0, "cr:5"),
    (6.0, "cr:6"),
    (7.0, "cr:7"),
    (8.0, "cr:8"),
    (9.0, "cr:9"),
    (10.0, "cr:10"),
    (11.0, "cr:11"),
    (12.0, "cr:12"),
    (13.0, "cr:13"),
    (14.0, "cr:14"),
    (15.0, "cr:15"),
    (16.0, "cr:16"),
    (17.0, "cr:17"),
    (18.0, "cr:18"),
    (19.0, "cr:19"),
    (20.0, "cr:20"),
    (21.0, "cr:21"),
    (22.0, "cr:22"),
    (23.0, "cr:23"),
    (24.0, "cr:24"),
    (25.0, "cr:25"),
    (26.0, "cr:26"),
    (27.0, "cr:27"),
    (28.0, "cr:28"),
    (29.0, "cr:29"),
    (30.0, "cr:30"),
]

CR_XP: dict[float, int] = {
    0: 10,
    0.125: 25,
    0.25: 50,
    0.5: 100,
    1.0: 200,
    2.0: 450,
    3.0: 700,
    4.0: 1100,
    5.0: 1800,
    6.0: 2300,
    7.0: 2900,
    8.0: 3900,
    9.0: 5000,
    10.0: 5900,
    11.0: 7200,
    12.0: 8400,
    13.0: 10000,
    14.0: 11500,
    15.0: 13000,
    16.0: 15000,
    17.0: 18000,
    18.0: 20000,
    19.0: 22000,
    20.0: 25000,
    21.0: 33000,
    22.0: 41000,
    23.0: 50000,
    24.0: 62000,
    25.0: 75000,
    26.0: 90000,
    27.0: 105000,
    28.0: 120000,
    29.0: 135000,
    30.0: 155000,
}

XP_BUDGET: dict[int, dict[str, int]] = {
    1: {"low": 50, "moderate": 75, "high": 100},
    2: {"low": 100, "moderate": 150, "high": 200},
    3: {"low": 150, "moderate": 225, "high": 400},
    4: {"low": 250, "moderate": 375, "high": 500},
    5: {"low": 500, "moderate": 750, "high": 1100},
    6: {"low": 600, "moderate": 1000, "high": 1400},
    7: {"low": 750, "moderate": 1300, "high": 1700},
    8: {"low": 1000, "moderate": 1700, "high": 2100},
    9: {"low": 1300, "moderate": 2000, "high": 2600},
    10: {"low": 1600, "moderate": 2300, "high": 3100},
    11: {"low": 1900, "moderate": 2900, "high": 4100},
    12: {"low": 2200, "moderate": 3700, "high": 4700},
    13: {"low": 2600, "moderate": 4200, "high": 5400},
    14: {"low": 2900, "moderate": 4900, "high": 6200},
    15: {"low": 3300, "moderate": 5400, "high": 7800},
    16: {"low": 3800, "moderate": 6100, "high": 9800},
    17: {"low": 4500, "moderate": 7200, "high": 11700},
    18: {"low": 5000, "moderate": 8700, "high": 14200},
    19: {"low": 5500, "moderate": 10700, "high": 17200},
    20: {"low": 6400, "moderate": 13200, "high": 22000},
}


def cr_tag_to_float(tag: str) -> float | None:
    if not tag.startswith("cr:"):
        return None
    val = tag[3:]
    if "-" in val:
        num, den = val.split("-", 1)
        try:
            return float(num) / float(den)
        except ValueError:
            return None
    try:
        return float(val)
    except ValueError:
        return None


def cr_str_to_float(cr_str: str) -> float | None:
    if "/" in cr_str:
        num, den = cr_str.split("/", 1)
        try:
            return float(num) / float(den)
        except ValueError:
            return None
    try:
        return float(cr_str)
    except ValueError:
        return None


def _stat_xp(stat_id: str, kb: KnowledgeStore) -> int:
    for tag in kb.get_tags(stat_id):
        if tag.startswith("cr:"):
            cr_float = cr_tag_to_float(tag)
            if cr_float is not None and cr_float in CR_XP:
                return CR_XP[cr_float]
    return 0


def _conflicting_cr_tags(stat_id: str, kb: KnowledgeStore) -> list[str]:
    """Every ``cr:`` tag on an object, when it carries more than one.

    ``kb extract`` applies tags additively, so re-importing a block whose CR was
    corrected leaves the old tag in place and the object ends up in two buckets.
    :func:`_stat_xp` then takes whichever comes first and prices the creature
    silently wrong — a Warrior Infantry corrected from CR 1/2 to CR 1/8 kept both
    and cost four times what it should.
    """
    cr_tags = [t for t in kb.get_tags(stat_id) if t.startswith("cr:")]
    return cr_tags if len(cr_tags) > 1 else []


def parse_cr_token(token: str) -> float | None:
    """Read a token as a challenge rating, or return ``None`` if it names an object.

    A roster slot may be a stat id (``stat.zombie``) or a bare challenge rating,
    which is how a creature that does not exist yet gets priced — the usual case
    during ``design --module stat``, where the block being built has no id until
    the session ends.  Accepts ``cr:3`` and ``cr:1-2`` (the dataset's tag forms),
    ``3``, ``1/2``, and ``0.5``.
    """
    raw = token.strip().lower()
    if not raw:
        return None
    if raw.startswith("cr:"):
        return cr_tag_to_float(raw)
    if "." in raw and not raw.replace(".", "", 1).isdigit():
        return None  # an id like `stat.zombie`
    return cr_str_to_float(raw)


def _cr_display(cr: float) -> str:
    for value, tag in CR_TAG_ORDER:
        if value == cr:
            frac = tag[3:]
            return frac.replace("-", "/") if "-" in frac else frac
    return f"{cr:g}"


def _token_label(token: str) -> str:
    """How a roster slot is named back to the caller."""
    cr = parse_cr_token(token)
    return f"CR {_cr_display(cr)} creature" if cr is not None else token.strip()


def _token_xp(token: str, kb: KnowledgeStore) -> int:
    """XP for a roster slot, whether it names a stat block or a challenge rating."""
    cr = parse_cr_token(token)
    if cr is not None:
        return CR_XP.get(cr, 0)
    return _stat_xp(token, kb)


@dataclass
class RequiredEntry:
    id: str
    count: int


@dataclass
class CandidateSolution:
    entries: list[RequiredEntry]
    total_xp: int
    remark: str | None = None

    def serialize(self, kb: KnowledgeStore) -> str:
        lines: list[str] = []
        for e in self.entries:
            label = _token_label(e.id)
            if parse_cr_token(e.id) is not None:
                lines.append(f"[{e.count}] {label}")
                continue
            tag_str = " ".join(sorted(kb.get_tags(e.id)))
            lines.append(f"[{e.count}] {label} {tag_str}")
        return "\n".join(lines)


def _reduce_candidates(
    required: list[RequiredEntry], budget: int, kb: KnowledgeStore
) -> list[CandidateSolution]:
    solutions: list[CandidateSolution] = []

    total_xp = sum(e.count * _token_xp(e.id, kb) for e in required)
    original_solution = CandidateSolution(entries=list(required), total_xp=total_xp)

    reduction_possible = False
    best_in_budget_solution: CandidateSolution | None = None

    for i, e in enumerate(required):
        if e.count > 1:
            xp = _token_xp(e.id, kb)
            if xp == 0:
                continue
            sum_other = total_xp - (e.count * xp)
            reduced = math.floor((budget - sum_other) / xp)
            if reduced >= 1:
                reduction_possible = True
                new_entries = list(required)
                new_entries[i] = RequiredEntry(id=e.id, count=reduced)
                new_total_xp = sum_other + (reduced * xp)
                solution = CandidateSolution(entries=new_entries, total_xp=new_total_xp)
                solutions.append(solution)
                if new_total_xp <= budget:
                    if (
                        best_in_budget_solution is None
                        or abs(new_total_xp - budget)
                        < abs(best_in_budget_solution.total_xp - budget)
                    ):
                        best_in_budget_solution = solution

    if reduction_possible:
        original_solution.remark = (
            "Over requested XP budget; do not use without narrative safeguards"
        )
        if best_in_budget_solution:
            solutions = [
                best_in_budget_solution,
            ] + [s for s in solutions if s != best_in_budget_solution]
        solutions.append(original_solution)
    else:
        original_solution.remark = (
            "required monster(s) alone exceed budget — no reduction possible"
        )
        solutions.append(original_solution)

    return solutions


def _weighted_sample(candidates: list[str]) -> list[str]:
    if not candidates:
        return []

    weights = [1.0 / (i + 1) for i in range(len(candidates))]

    selected: list[str] = []
    candidates_copy = list(candidates)
    weights_copy = list(weights)

    num_to_select = min(2, len(candidates))
    for _ in range(num_to_select):
        if not candidates_copy:
            break
        chosen = random.choices(candidates_copy, weights=weights_copy, k=1)[0]
        selected.append(chosen)

        idx = candidates_copy.index(chosen)
        candidates_copy.pop(idx)
        weights_copy.pop(idx)

    return selected


def _fill_candidates(
    required: list[RequiredEntry], remaining: int, optional: list[str], kb: KnowledgeStore
) -> list[CandidateSolution]:
    solutions: list[CandidateSolution] = []

    if not optional:
        if not required:
            return solutions

        for e in required:
            xp = _token_xp(e.id, kb)
            if xp == 0:
                continue
            extra = math.floor(remaining / xp)
            if extra >= 1:
                new_entries = list(required)
                idx = new_entries.index(e)
                new_entries[idx] = RequiredEntry(id=e.id, count=e.count + extra)
                total_xp = sum(x.count * _token_xp(x.id, kb) for x in new_entries)
                solutions.append(CandidateSolution(entries=new_entries, total_xp=total_xp))
        return solutions

    for _ in range(3):
        types_to_add = _weighted_sample(optional)
        rem = remaining
        fill_entries: list[RequiredEntry] = []
        for t in types_to_add:
            xp = _token_xp(t, kb)
            if xp == 0:
                continue
            count = math.floor(rem / xp)
            if count >= 1:
                rem -= count * xp
                fill_entries.append(RequiredEntry(id=t, count=count))

            min_xp = min(
                (_token_xp(opt, kb) for opt in optional if _token_xp(opt, kb) > 0),
                default=0,
            )
            if min_xp > 0 and rem < min_xp:
                break

        if fill_entries:
            combined = list(required) + fill_entries
            total_xp = sum(e.count * _token_xp(e.id, kb) for e in combined)
            solutions.append(CandidateSolution(entries=combined, total_xp=total_xp))

    if remaining > 0 and optional:
        rem = remaining
        fill_entries = []
        for opt in optional:
            xp = _token_xp(opt, kb)
            if xp == 0:
                continue
            count = math.floor(rem / xp)
            if count >= 1:
                rem -= count * xp
                fill_entries.append(RequiredEntry(id=opt, count=count))
            if rem <= 0:
                break
        if fill_entries:
            combined = list(required) + fill_entries
            total_xp = sum(e.count * _token_xp(e.id, kb) for e in combined)
            solutions.append(CandidateSolution(entries=combined, total_xp=total_xp))

    return solutions


def _rank_solutions(solutions: list[CandidateSolution], budget: int) -> list[CandidateSolution]:
    def sort_key(s: CandidateSolution) -> tuple[int, int]:
        dist = abs(s.total_xp - budget)
        under = 0 if s.total_xp <= budget else 1
        return (dist, under)

    solutions.sort(key=sort_key)

    deduped: list[CandidateSolution] = []
    seen: set[frozenset[tuple[str, int]]] = set()
    for s in solutions:
        key = frozenset((e.id, e.count) for e in s.entries)
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return deduped[:3]


def _validate_id_count_entries(raw: list[Any], *, label: str) -> str | None:
    for item in raw:
        if not isinstance(item, dict):
            return (
                f"Error: each '{label}' entry must be an object with 'id' and 'count' "
                '(shape: {"id": "stat.…", "count": N}).'
            )
        entry = cast(dict[str, Any], item)
        if "id" not in entry or "count" not in entry:
            return f"Error: each '{label}' entry must include both 'id' and 'count'."
        sid = str(entry["id"]).strip()
        if not sid:
            return f"Error: each '{label}' entry must have a non-empty 'id'."
        try:
            c = int(entry["count"])
        except (TypeError, ValueError):
            return f"Error: each '{label}' entry must have a numeric 'count' of at least 1."
        if c < 1:
            return f"Error: each '{label}' entry must have a numeric 'count' of at least 1."
    return None


def _entries_from_raw(raw: list[Any]) -> list[RequiredEntry]:
    out: list[RequiredEntry] = []
    for item in raw:
        entry = cast(dict[str, Any], item)
        out.append(
            RequiredEntry(id=str(entry["id"]).strip(), count=int(entry["count"]))
        )
    return out


def compute_encounters(
    required_raw: list[Any],
    optional: list[str],
    difficulty: str,
    pcs: list[int],
    allies_raw: list[Any],
    kb: KnowledgeStore,
) -> str:
    if not required_raw and not optional:
        return "Error: Both required and optional lists are empty. Nothing to build an encounter from."

    for label, arr in (("required", required_raw), ("allies", allies_raw)):
        err = _validate_id_count_entries(arr, label=label)
        if err is not None:
            return err

    budget = 0
    for pc_lvl in pcs:
        if pc_lvl in XP_BUDGET and difficulty in XP_BUDGET[pc_lvl]:
            budget += XP_BUDGET[pc_lvl][difficulty]

    ally_entries = _entries_from_raw(allies_raw)
    ally_xp = sum(e.count * _token_xp(e.id, kb) for e in ally_entries)

    adjusted_budget = budget + ally_xp

    if budget == 0:
        return (
            f"Error: Invalid difficulty '{difficulty}' "
            "(should be low, moderate, or high) or invalid PC levels."
        )

    required = _entries_from_raw(required_raw)

    committed_xp = sum(e.count * _token_xp(e.id, kb) for e in required)

    solutions: list[CandidateSolution] = []

    if committed_xp > adjusted_budget:
        remaining = 0
        solutions = _reduce_candidates(required, adjusted_budget, kb)
    else:
        remaining = adjusted_budget - committed_xp
        solutions = _fill_candidates(required, remaining, optional, kb)
        if not solutions:
            if required:
                solutions = [CandidateSolution(entries=required, total_xp=committed_xp)]
            elif optional:
                cheapest = min(optional, key=lambda x: _token_xp(x, kb))
                xp = _token_xp(cheapest, kb)
                if xp > 0:
                    solutions = [
                        CandidateSolution(
                            entries=[RequiredEntry(id=cheapest, count=1)],
                            total_xp=xp,
                            remark="budget too low for any candidate; emitting cheapest",
                        )
                    ]

    if not solutions:
        return "Error: Could not generate any encounter proposals."

    all_tokens = [e.id for e in required] + list(optional) + [e.id for e in ally_entries]
    unpriced = [tok for tok in all_tokens if _token_xp(tok, kb) == 0]
    ambiguous = [
        (tok, tags)
        for tok in dict.fromkeys(all_tokens)
        if parse_cr_token(tok) is None
        for tags in [_conflicting_cr_tags(tok, kb)]
        if tags
    ]

    ranked = _rank_solutions(solutions, adjusted_budget)

    party_size = len(pcs) + sum(e.count for e in ally_entries)

    output: list[str] = [
        "Encounter Proposals",
        "Line format: [creature qty] stat.id ..tags.. (or 'CR N creature' for a rating you passed)",
        "",
    ]
    if ambiguous:
        output.insert(
            1,
            "Warning: "
            + "; ".join(f"{tok} carries {', '.join(tags)}" for tok, tags in ambiguous)
            + " — more than one `cr:` tag, so it was priced as the first. Tags are "
            "additive on import, so a corrected CR leaves the old one behind; remove it "
            "with `lens kb tag <id> --remove <tag>`.",
        )
    if unpriced:
        output.insert(
            1,
            "Warning: no XP for "
            + ", ".join(dict.fromkeys(unpriced))
            + " — an id that does not exist, a stat block with no `cr:` tag, or a "
            "rating outside CR 0-30. Each counted as 0, so the budget below is wrong "
            "by whatever they are worth.",
        )

    options = ["A", "B", "C"]
    for i, sol in enumerate(ranked):
        remarks: list[str] = []
        if sol.remark:
            remarks.append(sol.remark)

        total_monsters = sum(e.count for e in sol.entries)
        if party_size > 0 and (total_monsters / party_size) > 4:
            remarks.append(
                "You have more than the recommended number of enemies per party member "
                "(PCs + allies); this encounter may be harder than CR math suggests, "
                "consider lowering enemy count"
            )

        if (
            not optional
            and remaining > 0
            and committed_xp <= adjusted_budget
            and not [
                e
                for e in required
                if _token_xp(e.id, kb) > 0
                and math.floor(remaining / _token_xp(e.id, kb)) >= 1
            ]
        ):
            remarks.append(
                "no optional candidates provided; consider using kb with-tag to "
                "discover candidates first"
            )

        header = f"> Option {options[i]}"
        if remarks:
            header += f" ({'; '.join(remarks)})"

        output.append(header)
        output.append(sol.serialize(kb))
        output.append("")

    return "\n".join(output)


BALANCE_ENCOUNTER_DESCRIPTION = """Use balance_encounter to generate up to three balanced encounter proposals from a ranked candidate list. Pass PC levels explicitly from context (level:N tags on pinned pc.* objects).

Every roster slot — in `required`, `optional`, and `allies` alike — is either a **stat block id** (`stat.zombie`) or a **bare challenge rating** (`3`, `1/2`, `cr:5`). The rating form prices a creature that does not exist yet, which is how you weigh a block you are still designing, or ask a shape question: `required: [{"id": "3", "count": 1}]` with `optional: ["stat.zombie", "stat.skeleton"]` asks "one CR 3 enemy plus zombies and skeletons — how many fit?". Proposals name a rating slot back as `CR 3 creature` instead of an id.

Call it as often as you need; iterating over mixes is what it is for. If NPCs fight on the party's side, pass `allies` in the same shape, and their XP is added to the budget so enemies scale to PCs **and** those allies. The tool uses D&D 2024 XP budget math (no monster-count multiplier)."""

BALANCE_ENCOUNTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "required": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Stat block id ('stat.vampire') **or** a bare challenge rating ('3', '1/2', 'cr:5') for a creature that does not exist yet"},
                    "count": {"type": "integer", "minimum": 1},
                },
                "required": ["id", "count"],
            },
            "description": (
                "Enemies that must appear, with counts. Same entry shape as `allies`. Each "
                "entry is a stat id or a challenge rating, so a block you are still designing "
                "can be weighed as its rating. Can be empty if you have no fixed requirements."
            ),
        },
        "optional": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Ranked list of stat block ids, or bare challenge ratings, to fill out the "
                "encounter (most preferred first). The tool picks counts."
            ),
        },
        "difficulty": {
            "type": "string",
            "enum": ["low", "moderate", "high"],
            "description": "Target encounter difficulty.",
        },
        "pcs": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1, "maximum": 20},
            "description": "PC levels, one integer per PC. Example: [5, 5, 5, 5].",
        },
        "allies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "For an NPC fighting on the party's side: Stat block id ('stat.vampire') **or** a bare challenge rating ('3', '1/2', 'cr:5') for a creature that does not exist yet",
                    },
                    "count": {"type": "integer", "minimum": 1},
                },
                "required": ["id", "count"],
            },
            "description": (
                "Allied combatants: same entry shape as `required`. Build XP comes from the "
                "stat's `cr:` tags, or from the rating you passed. Use [] when no allies fight."
            ),
        },
    },
    "required": ["required", "optional", "difficulty", "pcs"],
}


async def _balance_encounter_command_tool(args: dict[str, Any], project_root: Path) -> str:
    required = args.get("required", [])
    optional = args.get("optional", [])
    difficulty = args.get("difficulty", "moderate")
    pcs = args.get("pcs", [])
    allies_raw = args.get("allies", [])
    kb = KnowledgeStore.for_project(project_root)
    return compute_encounters(required, optional, difficulty, pcs, allies_raw, kb)


def register_tools(*, dataset_path: Path, dataset_name: str, project_root: Path | None) -> None:
    register_command_tool(
        "balance_encounter",
        CommandToolDef(
            description=BALANCE_ENCOUNTER_DESCRIPTION,
            parameters=BALANCE_ENCOUNTER_SCHEMA,
            limited_to_datasets=[dataset_name],
        ),
        _balance_encounter_command_tool,
    )
