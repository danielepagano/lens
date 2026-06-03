"""Tests for the image backend registry."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.image import registry as image_registry
from lens.core.image.api.a2e import A2EBackend
from lens.core.image.backend import ImageError


def _write_lens_toml(root: Path, body: str) -> None:
    (root / "lens.toml").write_text(body)


class LoadDescriptorTests(unittest.TestCase):
    def test_no_image_blocks_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(root, '[project]\nnarrative = "x"\n')
            with self.assertRaises(ImageError):
                image_registry.load_descriptor(root)

    def test_first_block_is_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_KEY"
aspect_ratios = ["1:1"]
sizes = ["1k"]
""",
            )
            descriptor = image_registry.load_descriptor(root)
            self.assertEqual(descriptor.id, "[default]")
            self.assertEqual(descriptor.api, "a2e")
            self.assertEqual(descriptor.aspect_ratios, ("1:1",))
            self.assertEqual(descriptor.sizes, ("1k",))
            self.assertEqual(descriptor.max_prompt_chars, 2000)
            same = image_registry.load_descriptor(root, "[default]")
            self.assertEqual(same.model, descriptor.model)

    def test_pick_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_KEY"
aspect_ratios = ["1:1"]
sizes = ["1k"]

[[image]]
id = "seed"
api = "a2e"
model = "seedream"
api_key_env = "FAKE_KEY"
aspect_ratios = ["16:9"]
sizes = ["1k"]
max_prompt_chars = 1500
""",
            )
            descriptor = image_registry.load_descriptor(root, "seed")
            self.assertEqual(descriptor.id, "seed")
            self.assertEqual(descriptor.model, "seedream")
            self.assertEqual(descriptor.aspect_ratios, ("16:9",))
            self.assertEqual(descriptor.max_prompt_chars, 1500)

    def test_unknown_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
id = "only"
api = "a2e"
model = "a2e"
api_key_env = "FAKE_KEY"
aspect_ratios = ["1:1"]
sizes = ["1k"]
""",
            )
            with self.assertRaises(ImageError):
                image_registry.load_descriptor(root, "nope")


class ResolveBackendTests(unittest.TestCase):
    def test_resolve_a2e(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_IMG_KEY"
aspect_ratios = ["1:1", "16:9"]
sizes = ["1k"]
""",
            )
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test_xxx"}):
                descriptor, backend = image_registry.resolve(root)
            self.assertEqual(descriptor.api, "a2e")
            self.assertTrue(descriptor.supports_reference_images)
            self.assertIsInstance(backend, A2EBackend)

    def test_resolve_missing_api_key_env_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "DEFINITELY_MISSING_VAR_XYZ"
aspect_ratios = ["1:1"]
sizes = ["1k"]
""",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DEFINITELY_MISSING_VAR_XYZ", None)
                with self.assertRaises(ImageError):
                    image_registry.resolve(root)

    def test_unknown_api_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[image]]
api = "future-provider"
model = "x"
api_key_env = "FAKE_IMG_KEY"
aspect_ratios = ["1:1"]
sizes = ["1k"]
""",
            )
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "k"}):
                with self.assertRaises(ImageError):
                    image_registry.resolve(root)


if __name__ == "__main__":
    unittest.main()
