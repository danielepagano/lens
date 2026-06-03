"""Re-export regression fixtures from lens.testing (see regression_fixtures.py)."""

from lens.testing.regression_fixtures import (
    setup_advance_minimal,
    setup_auto_compress_disabled_node,
    setup_auto_compress_low_threshold,
    setup_remember_section,
    setup_rpg_play_pins,
    setup_workflow_write_long,
)

__all__ = [
    "setup_advance_minimal",
    "setup_auto_compress_disabled_node",
    "setup_auto_compress_low_threshold",
    "setup_remember_section",
    "setup_rpg_play_pins",
    "setup_workflow_write_long",
]
