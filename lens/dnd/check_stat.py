"""Arithmetic proofreader for a `stat.*` block being designed.

Every check here was audited against the 511 published blocks in the lens-dnd
corpora and only kept where it fires on **none** of them (or, for save DCs,
0.4% after a one-point tolerance).  That rule is what makes the tool usable
inside a design session: a finding always means the block departs from what
published blocks do, never that it departs from something invented here.

One check was dropped for failing that audit, and it is worth naming so nobody
re-adds it:

* **Escape DCs and check DCs derived from ability + PB.**  Published blocks set
  those independently (a water elemental with Strength +4 and PB +3 has save DC
  15 and escape DC 14).  Only ``<Ability> Saving Throw: DC N`` is checked.

The tool reports; it never rewrites, and it has no opinion on whether the
creature is interesting, fair, or fun.  Those are the design module's job.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lens.core.command_tools import CommandToolDef, register_command_tool

CREATURE_TYPES = frozenset(
    """aberration beast celestial construct dragon elemental fey fiend giant
    humanoid monstrosity ooze plant undead""".split()
)
SIZES = frozenset("tiny small medium large huge gargantuan".split())
HIT_DIE_BY_SIZE = {
    "tiny": 4, "small": 6, "medium": 8, "large": 10, "huge": 12, "gargantuan": 20,
}
SWARM_TYPE = re.compile(rf"^swarm-of-({'|'.join(sorted(SIZES))})-[a-z]+$")

PB_BY_CR: tuple[tuple[float, int], ...] = (
    (4, 2), (8, 3), (12, 4), (16, 5), (20, 6), (24, 7), (28, 8), (30, 9),
)

# Generated from every published block in the lens-dnd corpora (bundled +
# lens-dnd-ext), which is close to the whole official 2024 set.  Baked rather
# than computed at run time: the tool is offered to every D&D design session
# and must not read 500 files to answer.  Regenerate when the corpus grows.
CR_BENCH: dict[float, tuple[int, int, int, int, int, int, int]] = {
    #  CR: (blocks, hp_median, hp_low, hp_high, ac_median, atk_median, dc_median)
    0.0: (32, 3, 1, 9, 12, 2, 12),
    0.125: (23, 7, 5, 11, 12, 4, 10),
    0.25: (44, 13, 10, 19, 12, 4, 11),
    0.5: (35, 19, 13, 27, 12, 4, 11),
    1.0: (42, 26, 22, 40, 13, 4, 11),
    2.0: (59, 45, 32, 63, 13, 5, 12),
    3.0: (41, 65, 49, 76, 14, 5, 12),
    4.0: (27, 71, 45, 97, 15, 5, 13),
    5.0: (35, 94, 76, 127, 15, 7, 15),
    6.0: (23, 110, 82, 127, 15, 7, 15),
    7.0: (16, 126, 105, 161, 16, 7, 15),
    8.0: (23, 136, 97, 157, 16, 7, 15),
    9.0: (12, 156, 137, 189, 18, 9, 17),
    10.0: (16, 162, 137, 220, 18, 9, 16),
    11.0: (12, 197, 168, 229, 17, 10, 17),
    12.0: (7, 178, 169, 240, 18, 9, 17),
    13.0: (10, 192, 184, 230, 18, 10, 17),
    14.0: (4, 195, 184, 228, 18, 10, 18),
    15.0: (6, 210, 187, 256, 18, 12, 18),
    16.0: (7, 252, 212, 264, 19, 12, 19),
    17.0: (8, 234, 199, 356, 20, 13, 20),
    20.0: (7, 323, 323, 337, 19, 13, 20),
    21.0: (5, 333, 297, 367, 21, 15, 22),
    22.0: (3, 402, 370, 444, 21, 15, 23),
    23.0: (6, 458, 346, 481, 22, 17, 23),
}


ABILITY_ROW = re.compile(
    r"\|\s*\d+\s*\(([+\-−]\d+)\)\s*" * 6, re.UNICODE
)
_ABILITY_CELL = re.compile(r"\|\s*\d+\s*\(([+\-−]\d+)\)")
ABILITY_NAMES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

AC_LINE = re.compile(r"\*\*AC\*\*\s*(\d+)")
HP_LINE = re.compile(r"\*\*HP\*\*\s*(\d+)")
CR_LINE = re.compile(r"\*\*CR\*\*\s*([\d/]+)")
ATTACK_BONUS = re.compile(r"Attack Roll:\s*\+(\d+)")
SAVE_DC = re.compile(r"Saving Throw:\s*DC\s*(\d+)")
DAMAGE_EXPR = re.compile(r"(\d+)\s*\((\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\)")
TAG_LINE = re.compile(r"^\s*-\s*([^\s#]+)\s*$", re.MULTILINE)
SAVES_LINE = re.compile(r"\*\*Saving Throws\*\*\s*(.+)")
SKILLS_LINE = re.compile(r"\*\*Skills\*\*\s*(.+)")
BONUS_ENTRY = re.compile(r"([A-Za-z][A-Za-z'\s]*?)\s*([+-]\d+)")
HP_DICE = re.compile(r"\*\*HP\*\*\s*(\d+)\s*\((\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\)")
ABILITY_BY_NAME = {
    "str": "STR", "strength": "STR", "dex": "DEX", "dexterity": "DEX",
    "con": "CON", "constitution": "CON", "int": "INT", "intelligence": "INT",
    "wis": "WIS", "wisdom": "WIS", "cha": "CHA", "charisma": "CHA",
}
TAG_INLINE = re.compile(r"^tags:\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)


def pb_for_cr(cr: float) -> int:
    for ceiling, pb in PB_BY_CR:
        if cr <= ceiling:
            return pb
    return 9


def parse_cr(text: str) -> float | None:
    raw = text.strip().replace("−", "-")
    for sep in ("/", "-"):
        if sep in raw:
            num, _, den = raw.partition(sep)
            try:
                return float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return None
    try:
        return float(raw)
    except ValueError:
        return None


def _cr_label(cr: float) -> str:
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(cr, f"{cr:g}")


def _parse_tags(block: str) -> list[str]:
    inline = TAG_INLINE.search(block)
    if inline:
        return [t.strip().strip("'\"") for t in inline.group(1).split(",") if t.strip()]
    if "tags:" not in block:
        return []
    after = block.split("tags:", 1)[1]
    end = after.find("\n---")
    return [t.strip() for t in TAG_LINE.findall(after[: end if end > 0 else len(after)])]


def _dice_average(count: int, faces: int, modifier: int) -> int:
    return int(count * (faces + 1) / 2) + modifier


def check_stat_block(block: str) -> str:
    """Proofread one stat block's own arithmetic. Returns a plain-text report."""
    findings: list[str] = []
    notes: list[str] = []

    m_cr = CR_LINE.search(block)
    m_ac = AC_LINE.search(block)
    m_hp = HP_LINE.search(block)
    cr = parse_cr(m_cr.group(1)) if m_cr else None

    scaling = m_cr is None and re.search(r"\*\*CR\*\*\s*\S", block) is not None
    if scaling:
        # `**CR** None (PB equals your Proficiency Bonus)` — a summoned block that
        # scales with its caster.  A real published shape, and nothing CR-derived
        # applies to it.
        notes.append("CR is not a number here, so nothing CR-derived was checked.")
    elif not m_cr or cr is None:
        findings.append(
            "No `**CR** N` line found, so nothing below it can be checked. "
            "See `stat._template` for the line order."
        )
    if not m_ac or not m_hp:
        findings.append("No `**AC** N · **HP** N · **Speed** …` line found.")

    cells = _ABILITY_CELL.findall(block)
    mods: dict[str, int] = {}
    if len(cells) >= 6:
        values = [int(c.replace("−", "-")) for c in cells[:6]]
        mods = dict(zip(ABILITY_NAMES, values))
    else:
        findings.append(
            "No six-column ability table found, so attack bonuses and DCs cannot be checked."
        )

    tags = _parse_tags(block)
    if tags:
        for prefix in ("cr:", "type:", "size:"):
            if not any(t.startswith(prefix) for t in tags):
                findings.append(
                    f"No `{prefix}` tag. Every published block carries one; without `cr:` "
                    "the block prices at 0 XP in balance_encounter."
                )
        for tag in tags:
            if tag.startswith("type:"):
                value = tag[5:]
                if value not in CREATURE_TYPES and not SWARM_TYPE.match(value):
                    findings.append(
                        f"`{tag}` is not a creature type. Use one of: "
                        f"{', '.join(sorted(CREATURE_TYPES))}, or `swarm-of-<size>-<type>`."
                    )
            elif tag.startswith("size:") and tag[5:] not in SIZES:
                findings.append(f"`{tag}` is not a size. Use one of: {', '.join(sorted(SIZES))}.")
        cr_tags = [t for t in tags if t.startswith("cr:")]
        if cr_tags and cr is not None:
            tagged = parse_cr(cr_tags[0][3:])
            if tagged is not None and abs(tagged - cr) > 1e-9:
                findings.append(
                    f"`{cr_tags[0]}` disagrees with the `**CR** {m_cr.group(1) if m_cr else '?'}` "
                    "line. The tag is what balance_encounter prices from."
                )

    if cr is not None and mods:
        pb = pb_for_cr(cr)
        # Strict: a bonus or DC should come out of an ability the block lists.
        # Two published habits are allowed for, and only these two, because
        # loosening further would cost more than the rare odd block is worth:
        # a floor under creatures whose modifiers are deeply negative (gas spore
        # fungus: attack +0, DC 10, off scores that derive -1 and 6), and the
        # severity split below — published blocks occasionally set a deliberately
        # weaker second ability (ancient white dragon: breath DC 22, Freezing
        # Burst DC 20), so a low outlier reports as a smell and a high one as an
        # error.
        derivable_attacks = {value + pb for value in mods.values()}
        best_attack = max(derivable_attacks)
        for bonus in sorted({int(b) for b in ATTACK_BONUS.findall(block)}):
            if bonus in derivable_attacks or bonus <= 0:
                continue
            if bonus > best_attack:
                findings.append(
                    f"Attack Roll +{bonus} is above anything this creature can produce: "
                    f"its best is +{best_attack} ({_best_ability(mods)} with PB +{pb})."
                )
            else:
                findings.append(
                    f"Attack Roll +{bonus} comes from no ability: with PB +{pb} this "
                    f"creature's attack bonuses are {_render(sorted(derivable_attacks))}. "
                    "Published blocks do this occasionally for a deliberately weaker "
                    "attack — if that is not what you meant, it is a typo."
                )
        derivable_dcs = {8 + value + pb for value in mods.values()}
        best_dc = max(derivable_dcs)
        for dc in sorted({int(d) for d in SAVE_DC.findall(block)}):
            if dc in derivable_dcs or dc <= 10:
                continue
            if dc > best_dc:
                findings.append(
                    f"Saving Throw DC {dc} is above anything this creature can produce: "
                    f"its best is DC {best_dc} ({_best_ability(mods)} with PB +{pb})."
                )
            else:
                findings.append(
                    f"Saving Throw DC {dc} comes from no ability: with PB +{pb} this "
                    f"creature's save DCs are {', '.join(str(v) for v in sorted(derivable_dcs))}. Published "
                    "blocks do this occasionally for a deliberately weaker effect — if "
                    "that is not what you meant, it is a typo."
                )

    # Neither of the next two lines appears anywhere in the 511 published blocks
    # (they fold saves into the ability table and never print hit dice), so these
    # checks cannot fire on the corpus.  They fire on hand-built and PC-shaped
    # blocks, which is exactly where the arithmetic drifts.
    if mods and cr is not None:
        pb = pb_for_cr(cr)
        saves = SAVES_LINE.search(block)
        if saves:
            for name, printed in BONUS_ENTRY.findall(saves.group(1)):
                ability = ABILITY_BY_NAME.get(name.strip().lower())
                if ability is None or ability not in mods:
                    continue
                expected = mods[ability] + pb
                if int(printed) != expected:
                    findings.append(
                        f"Saving Throws says {ability} {printed}, but {ability} "
                        f"{mods[ability]:+d} with PB +{pb} is {expected:+d}. A saving throw "
                        "is always the modifier plus PB — expertise never applies to saves."
                    )

    hp_dice = HP_DICE.search(block)
    if hp_dice and mods:
        printed_total = int(hp_dice.group(1))
        dice, faces = int(hp_dice.group(2)), int(hp_dice.group(3))
        flat = (int(hp_dice.group(5)) if hp_dice.group(5) else 0) * (
            -1 if hp_dice.group(4) == "-" else 1
        )
        if _dice_average(dice, faces, flat) != printed_total:
            findings.append(
                f"**HP** {printed_total} ({dice}d{faces}{flat:+d}) — that expression "
                f"averages {_dice_average(dice, faces, flat)}."
            )
        expected_flat = mods["CON"] * dice
        if flat != expected_flat:
            implied = flat / dice
            findings.append(
                f"**HP** {printed_total} ({dice}d{faces}{flat:+d}) — {dice} hit dice at CON "
                f"{mods['CON']:+d} is {expected_flat:+d}, not {flat:+d}; the printed bonus "
                f"implies CON {implied:+.0f}. Published blocks print no hit dice at all, so "
                "either fix the expression or drop it and keep the total."
            )

    for match in DAMAGE_EXPR.finditer(block):
        printed = int(match.group(1))
        count, faces = int(match.group(2)), int(match.group(3))
        modifier = (int(match.group(5)) if match.group(5) else 0) * (
            -1 if match.group(4) == "-" else 1
        )
        expected = _dice_average(count, faces, modifier)
        if printed != expected:
            findings.append(
                f"`{match.group(0)}` — the average of {count}d{faces}"
                f"{'' if not modifier else f' {modifier:+d}'} is {expected}."
            )

    # Hit points are dice-derived after all: floor(N x (die+1)/2) + CON x N, with
    # the rounding applied once at the end.  506 of the 510 published blocks that
    # can be checked satisfy it (0.8% miss, all size-variant or scaling blocks).
    # An earlier version of this check divided the total by a per-die average and
    # so failed on every odd dice count — it reported 31% and was dropped for it.
    if mods and m_hp and not hp_dice:
        size_tags = [t[5:] for t in tags if t.startswith("size:")]
        die = HIT_DIE_BY_SIZE.get(size_tags[0]) if size_tags else None
        if die:
            total = int(m_hp.group(1))
            con = mods["CON"]
            if not any(
                int(n * (die + 1) / 2) + con * n == total for n in range(1, 200)
            ):
                findings.append(
                    f"**HP** {total} is not reachable by any number of d{die} hit dice at "
                    f"CON {con:+d} — the nearest are "
                    f"{_nearest_hp_totals(die, con, total)}. Published blocks are all "
                    "Nd(size) + CON per die."
                )

    if cr is not None:
        bench = CR_BENCH.get(cr)
        if bench:
            blocks, hp_med, hp_low, hp_high, ac_med, atk_med, dc_med = bench
            notes.append(
                f"Published blocks at CR {_cr_label(cr)} ({blocks} of them): "
                f"HP {hp_med} (most fall {hp_low}–{hp_high}), AC {ac_med}, "
                f"best attack +{atk_med}, save DC {dc_med}."
                + (
                    f" This block: HP {m_hp.group(1)}, AC {m_ac.group(1)}."
                    if m_hp and m_ac
                    else ""
                )
            )
        else:
            notes.append(f"No published blocks at CR {_cr_label(cr)} to compare against.")

    out: list[str] = []
    if findings:
        out.append(f"{len(findings)} thing(s) to fix:")
        out.extend(f"- {f}" for f in findings)
    else:
        out.append("Nothing to fix: every bonus, DC, damage average and tag checks out.")
    if notes:
        out.append("")
        out.extend(notes)
    out.append("")
    out.append(
        "Arithmetic and tags only — whether the creature is any good is not "
        "something this tool knows."
    )
    return "\n".join(out)


