"""Unit tests for chain support: ChainSpec, LLM folding, chain execution."""

from __future__ import annotations

import unittest

from lens.core.chain import ChainSpec


class TestChainSpec(unittest.TestCase):
    def test_from_dict_none(self) -> None:
        self.assertIsNone(ChainSpec.from_dict(None))
        self.assertIsNone(ChainSpec.from_dict({}))

    def test_from_dict_requires_name(self) -> None:
        self.assertIsNone(ChainSpec.from_dict({"arguments": {}}))
        self.assertIsNone(ChainSpec.from_dict({"name": "", "arguments": {}}))

    def test_from_dict_requires_arguments(self) -> None:
        spec = ChainSpec.from_dict({"name": "write", "arguments": {"prompt": "x"}})
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.name, "write")
        self.assertEqual(spec.arguments.get("prompt"), "x")
        self.assertIsNone(spec.id)

    def test_from_dict_with_id(self) -> None:
        spec = ChainSpec.from_dict({
            "name": "play",
            "id": "call_123",
            "arguments": {"prompt": "arrive"},
        })
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.id, "call_123")
