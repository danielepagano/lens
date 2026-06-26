import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lens.core.command_tools import get_command_registry
from lens.core.dataset_extensions import clear_extension_state_for_tests
from lens.dnd.balance_encounter import (
    cr_tag_to_float,
    cr_str_to_float,
    compute_encounters,
    _reduce_candidates,  # pyright: ignore[reportPrivateUsage]
    _fill_candidates,  # pyright: ignore[reportPrivateUsage]
    _rank_solutions,  # pyright: ignore[reportPrivateUsage]
    RequiredEntry,
    CandidateSolution,
)


class TestBalanceEncounter(unittest.TestCase):
    def test_cr_tag_to_float(self) -> None:
        self.assertEqual(cr_tag_to_float("cr:0"), 0.0)
        self.assertEqual(cr_tag_to_float("cr:1-8"), 0.125)
        self.assertEqual(cr_tag_to_float("cr:1-4"), 0.25)
        self.assertEqual(cr_tag_to_float("cr:1-2"), 0.5)
        self.assertEqual(cr_tag_to_float("cr:1"), 1.0)
        self.assertEqual(cr_tag_to_float("cr:2"), 2.0)
        self.assertEqual(cr_tag_to_float("cr:30"), 30.0)
        self.assertIsNone(cr_tag_to_float("not_cr"))
        self.assertIsNone(cr_tag_to_float("cr:invalid"))

    def test_cr_str_to_float(self) -> None:
        self.assertEqual(cr_str_to_float("0"), 0.0)
        self.assertEqual(cr_str_to_float("1/8"), 0.125)
        self.assertEqual(cr_str_to_float("1/4"), 0.25)
        self.assertEqual(cr_str_to_float("1/2"), 0.5)
        self.assertEqual(cr_str_to_float("1"), 1.0)
        self.assertEqual(cr_str_to_float("2"), 2.0)
        self.assertEqual(cr_str_to_float("30"), 30.0)
        self.assertIsNone(cr_str_to_float("invalid"))

    def _mock_kb(self, tag_map: dict[str, list[str]]) -> MagicMock:
        kb = MagicMock()

        def get_tags(stat_id: str) -> list[str]:
            return tag_map.get(stat_id, [])

        kb.get_tags.side_effect = get_tags
        return kb

    def test_reduce_path_reducible(self) -> None:
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]})  # XP = 50
        required = [RequiredEntry(id="stat.zombie", count=80)]
        budget = 3000

        solutions = _reduce_candidates(required, budget, kb)

        self.assertEqual(len(solutions), 2)
        self.assertEqual(solutions[0].entries[0].count, 60)
        self.assertEqual(solutions[0].total_xp, 3000)
        self.assertEqual(solutions[1].entries[0].count, 80)
        self.assertEqual(solutions[1].total_xp, 4000)
        self.assertEqual(
            solutions[1].remark,
            "Over requested XP budget; do not use without narrative safeguards",
        )

    def test_reduce_path_not_reducible(self) -> None:
        kb = self._mock_kb({"stat.vampire": ["cr:13"]})  # XP = 10000
        required = [RequiredEntry(id="stat.vampire", count=1)]
        budget = 3000

        solutions = _reduce_candidates(required, budget, kb)

        self.assertEqual(len(solutions), 1)
        self.assertEqual(solutions[0].entries[0].count, 1)
        self.assertEqual(solutions[0].total_xp, 10000)
        self.assertEqual(
            solutions[0].remark,
            "required monster(s) alone exceed budget — no reduction possible",
        )

    def test_fill_path_no_optional(self) -> None:
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]})  # XP = 50
        required = [RequiredEntry(id="stat.zombie", count=20)]
        remaining = 1000

        solutions = _fill_candidates(required, remaining, [], kb)

        self.assertEqual(len(solutions), 1)
        self.assertEqual(solutions[0].entries[0].count, 40)
        self.assertEqual(solutions[0].total_xp, 2000)

    def test_fill_path_with_optional(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4"],
            "stat.wight": ["cr:3"],
            "stat.ghast": ["cr:2"],
        })
        required = [RequiredEntry(id="stat.zombie", count=20)]
        remaining = 2000
        optional = ["stat.wight", "stat.ghast"]

        import random

        random.seed(42)
        solutions = _fill_candidates(required, remaining, optional, kb)

        self.assertTrue(len(solutions) <= 4)
        for sol in solutions:
            self.assertTrue(sol.total_xp > 1000)
            self.assertTrue(sol.total_xp <= 3000)

    def test_ranking_solutions(self) -> None:
        budget = 3000
        s1 = CandidateSolution(entries=[RequiredEntry("a", 1)], total_xp=2900)
        s2 = CandidateSolution(entries=[RequiredEntry("b", 1)], total_xp=3100)
        s3 = CandidateSolution(entries=[RequiredEntry("c", 1)], total_xp=2950)

        ranked = _rank_solutions([s1, s2, s3], budget)

        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0].total_xp, 2950)
        self.assertEqual(ranked[1].total_xp, 2900)
        self.assertEqual(ranked[2].total_xp, 3100)

    def test_compute_encounters_edge_cases(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4", "type:undead"],
            "stat.dragon": ["cr:24", "type:dragon"],
            "stat.rat": ["cr:0", "type:beast"],
            "stat.wight": ["cr:3", "type:undead"],
            "stat.ally_cr20": ["cr:20", "type:humanoid"],
        })

        res = compute_encounters([], [], "moderate", [5], [], kb)
        self.assertTrue("Error:" in res)

        res = compute_encounters(
            [{"id": "stat.zombie", "count": 1}],
            [],
            "moderate",
            [1],
            [{"id": "stat.ally_cr20", "count": 1}],
            kb,
        )
        self.assertIn("stat.zombie", res)
        self.assertNotIn("Error:", res)

        res = compute_encounters([], ["stat.zombie"], "impossible", [1], [], kb)
        self.assertTrue("Error: Invalid difficulty 'impossible'" in res)

        res = compute_encounters([], ["stat.dragon", "stat.wight"], "moderate", [1], [], kb)
        self.assertTrue("budget too low for any candidate; emitting cheapest" in res)
        self.assertTrue("stat.wight" in res)

        res = compute_encounters([{"id": "stat.wight", "count": 1}], [], "moderate", [5, 1], [], kb)
        self.assertTrue("no optional candidates provided; consider using kb with-tag" in res)

        res = compute_encounters([{"id": "stat.zombie", "count": 20}], [], "moderate", [5, 5, 5, 5], [], kb)
        self.assertIn("enemies per party member", res)

    def test_compute_encounters_full_run(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4", "type:undead"],
            "stat.wight": ["cr:3", "type:undead"],
        })
        required = [{"id": "stat.zombie", "count": 20}]
        optional = ["stat.wight"]
        pcs = [5, 5, 5, 5]

        res = compute_encounters(required, optional, "moderate", pcs, [], kb)

        self.assertFalse("Error:" in res)
        self.assertTrue("stat.zombie" in res)
        self.assertTrue("stat.wight" in res)
        self.assertTrue("Option A" in res)

    def test_allies_increase_budget_deterministic_fill(self) -> None:
        import re

        def zombie_qty_option_a(s: str) -> int:
            start = s.find("> Option A")
            assert start >= 0, s
            end = s.find("> Option B", start)
            block = s[start:end] if end > start else s[start:]
            m = re.search(r"\[(\d+)\] stat\.zombie", block)
            assert m is not None, block
            return int(m.group(1))

        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4", "type:undead"],
            "stat.ally_fodder": ["cr:1-8", "type:humanoid"],
            "stat.ally_officer": ["cr:1", "type:humanoid"],
        })
        required = [{"id": "stat.zombie", "count": 1}]
        optional: list[str] = []
        pcs = [3, 3, 3, 3]

        res_pc_only = compute_encounters(required, optional, "moderate", pcs, [], kb)
        allies = [{"id": "stat.ally_fodder", "count": 12}, {"id": "stat.ally_officer", "count": 2}]
        res_with_allies = compute_encounters(required, optional, "moderate", pcs, allies, kb)

        self.assertEqual(zombie_qty_option_a(res_pc_only), 18)
        self.assertEqual(zombie_qty_option_a(res_with_allies), 32)
        self.assertGreater(zombie_qty_option_a(res_with_allies), zombie_qty_option_a(res_pc_only))

    def test_allies_rejects_non_object_entries(self) -> None:
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]})
        res = compute_encounters([], ["stat.zombie"], "moderate", [3], ["stat.guard"], kb)
        self.assertIn("Error:", res)
        self.assertIn("each 'allies' entry", res)

    def test_required_rejects_non_object_entries(self) -> None:
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]})
        res = compute_encounters(["stat.zombie"], [], "moderate", [3], [], kb)
        self.assertIn("Error:", res)
        self.assertIn("each 'required' entry", res)


