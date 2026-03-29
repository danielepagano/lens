import math
import random
from dataclasses import dataclass
from typing import Any

from pathlib import Path

from lens.core.command_tools import CommandToolDef, register_command_tool
from lens.core.knowledge import KnowledgeStore
from lens.core.prompts import PromptStore, tool_prompt_key

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


def _name_from_id(stat_id: str) -> str:  # pyright: ignore[reportUnusedFunction]
    if "." in stat_id:
        _, key = stat_id.split(".", 1)
        return key.replace("-", " ").title()
    return stat_id.replace("-", " ").title()


def _stat_xp(stat_id: str, kb: KnowledgeStore) -> int:
    tags = kb.get_tags(stat_id)
    for tag in tags:
        if tag.startswith("cr:"):
            cr_float = cr_tag_to_float(tag)
            if cr_float is not None and cr_float in CR_XP:
                return CR_XP[cr_float]
    return 0


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
            tags = kb.get_tags(e.id)
            tag_str = " ".join(sorted(tags))
            lines.append(f"[{e.count}] {e.id} {tag_str}")
        return "\n".join(lines)


def _reduce_candidates(
    required: list[RequiredEntry], budget: int, kb: KnowledgeStore
) -> list[CandidateSolution]:
    solutions: list[CandidateSolution] = []
    
    total_xp = sum(e.count * _stat_xp(e.id, kb) for e in required)
    original_solution = CandidateSolution(entries=list(required), total_xp=total_xp)

    reduction_possible = False
    best_in_budget_solution: CandidateSolution | None = None

    for i, e in enumerate(required):
        if e.count > 1:
            xp = _stat_xp(e.id, kb)
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
                    if best_in_budget_solution is None or abs(new_total_xp - budget) < abs(best_in_budget_solution.total_xp - budget):
                        best_in_budget_solution = solution

    if reduction_possible:
        original_solution.remark = "Over requested XP budget; do not use without narrative safeguards"
        if best_in_budget_solution:
            solutions = [best_in_budget_solution] + [s for s in solutions if s != best_in_budget_solution]
        solutions.append(original_solution)
    else:
        original_solution.remark = "⚠ required monster(s) alone exceed budget — no reduction possible"
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
        # random.choices returns a list, k=1 means 1 element
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
    
    # If there are no optional monsters, we can only add more of the required monsters
    if not optional:
        if not required:
            return solutions
            
        # Add extras to existing required entries proportionately
        for e in required:
            xp = _stat_xp(e.id, kb)
            if xp == 0:
                continue
            extra = math.floor(remaining / xp)
            if extra >= 1:
                new_entries = list(required)
                idx = new_entries.index(e)
                new_entries[idx] = RequiredEntry(id=e.id, count=e.count + extra)
                total_xp = sum(x.count * _stat_xp(x.id, kb) for x in new_entries)
                solutions.append(CandidateSolution(entries=new_entries, total_xp=total_xp))
        return solutions
    
    # We have optional fillers, let's try to hit the remaining budget exactly 3 times
    for _ in range(3):
        types_to_add = _weighted_sample(optional)
        rem = remaining
        fill_entries: list[RequiredEntry] = []
        for t in types_to_add:
            xp = _stat_xp(t, kb)
            if xp == 0:
                continue
            # Try to add enough to eat the remaining budget
            count = math.floor(rem / xp)
            if count >= 1:
                rem -= count * xp
                fill_entries.append(RequiredEntry(id=t, count=count))
            
            min_xp = min((_stat_xp(opt, kb) for opt in optional if _stat_xp(opt, kb) > 0), default=0)
            if min_xp > 0 and rem < min_xp:
                break
                
        if fill_entries:
            combined = list(required) + fill_entries
            total_xp = sum(e.count * _stat_xp(e.id, kb) for e in combined)
            solutions.append(CandidateSolution(entries=combined, total_xp=total_xp))
            
    # Add one more option that is highly varied (trying ALL optional types at least 1)
    if remaining > 0 and optional:
        rem = remaining
        fill_entries = []
        for opt in optional:
            xp = _stat_xp(opt, kb)
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
            total_xp = sum(e.count * _stat_xp(e.id, kb) for e in combined)
            solutions.append(CandidateSolution(entries=combined, total_xp=total_xp))
            
    return solutions


def _rank_solutions(solutions: list[CandidateSolution], budget: int) -> list[CandidateSolution]:
    def sort_key(s: CandidateSolution) -> tuple[int, int]:
        dist = abs(s.total_xp - budget)
        under = 0 if s.total_xp <= budget else 1
        return (dist, under)
        
    solutions.sort(key=sort_key)
    
    # Deduplicate based on id/count
    deduped: list[CandidateSolution] = []
    seen: set[frozenset[tuple[str, int]]] = set()
    for s in solutions:
        key = frozenset((e.id, e.count) for e in s.entries)
        if key not in seen:
            seen.add(key)
            deduped.append(s)
            
    return deduped[:3]


