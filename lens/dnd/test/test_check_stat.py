"""The checker's contract: it is silent on published blocks, loud on arithmetic.

The corpus sweep is the load-bearing test. Every check in ``check_stat`` was
kept only because it fires on ~none of the 511 published blocks in the lens-dnd
corpora; a check that starts flagging real monsters is a check that has become
an opinion, and the tool is offered to every D&D design session on the promise
that it has none.
"""

from __future__ import annotations

import pathlib
import unittest

from lens.dnd.check_stat import CR_BENCH, check_stat_block, parse_cr, pb_for_cr

GOBLIN_BOSS = """---
id: stat.goblin-boss
tags:
  - cr:1
  - type:fey
  - size:small
---
**Goblin Boss** · Small Fey, Chaotic Neutral

**AC** 17 · **HP** 21 · **Speed** 30 ft.

| STR | DEX | CON | INT | WIS | CHA |
|-----|-----|-----|-----|-----|-----|
| 10 (+0) | 15 (+2) | 10 (+0) | 10 (+0) | 8 (-1) | 10 (+0) |

**Skills** Stealth +6
**Senses** Darkvision 60 ft.,  Passive Perception 9
**Languages** Common, Goblin
**CR** 1

---
**Actions**

Scimitar. Melee Attack Roll: +4, reach 5 ft. Hit: 5 (1d6 + 2) Slashing damage.
"""


