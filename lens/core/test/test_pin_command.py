from __future__ import annotations

import unittest

from lens.core.commands.pin import validate_ids
from lens.core.exceptions import LensException


class TestPinCommandValidateIds(unittest.TestCase):
    def test_allows_linked_suffix_plus(self) -> None:
        validate_ids(["person.amy+"])

    def test_allows_linked_suffix_double_plus(self) -> None:
        validate_ids(["place.market++"])

    def test_rejects_triple_plus_suffix(self) -> None:
        with self.assertRaises(LensException):
            validate_ids(["person.amy+++"])