def compute_encounters(
    required_raw: list[dict[str, Any]],
    optional: list[str],
    difficulty: str,
    pcs: list[int],
    allies: list[str],
    kb: KnowledgeStore,
) -> str:
    if not required_raw and not optional:
        return "Error: Both required and optional lists are empty. Nothing to build an encounter from."
        
    budget = 0
    for pc_lvl in pcs:
        if pc_lvl in XP_BUDGET and difficulty in XP_BUDGET[pc_lvl]:
            budget += XP_BUDGET[pc_lvl][difficulty]
            
    ally_xp = 0
    for ally_cr in allies:
        f = cr_str_to_float(ally_cr)
        if f is not None and f in CR_XP:
            ally_xp += CR_XP[f]

    # Allies increase party strength, so we add their XP to the budget (more room for monsters at same difficulty).
    adjusted_budget = budget + ally_xp

    if budget == 0:
        return f"Error: Invalid difficulty '{difficulty}' (should be low, moderate, or high) or invalid PC levels."

    required: list[RequiredEntry] = []
    for r in required_raw:
        if "id" in r and "count" in r:
            required.append(RequiredEntry(id=r["id"], count=r["count"]))

    committed_xp = sum(e.count * _stat_xp(e.id, kb) for e in required)

    solutions: list[CandidateSolution] = []
    
    if committed_xp > adjusted_budget:
        remaining = 0
        solutions = _reduce_candidates(required, adjusted_budget, kb)
    else:
        remaining = adjusted_budget - committed_xp
        solutions = _fill_candidates(required, remaining, optional, kb)
        if not solutions:
            # If fill failed (e.g. no optionals fit in remaining budget), try returning just the required ones
            if required:
                solutions = [CandidateSolution(entries=required, total_xp=committed_xp)]
            elif optional:
                # If we have no required and couldn't fill (maybe budget too low for any optional), 
                # grab the absolute cheapest optional and put 1 in so we emit SOMETHING.
                cheapest = min(optional, key=lambda x: _stat_xp(x, kb))
                xp = _stat_xp(cheapest, kb)
                if xp > 0:
                    solutions = [CandidateSolution(entries=[RequiredEntry(id=cheapest, count=1)], total_xp=xp, remark="budget too low for any candidate; emitting cheapest")]
            
    if not solutions:
        return "Error: Could not generate any encounter proposals."
        
    ranked = _rank_solutions(solutions, adjusted_budget)
    
    party_size = len(pcs) + len(allies)
    
    output: list[str] = [
        "Encounter Proposals",
        "Line format: [creature qty] stat.id ..tags..",
        ""
    ]
    
    options = ["A", "B", "C"]
    for i, sol in enumerate(ranked):
        remarks: list[str] = []
        if sol.remark:
            remarks.append(sol.remark)

        total_monsters = sum(e.count for e in sol.entries)
        if party_size > 0 and (total_monsters / party_size) > 4:
            remarks.append("You have more than the recommended number of enemies per ally; this encounter may be harder than CR math suggests, consider lowering enemy count")
            
        if not optional and remaining > 0 and committed_xp <= adjusted_budget and not [e for e in required if _stat_xp(e.id, kb) > 0 and math.floor(remaining / _stat_xp(e.id, kb)) >= 1]:
            remarks.append("no optional candidates provided; consider using kb with-tag to discover candidates first")
            
        header = f"> Option {options[i]}"
        if remarks:
            header += f" ({'; '.join(remarks)})"
            
        output.append(header)
        output.append(sol.serialize(kb))
        output.append("")
        
    return "\n".join(output)


balance_encounter_SCHEMA = {
    "type": "object",
    "properties": {
        "required": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Stat block ID, e.g. 'stat.vampire'"},
                    "count": {"type": "integer", "minimum": 1}
                },
                "required": ["id", "count"]
            },
            "description": "Monsters that must appear with specific counts. Can be empty if the AI has no fixed requirements."
        },
        "optional": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ranked list of stat block IDs to fill out the encounter (most preferred first). The tool picks counts. Any number of candidates — weighted randomization ensures lower-ranked options still appear occasionally."
        },
        "difficulty": {
            "type": "string",
            "enum": ["low", "moderate", "high"],
            "description": "Target encounter difficulty."
        },
        "pcs": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1, "maximum": 20},
            "description": "PC levels, one integer per PC. Example: [5, 5, 5, 5]."
        },
        "allies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional ally CRs as fraction strings ('1/2', '2', etc.) that fight with the party and increase the effective budget (encounter becomes easier)."
        }
    },
    "required": ["required", "optional", "difficulty", "pcs"]
}


async def _balance_encounter_command_tool(args: dict[str, Any], project_root: Path) -> str:
    required = args.get("required", [])
    optional = args.get("optional", [])
    difficulty = args.get("difficulty", "moderate")
    pcs = args.get("pcs", [])
    allies = args.get("allies", [])
    kb = KnowledgeStore.for_project(project_root)
    return compute_encounters(required, optional, difficulty, pcs, allies, kb)


_BALANCE_ENCOUNTER_DESCRIPTION = PromptStore(None).get(tool_prompt_key("balance_encounter"))

register_command_tool(
    "balance_encounter",
    CommandToolDef(
        description=_BALANCE_ENCOUNTER_DESCRIPTION,
        parameters=balance_encounter_SCHEMA,
        limited_to_datasets=["dnd"],
    ),
    _balance_encounter_command_tool,
)
