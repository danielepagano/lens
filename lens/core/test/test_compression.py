"""Unit tests for lens.core.compression."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.compression import (
    Aggressiveness,
    CompressConfig,
    auto_compress_enabled,
    get_last_compress_size,
    get_visible_text,
    measure_visible_bytes,
    should_trigger,
)


class TestCompressConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = CompressConfig()
        self.assertEqual(cfg.sm, 15_000)
        self.assertEqual(cfg.m, 40_000)
        self.assertEqual(cfg.lg, 80_000)
        self.assertEqual(cfg.xl, 150_000)
        self.assertTrue(cfg.auto_compress)

    def test_from_project_no_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertEqual(cfg, CompressConfig())

    def test_from_project_no_compress_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text('[project]\nnarrative = "x"\n')
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertEqual(cfg, CompressConfig())

    def test_from_project_partial_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text(
                '[project]\nnarrative = "x"\n[compress]\nm = 20000\nauto_compress = true\n'
            )
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertEqual(cfg.m, 20_000)
        self.assertTrue(cfg.auto_compress)
        self.assertEqual(cfg.sm, 15_000)  # default

    def test_from_project_non_bool_auto_compress_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text(
                '[project]\nnarrative = "x"\n[compress]\nauto_compress = "false"\n'
            )
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertTrue(cfg.auto_compress)

    def test_from_project_mode_string_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text(
                '[project]\nnarrative = "x"\n[compress]\nmode = "off"\n'
            )
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertTrue(cfg.auto_compress)

    def test_from_project_all_fields(self) -> None:
        toml = (
            '[project]\nnarrative = "x"\n'
            "[compress]\n"
            "sm = 1000\nm = 5000\nl = 10000\nxl = 20000\nauto_compress = false\nunit = \"bytes\"\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text(toml)
            cfg = CompressConfig.from_project(Path(tmp))
        self.assertEqual(cfg.sm, 1000)
        self.assertEqual(cfg.m, 5000)
        self.assertEqual(cfg.lg, 10000)  # TOML "l" maps to Python "lg"
        self.assertEqual(cfg.xl, 20000)
        self.assertFalse(cfg.auto_compress)


class TestGetLastCompressSize(unittest.TestCase):
    def test_missing_key(self) -> None:
        self.assertIsNone(get_last_compress_size({}))

    def test_compress_not_dict(self) -> None:
        self.assertIsNone(get_last_compress_size({"compress": "string"}))

    def test_last_size_present(self) -> None:
        self.assertEqual(get_last_compress_size({"compress": {"last_size": 1234}}), 1234)

    def test_last_size_missing(self) -> None:
        self.assertIsNone(get_last_compress_size({"compress": {"other": "value"}}))

    def test_last_size_not_int(self) -> None:
        self.assertIsNone(get_last_compress_size({"compress": {"last_size": "big"}}))


class TestAutoCompressEnabled(unittest.TestCase):
    cfg = CompressConfig(auto_compress=True)

    def test_no_override(self) -> None:
        self.assertTrue(auto_compress_enabled(self.cfg, {}))

    def test_per_node_override_off(self) -> None:
        fm = {"compress": {"auto_compress": False}}
        self.assertFalse(auto_compress_enabled(self.cfg, fm))

    def test_per_node_non_bool_ignored(self) -> None:
        fm = {"compress": {"auto_compress": "no"}}
        self.assertTrue(auto_compress_enabled(self.cfg, fm))

    def test_per_node_unknown_keys_use_project(self) -> None:
        fm = {"compress": {"mode": "off"}}
        self.assertFalse(
            auto_compress_enabled(CompressConfig(auto_compress=False), fm)
        )

    def test_compress_not_dict(self) -> None:
        fm = {"compress": "something"}
        self.assertTrue(auto_compress_enabled(self.cfg, fm))


class TestShouldTrigger(unittest.TestCase):
    cfg = CompressConfig(sm=1000, m=4000, lg=8000, xl=15000)

    # --- below threshold ---

    def test_below_m_no_trigger(self) -> None:
        self.assertIsNone(should_trigger(3999, None, self.cfg))

    def test_exactly_m_minus_1_no_trigger(self) -> None:
        self.assertIsNone(should_trigger(self.cfg.m - 1, None, self.cfg))

    # --- at m boundary: LOW ---

    def test_at_m_no_last_size_low(self) -> None:
        self.assertEqual(should_trigger(self.cfg.m, None, self.cfg), Aggressiveness.LOW)

    def test_at_m_with_sufficient_delta_low(self) -> None:
        # last = m - sm → delta = sm → ok
        self.assertEqual(
            should_trigger(self.cfg.m, self.cfg.m - self.cfg.sm, self.cfg),
            Aggressiveness.LOW,
        )

    def test_at_m_insufficient_delta_no_trigger(self) -> None:
        # last = m - sm + 1 → delta = sm - 1 → not ok
        self.assertIsNone(should_trigger(self.cfg.m, self.cfg.m - self.cfg.sm + 1, self.cfg))

    # --- l boundary: MEDIUM ---

    def test_at_l_plus_1_medium(self) -> None:
        self.assertEqual(
            should_trigger(self.cfg.lg + 1, None, self.cfg), Aggressiveness.MEDIUM
        )

    def test_at_xl_medium(self) -> None:
        self.assertEqual(
            should_trigger(self.cfg.xl, None, self.cfg), Aggressiveness.MEDIUM
        )

    def test_medium_insufficient_delta_no_trigger(self) -> None:
        self.assertIsNone(
            should_trigger(self.cfg.lg + 1, self.cfg.lg + 1, self.cfg)
        )

    # --- above xl: HIGH (no delta check) ---

    def test_above_xl_high(self) -> None:
        self.assertEqual(
            should_trigger(self.cfg.xl + 1, None, self.cfg), Aggressiveness.HIGH
        )

    def test_above_xl_high_even_same_last_size(self) -> None:
        # delta check is skipped for HIGH
        self.assertEqual(
            should_trigger(self.cfg.xl + 1, self.cfg.xl + 1, self.cfg),
            Aggressiveness.HIGH,
        )


class TestVisibleBytes(unittest.TestCase):
    def test_strips_annotations(self) -> None:
        text = "[write:op1]: #\nhello world\n[/write:op1]: #\n"
        visible = get_visible_text(text)
        self.assertNotIn("[write:op1]: #", visible)
        self.assertIn("hello world", visible)

    def test_measure_bytes(self) -> None:
        s = "abc"
        self.assertEqual(measure_visible_bytes(s), 3)
        emoji = "😀"
        self.assertEqual(measure_visible_bytes(emoji), 4)
