"""RPG dataset: operators scoped to the ``rpg`` core dataset."""

from lens.core.dataset_config import register_dataset_config

register_dataset_config("rpg", {"kb_dice_rolling": "expressions"})