def _swap(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


class TestCheckStatBlock(unittest.TestCase):
    def test_clean_block_reports_nothing(self) -> None:
        out = check_stat_block(GOBLIN_BOSS)
        self.assertTrue(out.startswith("Nothing to fix"), out)

    def test_context_line_names_the_corpus_not_a_verdict(self) -> None:
        """The CR comparison is context. It must never read as a finding."""
        out = check_stat_block(GOBLIN_BOSS)
        self.assertIn("Published blocks at CR 1", out)
        self.assertNotIn("- Published blocks", out)

    def test_damage_average_must_match_its_dice(self) -> None:
        """The failure every model made and no prompt wording fixed."""
        out = check_stat_block(_swap(GOBLIN_BOSS, "5 (1d6 + 2)", "7 (1d6 + 2)"))
        self.assertIn("the average of 1d6 +2 is 5", out)

    def test_attack_bonus_above_every_ability_is_an_error(self) -> None:
        out = check_stat_block(_swap(GOBLIN_BOSS, "Attack Roll: +4", "Attack Roll: +9"))
        self.assertIn("above anything this creature can produce", out)

    def test_dc_above_every_ability_is_an_error(self) -> None:
        block = _swap(
            GOBLIN_BOSS,
            "Hit: 5 (1d6 + 2) Slashing damage.",
            "Strength Saving Throw: DC 15, one creature.",
        )
        out = check_stat_block(block)
        self.assertIn("Saving Throw DC 15 is above anything", out)

    def test_dc_below_the_best_ability_is_a_smell_not_an_error(self) -> None:
        """Published blocks give a deliberately weaker second effect a lower DC
        (ancient white dragon: breath DC 22, Freezing Burst DC 20), so this is
        reported as possible-typo rather than as impossible."""
        block = _swap(
            GOBLIN_BOSS,
            "Hit: 5 (1d6 + 2) Slashing damage.",
            "Strength Saving Throw: DC 11, one creature.",
        )
        out = check_stat_block(block)
        self.assertIn("comes from no ability", out)
        self.assertNotIn("above anything", out)

    def test_escape_dcs_are_not_checked(self) -> None:
        """Published escape DCs do not follow 8 + mod + PB — a water elemental
        with Strength +4 and PB +3 has save DC 15 and escape DC 14."""
        block = _swap(
            GOBLIN_BOSS,
            "Hit: 5 (1d6 + 2) Slashing damage.",
            "Hit: 5 (1d6 + 2) Slashing damage, and the target is Grappled (escape DC 14).",
        )
        self.assertTrue(check_stat_block(block).startswith("Nothing to fix"))

    def test_missing_required_tags_are_reported(self) -> None:
        out = check_stat_block(_swap(GOBLIN_BOSS, "  - cr:1\n", ""))
        self.assertIn("No `cr:` tag", out)

    def test_cr_tag_must_agree_with_the_cr_line(self) -> None:
        out = check_stat_block(_swap(GOBLIN_BOSS, "  - cr:1\n", "  - cr:4\n"))
        self.assertIn("disagrees with", out)

    def test_swarm_types_are_valid(self) -> None:
        """2024 swarms are their own type ('Swarm of Tiny Beasts') and 11 blocks
        in the corpus use them."""
        out = check_stat_block(_swap(GOBLIN_BOSS, "type:fey", "type:swarm-of-tiny-beasts"))
        self.assertTrue(out.startswith("Nothing to fix"), out)
        bad = check_stat_block(_swap(GOBLIN_BOSS, "type:fey", "type:goblinoid"))
        self.assertIn("is not a creature type", bad)

    def test_hp_must_be_reachable_by_some_hit_dice_count(self) -> None:
        """HP is floor(N x (die+1)/2) + CON x N, with the rounding applied once
        at the end: 506 of the 510 checkable published blocks satisfy it. The
        goblin boss is Small (d6) with CON +0, so 21 is 6d6 and 22 is nothing."""
        self.assertTrue(check_stat_block(GOBLIN_BOSS).startswith("Nothing to fix"))
        out = check_stat_block(_swap(GOBLIN_BOSS, "**HP** 21", "**HP** 22"))
        self.assertIn("not reachable by any number of d6 hit dice", out)
        self.assertIn("21 and 24", out)

    def test_hp_check_needs_a_size_tag(self) -> None:
        """No size, no hit die, no check — silence rather than a guess."""
        out = check_stat_block(_swap(GOBLIN_BOSS, "  - size:small\n", ""))
        self.assertNotIn("hit dice", out)

    def test_saving_throw_line_is_checked_when_present(self) -> None:
        """No published block has this line, so the check cannot fire on the
        corpus — but hand-built and PC-shaped blocks carry one, and that is
        where the arithmetic drifts. Saves are mod + PB; expertise never applies."""
        block = _swap(
            GOBLIN_BOSS,
            "**Skills** Stealth +6",
            "**Saving Throws** DEX +4, WIS +3\n**Skills** Stealth +6",
        )
        out = check_stat_block(block)
        self.assertIn("Saving Throws says WIS +3", out)
        self.assertIn("is +1", out)
        self.assertNotIn("DEX", out.split("Published blocks")[0].replace("DEX +4", ""))

    def test_hp_dice_expression_is_checked_when_present(self) -> None:
        """`**HP** 73 (7d8 + 42)` averages correctly and still cannot be right:
        seven hit dice at CON +2 is +14. Published blocks print no hit dice, so
        this too is silent on the corpus."""
        out = check_stat_block(_swap(GOBLIN_BOSS, "**HP** 21", "**HP** 73 (7d8 + 42)"))
        self.assertIn("7 hit dice at CON +0 is +0", out)

    def test_hp_dice_average_must_match(self) -> None:
        out = check_stat_block(_swap(GOBLIN_BOSS, "**HP** 21", "**HP** 45 (9d8)"))
        self.assertIn("averages 40", out)

    def test_reports_when_it_cannot_read_the_block(self) -> None:
        out = check_stat_block("just some prose about a monster")
        self.assertIn("No `**CR** N` line", out)

    def test_bench_table_covers_the_common_range(self) -> None:
        for cr in (0.25, 1.0, 5.0, 10.0):
            self.assertIn(cr, CR_BENCH)
        blocks, hp_med, hp_low, hp_high, *_rest = CR_BENCH[5.0]
        self.assertGreater(blocks, 10)
        self.assertLessEqual(hp_low, hp_med)
        self.assertLessEqual(hp_med, hp_high)

    def test_pb_and_cr_parsing(self) -> None:
        self.assertEqual(pb_for_cr(0.25), 2)
        self.assertEqual(pb_for_cr(5), 3)
        self.assertEqual(pb_for_cr(17), 6)
        self.assertEqual(parse_cr("1/4"), 0.25)
        self.assertEqual(parse_cr("12"), 12.0)
        self.assertIsNone(parse_cr("None"))


class TestSilentOnPublishedBlocks(unittest.TestCase):
    """The contract: sweep the bundled corpus and expect near-total silence.

    A new check that flags real monsters has become an opinion, and this test is
    where that shows up. The sweep runs against the bundled dataset only; the
    same sweep over the bundled + `lens-dnd-ext` corpora (511 blocks) reports 4,
    all listed in the module docstring.
    """

    KNOWN = {
        # Corrupt since the dataset was imported: `HP unknown`, `Speed 300 ft.`,
        # CHA 50 (+20), `Stealth +50`, `Passive Perception -10`, `Languages
        # Elfish`. The checker is right about this one; the data is wrong.
        "stat.giant-crocodile",
        # Three published blocks give a secondary effect a DC lower than their
        # main one — the ancient white dragon breathes at DC 22 and its Freezing
        # Burst is DC 20. Reported as a possible typo rather than as impossible,
        # which is the intended behaviour: strict beats quiet, and a rare warning
        # on a deliberate outlier is cheaper than missing a real slip.
        "stat.adult-bronze-dragon",
        "stat.ancient-white-dragon",
        "stat.sphinx-of-valor",
        # Four totals no hit-dice count reaches: two size-variant blocks whose
        # `size:` tag does not match the die the variant was built on, a scaling
        # summon, and one import oddity. All data, not check.
        "stat.otherworldly-steed",
        "stat.warrior-infantry",
        "stat.dracolich-gargantuan",
        "stat.shadow-dragon-large",
    }

    def test_published_blocks_produce_no_findings(self) -> None:
        import tomllib

        root = pathlib.Path(__file__).resolve().parents[3] / "datasets" / "lens-dnd" / "knowledge"
        if not (root / "stat").is_dir():
            self.skipTest("bundled lens-dnd dataset not present")
        tags = tomllib.load((root / "tags.toml").open("rb")).get("objects", {})

        flagged: dict[str, list[str]] = {}
        count = 0
        for path in sorted((root / "stat").glob("*.md")):
            if path.stem == "_template":
                continue
            count += 1
            kb_id = f"stat.{path.stem}"
            front = "---\nid: {}\ntags:\n{}---\n".format(
                kb_id, "".join(f"  - {t}\n" for t in tags.get(kb_id, []))
            )
            report = check_stat_block(front + path.read_text(encoding="utf-8"))
            if not report.startswith("Nothing to fix"):
                flagged[kb_id] = [
                    line for line in report.splitlines() if line.startswith("- ")
                ]

        self.assertGreater(count, 300, "corpus sweep found almost no blocks to check")
        unexpected = {k: v for k, v in flagged.items() if k not in self.KNOWN}
        self.assertEqual(unexpected, {}, "checker gained an opinion about published blocks")
        # And keep it quantitative: silence on published data is the whole promise.
        self.assertLess(len(flagged) / count, 0.02)


if __name__ == "__main__":
    unittest.main()