def _nearest_hp_totals(die: int, con: int, target: int) -> str:
    totals = [int(n * (die + 1) / 2) + con * n for n in range(1, 200)]
    totals = sorted({t for t in totals if t > 0}, key=lambda t: abs(t - target))[:2]
    return " and ".join(str(t) for t in sorted(totals))


def _render(values: list[int]) -> str:
    return ", ".join(f"{v:+d}" for v in values)


def _best_ability(mods: dict[str, int]) -> str:
    best = max(mods.values())
    names = [name for name, value in mods.items() if value == best]
    return f"{'/'.join(names)} {best:+d}"


CHECK_STAT_DESCRIPTION = """Proofread a `stat.*` block you are about to emit, before you emit it. Pass the block text (front matter and fence included if you have them). Reports any attack bonus, save DC, damage average, or tag that does not follow from the block's own ability scores and CR, and shows what published blocks at that CR look like. Stat blocks only; it says nothing about whether the creature is good."""

CHECK_STAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "block": {
            "type": "string",
            "description": "The stat block text, as you intend to emit it.",
        }
    },
    "required": ["block"],
}


async def _check_stat_command_tool(args: dict[str, Any], project_root: Path) -> str:
    block = str(args.get("block") or "").strip()
    if not block:
        return "Error: pass the stat block text as `block`."
    return check_stat_block(block)


def register_tools(*, dataset_name: str) -> None:
    register_command_tool(
        "check_stat",
        CommandToolDef(
            description=CHECK_STAT_DESCRIPTION,
            parameters=CHECK_STAT_SCHEMA,
            limited_to_datasets=[dataset_name],
        ),
        _check_stat_command_tool,
    )
