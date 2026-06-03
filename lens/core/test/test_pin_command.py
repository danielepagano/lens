from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.commands.pin import (
    coerce_param_pin_value,
    param_set,
    validate_ids,
    validate_param_scope,
    var_set,
    var_value_to_parts,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.test.test_pinning import init_git_repo, make_pin_test_project


class TestPinCommandValidateIds(unittest.TestCase):
    def test_allows_linked_suffix_plus(self) -> None:
        validate_ids(["person.amy+"])

    def test_allows_linked_suffix_double_plus(self) -> None:
        validate_ids(["place.market++"])

    def test_rejects_triple_plus_suffix(self) -> None:
        with self.assertRaises(LensException):
            validate_ids(["person.amy+++"])


class TestPinCommandParamScope(unittest.TestCase):
    def test_global_scope(self) -> None:
        self.assertEqual(validate_param_scope("global"), "global")

    def test_operator_slug(self) -> None:
        self.assertEqual(validate_param_scope("write"), "write")

    def test_rejects_invalid_scope(self) -> None:
        with self.assertRaises(LensException):
            validate_param_scope("bad scope")


class TestVarValueToParts(unittest.TestCase):
    def test_bool_to_lowercase_words(self) -> None:
        self.assertEqual(var_value_to_parts(True), ["true"])
        self.assertEqual(var_value_to_parts(False), ["false"])


class TestCoerceParamPinValue(unittest.TestCase):
    def test_bool_and_number(self) -> None:
        self.assertIs(coerce_param_pin_value("true"), True)
        self.assertIs(coerce_param_pin_value("FALSE"), False)
        self.assertEqual(coerce_param_pin_value("42"), 42)
        self.assertEqual(coerce_param_pin_value("1.5"), 1.5)


class TestVarParamCommandIntegration(unittest.TestCase):
    def test_var_set_writes_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            session = ProjectSession(root, root)
            _, _path = var_set(session, "mood", ["dark", "and", "stormy"], None, None)
            text = node.md_path().read_text()
            self.assertIn("dark and stormy", text)

    def test_param_set_coerces_bool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            session = ProjectSession(root, root)
            _, _path = param_set(
                session, "write", "reasoning", ["true"], None, None
            )
            text = node.md_path().read_text()
            self.assertIn("reasoning: true", text)