class TestBalanceEncounterCommandToolRegistration(unittest.TestCase):
    """Verify balance_encounter is registered via dataset extension and gated on lens-dnd."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)

    def tearDown(self) -> None:
        clear_extension_state_for_tests()
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_dnd_project(self, datasets_line: str) -> None:
        (self.root / "lens.toml").write_text(f"[project]\n{datasets_line}\n")

    def test_balance_encounter_in_command_registry(self) -> None:
        self._write_dnd_project('datasets = ["lens-dnd"]')
        registry = get_command_registry(self.root)
        self.assertIn(
            "balance_encounter",
            registry,
            "balance_encounter was not registered as a command tool; "
            "it will be invisible to the design operator",
        )

    def test_balance_encounter_limited_to_dnd_dataset(self) -> None:
        self._write_dnd_project('datasets = ["lens-dnd"]')
        registry = get_command_registry(self.root)
        tool_def, _ = registry["balance_encounter"]
        self.assertEqual(
            tool_def.limited_to_datasets,
            ["lens-dnd"],
            "balance_encounter should be limited to the 'lens-dnd' dataset",
        )

    def test_balance_encounter_excluded_without_dnd_dataset(self) -> None:
        (self.root / "lens.toml").write_text("[project]\n")
        registry = get_command_registry(self.root)
        self.assertNotIn(
            "balance_encounter",
            registry,
            "balance_encounter should be hidden when the lens-dnd dataset is not active",
        )

    def test_balance_encounter_excluded_with_other_dataset(self) -> None:
        (self.root / "lens.toml").write_text('[project]\ndatasets = ["rpg"]\n')
        registry = get_command_registry(self.root)
        self.assertNotIn("balance_encounter", registry)

    def test_balance_encounter_included_with_dnd_dataset(self) -> None:
        self._write_dnd_project('datasets = ["lens-dnd"]')
        registry = get_command_registry(self.root)
        self.assertIn(
            "balance_encounter",
            registry,
            "balance_encounter should be available when the lens-dnd dataset is active",
        )

    def test_balance_encounter_included_with_dnd_among_datasets(self) -> None:
        self._write_dnd_project('datasets = ["rpg", "lens-dnd"]')
        registry = get_command_registry(self.root)
        self.assertIn("balance_encounter", registry)

    def test_balance_encounter_has_schema_and_description(self) -> None:
        self._write_dnd_project('datasets = ["lens-dnd"]')
        registry = get_command_registry(self.root)
        tool_def, fn = registry["balance_encounter"]
        self.assertTrue(tool_def.description, "description must not be empty")
        self.assertIn("required", tool_def.parameters.get("required", []))
        self.assertIsNotNone(fn)
