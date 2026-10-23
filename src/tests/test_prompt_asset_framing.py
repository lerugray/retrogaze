"""
Asset-framing tests for the FLUX prompt builder (Ricky, 2026-09-11).

Reported bug: with asset_type=item and era=late, the generator produced
characters even though "Item" was selected ("robe" was the reported
prompt). Root cause was the era style anchor, not the item template: the
NES late ``style_ref`` reads "Detailed armor, expressive face, visible
shading." and was substituted into the item prompt too, directly
contradicting its "no character, no hands, no person" framing, so FLUX
drew the character the style line asked for.

Fix: eras may declare a subject-neutral ``object_ref``; non-character
asset types use it instead of ``style_ref``. These tests pin that
contract across every console and era so a future style_ref edit cannot
silently reintroduce character anatomy into item/tile/UI prompts.

No network: ``build_prompt`` is pure string assembly.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RETROGAZE_MOCK", "1")

import pytest

from retrogaze.prompts import _era_style_ref, build_prompt
from retrogaze.console_prompt_data import _REGISTRY, get_prompt_data


# One entry per distinct ConsolePromptData (aliases share an object).
_CONSOLES: dict[str, object] = {}
for _alias, _data in _REGISTRY.items():
    _CONSOLES.setdefault(_data.name, _data)

_CONSOLE_ERAS = sorted(
    (name, era) for name, data in _CONSOLES.items() for era in data.eras
)

# Framing that must appear for an item generation.
_ITEM_FRAMING = (
    "Single large pixel art game item",
    "No character, no hands, no person",
)

# Wording that describes a living subject. None of it may appear in a
# non-character prompt (compared case-insensitively).
_CHARACTER_FRAMING = (
    "expressive face",
    "detailed armor",
    "expressive character design",
    "large character sprites",
    "expressive animation frames",
    "both legs visible",
    "both arms visible",
    "full body with all limbs",
    "single pixel art character sprite",
    "chunky proportions, large head, short body",
)

_DESCRIPTIONS = ("robe", "sword", "potion")
_NON_CHARACTER_TYPES = ("item", "ui_element", "ui_frame", "tile", "tileset")


@pytest.mark.parametrize("console,era", _CONSOLE_ERAS)
@pytest.mark.parametrize("description", _DESCRIPTIONS)
def test_item_prompt_carries_item_framing_not_character_framing(
    console, era, description
):
    prompt = build_prompt(
        description=description, asset_type="item", era=era, console=console
    )["prompt"]
    lowered = prompt.lower()
    for marker in _ITEM_FRAMING:
        assert marker.lower() in lowered, (
            f"{console}/{era} item prompt lost item framing {marker!r}"
        )
    for marker in _CHARACTER_FRAMING:
        assert marker not in lowered, (
            f"{console}/{era} item prompt leaked character framing {marker!r}: {prompt}"
        )


@pytest.mark.parametrize("console,era", _CONSOLE_ERAS)
@pytest.mark.parametrize("asset_type", _NON_CHARACTER_TYPES)
def test_non_character_prompts_never_request_anatomy(console, era, asset_type):
    prompt = build_prompt(
        description="robe", asset_type=asset_type, era=era, console=console
    )["prompt"]
    lowered = prompt.lower()
    for marker in _CHARACTER_FRAMING:
        assert marker not in lowered, (
            f"{console}/{era}/{asset_type} prompt leaked {marker!r}: {prompt}"
        )


@pytest.mark.parametrize("console,era", _CONSOLE_ERAS)
def test_character_types_keep_the_full_style_anchor(console, era):
    """The subject-neutral split must not strip character prompts."""
    era_data = get_prompt_data(console).eras[era]
    if era_data.object_ref:
        # The era has a neutral ref, so the two must differ; character
        # types still get the character-flavoured anchor verbatim.
        assert _era_style_ref(era_data, "character") == era_data.style_ref
        assert _era_style_ref(era_data, "item") == era_data.object_ref
        assert era_data.object_ref != era_data.style_ref
    else:
        # No neutral ref needed; both paths use style_ref.
        assert _era_style_ref(era_data, "item") == era_data.style_ref


def test_nes_late_item_prompt_no_longer_mentions_faces_or_armor():
    """Regression pin for the exact reported case (item + late + robe)."""
    prompt = build_prompt(
        description="robe", asset_type="item", era="late", console="nes"
    )["prompt"]
    assert "expressive face" not in prompt.lower()
    assert "detailed armor" not in prompt.lower()
    assert "Single large pixel art game item" in prompt
    assert "Subject: robe." in prompt
