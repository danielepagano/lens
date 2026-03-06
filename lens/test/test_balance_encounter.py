import unittest
from unittest.mock import MagicMock
from lens.core.commands.balance_encounter import (
    cr_tag_to_float,
    cr_str_to_float,
    compute_encounters,
    _reduce_candidates, # pyright: ignore[reportPrivateUsage]
    _fill_candidates, # pyright: ignore[reportPrivateUsage]
    _rank_solutions, # pyright: ignore[reportPrivateUsage]
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
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]}) # XP = 50
        # 80 zombies = 4000 XP
        required = [RequiredEntry(id="stat.zombie", count=80)]
        budget = 3000
        
        solutions = _reduce_candidates(required, budget, kb)
        
        self.assertEqual(len(solutions), 2)
        # Reduced option should be first (in budget)
        self.assertEqual(solutions[0].entries[0].count, 60)
        self.assertEqual(solutions[0].total_xp, 3000)
        
        # Original option should be second
        self.assertEqual(solutions[1].entries[0].count, 80)
        self.assertEqual(solutions[1].total_xp, 4000)
        self.assertEqual(solutions[1].remark, "Over requested XP budget; do not use without narrative safeguards")

    def test_reduce_path_not_reducible(self) -> None:
        kb = self._mock_kb({"stat.vampire": ["cr:13"]}) # XP = 10000
        # 1 vampire = 10000 XP
        required = [RequiredEntry(id="stat.vampire", count=1)]
        budget = 3000
        
        solutions = _reduce_candidates(required, budget, kb)
        
        self.assertEqual(len(solutions), 1)
        self.assertEqual(solutions[0].entries[0].count, 1)
        self.assertEqual(solutions[0].total_xp, 10000)
        self.assertEqual(solutions[0].remark, "⚠ required monster(s) alone exceed budget — no reduction possible")

    def test_fill_path_no_optional(self) -> None:
        kb = self._mock_kb({"stat.zombie": ["cr:1-4"]}) # XP = 50
        required = [RequiredEntry(id="stat.zombie", count=20)]
        remaining = 1000
        
        solutions = _fill_candidates(required, remaining, [], kb)
        
        self.assertEqual(len(solutions), 1)
        self.assertEqual(solutions[0].entries[0].count, 40) # 20 original + 20 extra
        self.assertEqual(solutions[0].total_xp, 2000)

    def test_fill_path_with_optional(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4"], # XP 50
            "stat.wight": ["cr:3"], # XP 700
            "stat.ghast": ["cr:2"]  # XP 450
        })
        required = [RequiredEntry(id="stat.zombie", count=20)] # 1000 XP
        remaining = 2000
        optional = ["stat.wight", "stat.ghast"]
        
        import random
        random.seed(42) # Ensure reproducibility for tests
        solutions = _fill_candidates(required, remaining, optional, kb)
        
        self.assertTrue(len(solutions) <= 4)
        for sol in solutions:
            self.assertTrue(sol.total_xp > 1000)
            self.assertTrue(sol.total_xp <= 3000) # Should not exceed original 1000 + 2000 remaining

    def test_ranking_solutions(self) -> None:
        budget = 3000
        s1 = CandidateSolution(entries=[RequiredEntry("a", 1)], total_xp=2900) # diff 100, under
        s2 = CandidateSolution(entries=[RequiredEntry("b", 1)], total_xp=3100) # diff 100, over
        s3 = CandidateSolution(entries=[RequiredEntry("c", 1)], total_xp=2950) # diff 50, under
        
        ranked = _rank_solutions([s1, s2, s3], budget)
        
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0].total_xp, 2950)
        self.assertEqual(ranked[1].total_xp, 2900) # under wins tie
        self.assertEqual(ranked[2].total_xp, 3100)

    def test_compute_encounters_edge_cases(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4", "type:undead"], # XP 50
            "stat.dragon": ["cr:24", "type:dragon"], # XP 62000
            "stat.rat": ["cr:0", "type:beast"], # XP 10
            "stat.wight": ["cr:3", "type:undead"] # XP 700
        })
        
        # Empty everything
        res = compute_encounters([], [], "moderate", [5], [], kb)
        self.assertTrue("Error:" in res)
        
        # Strong allies: we still fill to adjusted budget (more opponents), no special remark
        res = compute_encounters([{"id": "stat.zombie", "count": 1}], [], "moderate", [1], ["20"], kb)
        self.assertIn("stat.zombie", res)
        self.assertNotIn("Error:", res)
        # Adjusted budget = 75 + 25000 = 25075, remaining 25025 → many zombies
        self.assertIn("[50", res)  # count 501 or similar
        
        # Invalid difficulty / PC levels
        res = compute_encounters([], ["stat.zombie"], "impossible", [1], [], kb)
        self.assertTrue("Error: Invalid difficulty 'impossible'" in res)
        
        # Budget too low for any candidate; emitting cheapest
        res = compute_encounters([], ["stat.dragon", "stat.wight"], "moderate", [1], [], kb) # Budget 75
        self.assertTrue("budget too low for any candidate; emitting cheapest" in res)
        self.assertTrue("stat.wight" in res) # should pick the cheapest among optionals
        
        # No optional candidates provided
        # Budget 3000. Required: 1 zombie (XP 50). Remaining 2950. No optionals.
        # But wait! If no optionals, it fills with MORE zombies!
        # So we need a situation where remaining > 0, NO optionals, and it CANNOT add more required.
        # It can't add more required if remaining < required XP.
        # E.g. Budget = 1000. Required: 1 wight (XP 700). Remaining 300. Optional = [].
        res = compute_encounters([{"id": "stat.wight", "count": 1}], [], "moderate", [5, 1], [], kb) # Budget 750+75=825. Remaining 125.
        self.assertTrue("no optional candidates provided; consider using kb with-tag" in res)
        
        # Too many enemies per ally
        # PCs: 4, so threshold is 4 * 4 = 16. If we have 20 zombies, it should warn.
        res = compute_encounters([{"id": "stat.zombie", "count": 20}], [], "moderate", [5, 5, 5, 5], [], kb)
        self.assertTrue("You have more than the recommended number of enemies per ally" in res)

    def test_compute_encounters_full_run(self) -> None:
        kb = self._mock_kb({
            "stat.zombie": ["cr:1-4", "type:undead"],
            "stat.wight": ["cr:3", "type:undead"],
        })
        required = [{"id": "stat.zombie", "count": 20}]
        optional = ["stat.wight"]
        pcs = [5, 5, 5, 5] # budget = 4 * 750 = 3000
        
        res = compute_encounters(required, optional, "moderate", pcs, [], kb)
        
        self.assertFalse("Error:" in res)
        self.assertTrue("stat.zombie" in res)
        self.assertTrue("stat.wight" in res)
        self.assertTrue("Option A" in res)
