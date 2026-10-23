"""Tests for ConsolePromptData system and multi-console prompt engineering."""

import pytest

from retrogaze.console_prompt_data import (
    ConsolePromptData,
    EraPromptData,
    get_prompt_data,
)


# --- Helpers ---

REQUIRED_ERA_FIELDS = [
    "label", "year_range", "reference_games",
    "style_ref", "tile_ref", "era_hints", "outline_hint",
]

# Dicts keyed by era
ERA_KEYED_DICTS = [
    "palette_rules", "color_theory_rules", "tool_configs",
    "few_shot_examples",
]

# Dicts keyed by view type (side, front, top-down, 3/4)
VIEW_KEYED_DICTS = ["view_rules"]


def _assert_valid_prompt_data(pd: ConsolePromptData):
    """Verify a ConsolePromptData has all required fields populated."""
    assert pd.name
    assert pd.display_name
    assert pd.default_era in pd.eras, (
        f"{pd.name}: default_era '{pd.default_era}' not in eras {list(pd.eras.keys())}"
    )
    assert len(pd.eras) >= 1

    # Every era must have all EraPromptData fields non-empty
    for era_key, era in pd.eras.items():
        for field in REQUIRED_ERA_FIELDS:
            val = getattr(era, field)
            assert val and isinstance(val, str), (
                f"{pd.name}.eras[{era_key!r}].{field} is empty or missing"
            )

    # Era-keyed dicts must have entries for every era
    for dict_name in ERA_KEYED_DICTS:
        d = getattr(pd, dict_name)
        assert isinstance(d, dict), f"{pd.name}.{dict_name} is not a dict"
        for era_key in pd.eras:
            assert era_key in d, (
                f"{pd.name}.{dict_name} missing era key {era_key!r}"
            )
            assert d[era_key], (
                f"{pd.name}.{dict_name}[{era_key!r}] is empty"
            )

    # View-keyed dicts must have at least side and front views
    for dict_name in VIEW_KEYED_DICTS:
        d = getattr(pd, dict_name)
        assert isinstance(d, dict), f"{pd.name}.{dict_name} is not a dict"
        for view_key in ("side", "front"):
            assert view_key in d, (
                f"{pd.name}.{dict_name} missing view key {view_key!r}"
            )

    # terrain_color_hints must be a list
    assert isinstance(pd.terrain_color_hints, list)


# --- Game Boy DMG ---


class TestGameBoyDMG:
    def test_get_prompt_data(self):
        pd = get_prompt_data("gb_dmg")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "gb_dmg"
        assert pd.display_name == "Game Boy"

    def test_eras_populated(self):
        pd = get_prompt_data("gb_dmg")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        dmg = get_prompt_data("gb_dmg")
        assert get_prompt_data("gb") is dmg
        assert get_prompt_data("game_boy") is dmg

    def test_default_era(self):
        pd = get_prompt_data("gb_dmg")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("gb_dmg")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("gb_dmg")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"


# --- Game Boy Pocket ---


class TestGameBoyPocket:
    def test_get_prompt_data(self):
        pd = get_prompt_data("gb_pocket")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "gb_pocket"
        assert pd.display_name == "Game Boy Pocket"

    def test_eras_populated(self):
        pd = get_prompt_data("gb_pocket")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_default_era(self):
        pd = get_prompt_data("gb_pocket")
        assert pd.default_era == "mid"

    def test_few_shot_uses_grayscale_hex(self):
        """Pocket examples should use true grayscale, not DMG green."""
        pd = get_prompt_data("gb_pocket")
        for era_key, example in pd.few_shot_examples.items():
            assert "#000000" in example or "#555555" in example, (
                f"Pocket few_shot[{era_key!r}] should reference grayscale hex values"
            )
            assert "#0F380F" not in example, (
                f"Pocket few_shot[{era_key!r}] should NOT use DMG green hex"
            )

    def test_pocket_is_distinct_from_dmg(self):
        dmg = get_prompt_data("gb_dmg")
        pocket = get_prompt_data("gb_pocket")
        assert dmg is not pocket
        assert dmg.name != pocket.name
        # They share era definitions but have different few-shot examples
        assert dmg.few_shot_examples is not pocket.few_shot_examples


# --- Commodore 64 ---


class TestCommodore64:
    def test_get_prompt_data(self):
        pd = get_prompt_data("c64")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "c64"
        assert pd.display_name == "Commodore 64"

    def test_eras_populated(self):
        pd = get_prompt_data("c64")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        c64 = get_prompt_data("c64")
        assert get_prompt_data("c64_hires") is c64
        assert get_prompt_data("commodore_64") is c64

    def test_default_era(self):
        pd = get_prompt_data("c64")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("c64")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_few_shot_uses_c64_palette_hex(self):
        """C64 examples should reference actual C64 VICE palette hex values."""
        pd = get_prompt_data("c64")
        for era_key, example in pd.few_shot_examples.items():
            assert "#000000" in example or "#444444" in example or "#959595" in example, (
                f"C64 few_shot[{era_key!r}] should reference C64 palette hex values"
            )

    def test_palette_rules_reference_gray_ramp(self):
        """Mid and late palette rules should mention the C64 gray ramp."""
        pd = get_prompt_data("c64")
        for era_key in ("mid", "late"):
            assert "#444444" in pd.palette_rules[era_key] or "gray" in pd.palette_rules[era_key].lower(), (
                f"C64 palette_rules[{era_key!r}] should reference gray shading"
            )

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("c64")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"


# --- Game Boy Color ---


class TestGameBoyColor:
    def test_get_prompt_data(self):
        pd = get_prompt_data("gbc")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "gbc"
        assert pd.display_name == "Game Boy Color"

    def test_eras_populated(self):
        pd = get_prompt_data("gbc")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        gbc = get_prompt_data("gbc")
        assert get_prompt_data("game_boy_color") is gbc

    def test_default_era(self):
        pd = get_prompt_data("gbc")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("gbc")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_few_shot_uses_15bit_rgb_hex(self):
        """GBC examples should use 15-bit RGB hex values, not DMG green or grayscale."""
        pd = get_prompt_data("gbc")
        for era_key, example in pd.few_shot_examples.items():
            # Should contain hex color references
            assert "#" in example, (
                f"GBC few_shot[{era_key!r}] should contain hex color values"
            )
            # Should NOT use DMG green palette
            assert "#0F380F" not in example, (
                f"GBC few_shot[{era_key!r}] should NOT use DMG green hex"
            )
            # Should NOT use pure grayscale (GB Pocket style)
            assert "#555555" not in example, (
                f"GBC few_shot[{era_key!r}] should NOT use pure grayscale hex"
            )
            assert "#AAAAAA" not in example, (
                f"GBC few_shot[{era_key!r}] should NOT use pure grayscale hex"
            )

    def test_palette_rules_reference_per_tile(self):
        """GBC palette rules should mention per-tile palette assignment."""
        pd = get_prompt_data("gbc")
        for era_key, rules in pd.palette_rules.items():
            assert "per-tile" in rules.lower() or "per tile" in rules.lower(), (
                f"GBC palette_rules[{era_key!r}] should reference per-tile palette assignment"
            )

    def test_palette_rules_reference_4_colors_per_tile(self):
        """GBC palette rules should mention the 4-colors-per-tile constraint."""
        pd = get_prompt_data("gbc")
        for era_key, rules in pd.palette_rules.items():
            assert "4 color" in rules.lower() or "4-color" in rules.lower() or "exactly 4" in rules.lower(), (
                f"GBC palette_rules[{era_key!r}] should reference 4 colors per tile"
            )

    def test_color_theory_references_value_first(self):
        """Early era color theory should mention value-first design."""
        pd = get_prompt_data("gbc")
        assert "value" in pd.color_theory_rules["early"].lower(), (
            "GBC early color_theory should reference value-first design"
        )

    def test_color_theory_references_palette_families(self):
        """Mid and late era color theory should mention palette families."""
        pd = get_prompt_data("gbc")
        for era_key in ("mid", "late"):
            assert "palette famil" in pd.color_theory_rules[era_key].lower(), (
                f"GBC color_theory[{era_key!r}] should reference palette families"
            )

    def test_color_theory_references_cross_tile_shading(self):
        """Mid and late era should mention cross-tile shading."""
        pd = get_prompt_data("gbc")
        for era_key in ("mid", "late"):
            assert "cross-tile" in pd.color_theory_rules[era_key].lower(), (
                f"GBC color_theory[{era_key!r}] should reference cross-tile shading"
            )

    def test_color_theory_references_colorful_but_chunky(self):
        """Color theory should mention the GBC's distinctive aesthetic."""
        pd = get_prompt_data("gbc")
        # At least one era should reference this
        found = any(
            "colorful but chunky" in rules.lower()
            for rules in pd.color_theory_rules.values()
        )
        assert found, "GBC color_theory should reference 'colorful but chunky' aesthetic"

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("gbc")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"

    def test_gbc_is_distinct_from_dmg(self):
        """GBC should be a completely separate entry from DMG."""
        dmg = get_prompt_data("gb_dmg")
        gbc = get_prompt_data("gbc")
        assert dmg is not gbc
        assert dmg.name != gbc.name
        assert dmg.display_name != gbc.display_name
        # Different eras (different reference games, year ranges)
        assert gbc.eras["early"].year_range != dmg.eras["early"].year_range
        # Different few-shot examples
        assert gbc.few_shot_examples is not dmg.few_shot_examples

    def test_era_reference_games(self):
        """Each era should reference appropriate GBC games."""
        pd = get_prompt_data("gbc")
        assert "Pokemon" in pd.eras["early"].reference_games or "Dragon Quest" in pd.eras["early"].reference_games
        assert "Zelda" in pd.eras["mid"].reference_games or "Oracle" in pd.eras["mid"].reference_games or "Wario" in pd.eras["mid"].reference_games
        assert "Shantae" in pd.eras["late"].reference_games


# --- SNES ---


class TestSNES:
    def test_get_prompt_data(self):
        pd = get_prompt_data("snes")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "snes"
        assert pd.display_name == "Super Nintendo"

    def test_eras_populated(self):
        pd = get_prompt_data("snes")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        snes = get_prompt_data("snes")
        assert get_prompt_data("super_nintendo") is snes

    def test_default_era(self):
        pd = get_prompt_data("snes")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("snes")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_few_shot_uses_15bit_rgb_hex(self):
        """SNES examples should use 15-bit RGB hex values, not NES fixed palette."""
        pd = get_prompt_data("snes")
        for era_key, example in pd.few_shot_examples.items():
            # Should contain hex color references
            assert "#" in example, (
                f"SNES few_shot[{era_key!r}] should contain hex color values"
            )
            # Should NOT use NES fixed palette colors
            assert "#0F380F" not in example, (
                f"SNES few_shot[{era_key!r}] should NOT use DMG green hex"
            )

    def test_palette_rules_reference_8_plus_8(self):
        """SNES palette rules should reference the 8+8 palette architecture."""
        pd = get_prompt_data("snes")
        for era_key, rules in pd.palette_rules.items():
            found = (
                "8 bg" in rules.lower()
                or "8 palettes for background" in rules.lower()
                or "8+8" in rules.lower()
                or "separate" in rules.lower()
            )
            assert found, (
                f"SNES palette_rules[{era_key!r}] should reference 8+8 palette system "
                f"or separate BG/sprite pools"
            )

    def test_palette_rules_reference_hue_families(self):
        """Mid and late palette rules should mention hue families."""
        pd = get_prompt_data("snes")
        for era_key in ("mid", "late"):
            assert "hue famil" in pd.palette_rules[era_key].lower(), (
                f"SNES palette_rules[{era_key!r}] should reference hue families"
            )

    def test_color_theory_references_hue_shifting(self):
        """Mid and late color theory should explain hue shifting."""
        pd = get_prompt_data("snes")
        for era_key in ("mid", "late"):
            assert "hue shift" in pd.color_theory_rules[era_key].lower(), (
                f"SNES color_theory[{era_key!r}] should reference hue shifting"
            )

    def test_color_theory_references_material_differentiation(self):
        """Mid and late color theory should cover material differentiation."""
        pd = get_prompt_data("snes")
        for era_key in ("mid", "late"):
            rules = pd.color_theory_rules[era_key].lower()
            assert "metal" in rules, (
                f"SNES color_theory[{era_key!r}] should mention metal material"
            )
            assert "fabric" in rules or "matte" in rules, (
                f"SNES color_theory[{era_key!r}] should mention fabric/matte material"
            )
            assert "skin" in rules, (
                f"SNES color_theory[{era_key!r}] should mention skin tones"
            )

    def test_color_theory_references_atmospheric_palette(self):
        """Mid and late color theory should cover atmospheric palette design."""
        pd = get_prompt_data("snes")
        for era_key in ("mid", "late"):
            rules = pd.color_theory_rules[era_key].lower()
            assert "atmospher" in rules, (
                f"SNES color_theory[{era_key!r}] should reference atmospheric "
                f"palette design"
            )

    def test_late_color_theory_references_chrono_trigger(self):
        """Late era color theory should reference Chrono Trigger techniques."""
        pd = get_prompt_data("snes")
        rules = pd.color_theory_rules["late"].lower()
        assert "chrono trigger" in rules, (
            "SNES late color_theory should reference Chrono Trigger"
        )

    def test_late_color_theory_references_super_metroid(self):
        """Late era color theory should reference Super Metroid techniques."""
        pd = get_prompt_data("snes")
        rules = pd.color_theory_rules["late"].lower()
        assert "super metroid" in rules, (
            "SNES late color_theory should reference Super Metroid"
        )

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("snes")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"

    def test_snes_is_distinct_from_nes(self):
        """SNES should be a completely separate entry from NES."""
        nes = get_prompt_data("nes")
        snes = get_prompt_data("snes")
        assert nes is not snes
        assert nes.name != snes.name
        assert nes.display_name != snes.display_name
        assert snes.few_shot_examples is not nes.few_shot_examples
        # SNES has different era set (no 'retro')
        assert "retro" not in snes.eras

    def test_era_reference_games(self):
        """Each era should reference appropriate SNES games."""
        pd = get_prompt_data("snes")
        assert "Super Mario World" in pd.eras["early"].reference_games
        assert "A Link to the Past" in pd.eras["early"].reference_games
        assert "Super Metroid" in pd.eras["mid"].reference_games
        assert "Final Fantasy VI" in pd.eras["mid"].reference_games
        assert "Chrono Trigger" in pd.eras["late"].reference_games

    def test_era_year_ranges(self):
        """Each era should cover the correct year range."""
        pd = get_prompt_data("snes")
        assert "1990" in pd.eras["early"].year_range
        assert "1992" in pd.eras["early"].year_range
        assert "1993" in pd.eras["mid"].year_range
        assert "1994" in pd.eras["mid"].year_range
        assert "1995" in pd.eras["late"].year_range
        assert "1997" in pd.eras["late"].year_range


# --- PC Engine ---


class TestPCEngine:
    def test_get_prompt_data(self):
        pd = get_prompt_data("pc_engine")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "pc_engine"
        assert pd.display_name == "PC Engine"

    def test_eras_populated(self):
        pd = get_prompt_data("pc_engine")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        pce = get_prompt_data("pc_engine")
        assert get_prompt_data("turbografx") is pce
        assert get_prompt_data("turbografx_16") is pce

    def test_default_era(self):
        pd = get_prompt_data("pc_engine")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("pc_engine")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_terrain_hints_include_space(self):
        """PC Engine is a shmup platform — terrain hints should include space/starfield."""
        pd = get_prompt_data("pc_engine")
        space_keywords = set()
        for keywords, hint in pd.terrain_color_hints:
            space_keywords.update(keywords)
        assert "space" in space_keywords or "starfield" in space_keywords, (
            "PC Engine terrain hints should include space/starfield for shmup backgrounds"
        )

    def test_few_shot_uses_9bit_rgb_hex(self):
        """PCE examples should use 9-bit RGB hex values, not NES fixed palette."""
        pd = get_prompt_data("pc_engine")
        for era_key, example in pd.few_shot_examples.items():
            assert "#" in example, (
                f"PCE few_shot[{era_key!r}] should contain hex color values"
            )
            # Should NOT use NES fixed palette colors
            assert "#0F380F" not in example, (
                f"PCE few_shot[{era_key!r}] should NOT use DMG green hex"
            )
            # Should NOT use pure black outlines in mid/late
            if era_key in ("mid", "late"):
                assert "#000000" not in example, (
                    f"PCE few_shot[{era_key!r}] should use chromatic dark outline, not pure black"
                )

    def test_few_shot_late_uses_all_15_slots(self):
        """Late era few-shot should demonstrate using all 15 palette slots."""
        pd = get_prompt_data("pc_engine")
        example = pd.few_shot_examples["late"]
        assert "15" in example, (
            "PCE late few_shot should reference using all 15 palette slots"
        )

    def test_palette_rules_reference_16_sprite_palettes(self):
        """Palette rules should reference the 16+16 palette architecture."""
        pd = get_prompt_data("pc_engine")
        for era_key, rules in pd.palette_rules.items():
            assert "16" in rules, (
                f"PCE palette_rules[{era_key!r}] should reference 16 sprite palettes"
            )

    def test_palette_rules_reference_9bit_rgb(self):
        """Palette rules should mention 9-bit RGB / 512 colors."""
        pd = get_prompt_data("pc_engine")
        for era_key, rules in pd.palette_rules.items():
            assert "9-bit" in rules or "512" in rules, (
                f"PCE palette_rules[{era_key!r}] should reference 9-bit RGB or 512 colors"
            )

    def test_palette_rules_reference_single_bg_plane(self):
        """Palette rules should mention the single background plane constraint."""
        pd = get_prompt_data("pc_engine")
        # At least early era should mention single BG plane
        assert "single" in pd.palette_rules["early"].lower() and "plane" in pd.palette_rules["early"].lower(), (
            "PCE early palette_rules should reference single background plane"
        )

    def test_palette_rules_late_references_15_color_gradient(self):
        """Late palette rules should describe multi-step gradient shading with 15 colors."""
        pd = get_prompt_data("pc_engine")
        rules = pd.palette_rules["late"]
        assert "gradient" in rules.lower() or "body_deep_shadow" in rules.lower(), (
            "PCE late palette_rules should describe gradient shading with 15 colors"
        )

    def test_color_theory_references_hue_shifting(self):
        """Late color theory should explain hue shifting."""
        pd = get_prompt_data("pc_engine")
        assert "hue shift" in pd.color_theory_rules["late"].lower(), (
            "PCE late color_theory should reference hue shifting"
        )

    def test_color_theory_references_material_differentiation(self):
        """Late color theory should cover material differentiation."""
        pd = get_prompt_data("pc_engine")
        rules = pd.color_theory_rules["late"].lower()
        assert "metal" in rules, "PCE late color_theory should mention metal material"
        assert "fabric" in rules, "PCE late color_theory should mention fabric material"
        assert "skin" in rules, "PCE late color_theory should mention skin tones"

    def test_color_theory_references_dense_single_layer(self):
        """Color theory should cover dense single-layer BG composition."""
        pd = get_prompt_data("pc_engine")
        for era_key in ("mid", "late"):
            rules = pd.color_theory_rules[era_key].lower()
            assert "single" in rules and ("layer" in rules or "plane" in rules), (
                f"PCE color_theory[{era_key!r}] should reference single-layer BG composition"
            )

    def test_color_theory_mid_references_weapon_contrast(self):
        """Mid era color theory should mention weapon/projectile contrast palettes."""
        pd = get_prompt_data("pc_engine")
        rules = pd.color_theory_rules["mid"].lower()
        assert "projectile" in rules or "weapon" in rules, (
            "PCE mid color_theory should reference weapon/projectile contrast palettes"
        )

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("pc_engine")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"

    def test_pce_is_distinct_from_nes(self):
        """PC Engine should be a completely separate entry from NES."""
        nes = get_prompt_data("nes")
        pce = get_prompt_data("pc_engine")
        assert nes is not pce
        assert nes.name != pce.name
        assert nes.display_name != pce.display_name
        assert pce.few_shot_examples is not nes.few_shot_examples
        # PCE has no 'retro' era
        assert "retro" not in pce.eras

    def test_era_reference_games(self):
        """Each era should reference appropriate PC Engine games."""
        pd = get_prompt_data("pc_engine")
        assert "R-Type" in pd.eras["early"].reference_games
        assert "Bonk" in pd.eras["early"].reference_games
        assert "Soldier Blade" in pd.eras["mid"].reference_games or "Blazing Lazers" in pd.eras["mid"].reference_games
        assert "Rondo of Blood" in pd.eras["late"].reference_games

    def test_era_year_ranges(self):
        """Each era should cover the correct year range."""
        pd = get_prompt_data("pc_engine")
        assert "1987" in pd.eras["early"].year_range
        assert "1989" in pd.eras["early"].year_range
        assert "1990" in pd.eras["mid"].year_range
        assert "1992" in pd.eras["mid"].year_range
        assert "1993" in pd.eras["late"].year_range
        assert "1994" in pd.eras["late"].year_range

    def test_era_hints_mention_16x16_minimum(self):
        """Early and mid era hints should mention the 16x16 minimum sprite size."""
        pd = get_prompt_data("pc_engine")
        for era_key in ("early", "mid"):
            era = pd.eras[era_key]
            assert "16x16" in era.era_hints, (
                f"PCE eras[{era_key!r}].era_hints should mention 16x16 minimum sprite size"
            )

    def test_few_shot_mid_sprite_size_at_least_32(self):
        """Mid and late era few-shot should use 32x32 sprite examples (not 16x16)."""
        pd = get_prompt_data("pc_engine")
        for era_key in ("mid", "late"):
            example = pd.few_shot_examples[era_key]
            assert "32x32" in example, (
                f"PCE few_shot[{era_key!r}] should use 32x32 sprite examples"
            )


# --- Sega Genesis ---


class TestGenesis:
    def test_get_prompt_data(self):
        pd = get_prompt_data("genesis")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "genesis"
        assert pd.display_name == "Sega Genesis"

    def test_eras_populated(self):
        pd = get_prompt_data("genesis")
        assert set(pd.eras.keys()) == {"early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_aliases(self):
        genesis = get_prompt_data("genesis")
        assert get_prompt_data("mega_drive") is genesis

    def test_default_era(self):
        pd = get_prompt_data("genesis")
        assert pd.default_era == "mid"

    def test_terrain_hints_nonempty(self):
        pd = get_prompt_data("genesis")
        assert len(pd.terrain_color_hints) > 0
        for keywords, hint in pd.terrain_color_hints:
            assert len(keywords) > 0
            assert len(hint) > 0

    def test_terrain_hints_include_metal(self):
        """Genesis terrain hints should include metal/factory for Vectorman-style environments."""
        pd = get_prompt_data("genesis")
        all_keywords = set()
        for keywords, hint in pd.terrain_color_hints:
            all_keywords.update(keywords)
        assert "metal" in all_keywords or "factory" in all_keywords, (
            "Genesis terrain hints should include metal/factory keywords"
        )

    def test_few_shot_uses_9bit_rgb_hex(self):
        """Genesis examples should use 9-bit RGB hex values (quantized to 8 steps per channel)."""
        pd = get_prompt_data("genesis")
        for era_key, example in pd.few_shot_examples.items():
            assert "#" in example, (
                f"Genesis few_shot[{era_key!r}] should contain hex color values"
            )

    def test_few_shot_mid_uses_chromatic_outline(self):
        """Mid and late era few-shot should NOT use pure black (#000000) outline."""
        pd = get_prompt_data("genesis")
        for era_key in ("mid", "late"):
            example = pd.few_shot_examples[era_key]
            # The outline color in mid/late should be a dark chromatic color, not #000000
            assert "outline" in example.lower()
            # First palette entry should not be #000000
            lines = example.split("\n")
            palette_line = [l for l in lines if "Palette:" in l][0]
            assert "#000000" not in palette_line, (
                f"Genesis few_shot[{era_key!r}] should use chromatic dark outline, not pure black"
            )

    def test_few_shot_early_uses_black_outline(self):
        """Early era few-shot SHOULD use pure black outline (NES-inherited)."""
        pd = get_prompt_data("genesis")
        example = pd.few_shot_examples["early"]
        assert "#000000" in example, (
            "Genesis early few_shot should use black outline (NES-inherited convention)"
        )

    def test_palette_rules_reference_9bit_rgb(self):
        """Palette rules should mention 9-bit RGB / 512 colors."""
        pd = get_prompt_data("genesis")
        for era_key, rules in pd.palette_rules.items():
            assert "9-bit" in rules or "512" in rules, (
                f"Genesis palette_rules[{era_key!r}] should reference 9-bit RGB or 512 colors"
            )

    def test_palette_rules_reference_4_palettes(self):
        """Palette rules should mention the 4 palettes x 16 colors system."""
        pd = get_prompt_data("genesis")
        for era_key, rules in pd.palette_rules.items():
            assert "4 palette" in rules.lower() or "4 palettes" in rules.lower(), (
                f"Genesis palette_rules[{era_key!r}] should reference 4-palette system"
            )

    def test_palette_rules_reference_hardware_quantization(self):
        """Palette rules should mention the 8-step per channel quantization values."""
        pd = get_prompt_data("genesis")
        for era_key, rules in pd.palette_rules.items():
            assert "36" in rules and "73" in rules and "109" in rules, (
                f"Genesis palette_rules[{era_key!r}] should list Genesis hardware step values"
            )

    def test_palette_rules_reference_dedicated_palette(self):
        """Palette rules should mention character palette isolation."""
        pd = get_prompt_data("genesis")
        for era_key, rules in pd.palette_rules.items():
            assert "dedicated" in rules.lower() or "cram" in rules.upper(), (
                f"Genesis palette_rules[{era_key!r}] should reference dedicated character palette"
            )

    def test_color_theory_references_hue_shifting(self):
        """Mid and late color theory should explain hue shifting."""
        pd = get_prompt_data("genesis")
        for era_key in ("mid", "late"):
            assert "hue shift" in pd.color_theory_rules[era_key].lower(), (
                f"Genesis color_theory[{era_key!r}] should reference hue shifting"
            )

    def test_color_theory_references_dithering(self):
        """Mid and late color theory should explain dithering for gradients."""
        pd = get_prompt_data("genesis")
        for era_key in ("mid", "late"):
            rules = pd.color_theory_rules[era_key].lower()
            assert "dither" in rules, (
                f"Genesis color_theory[{era_key!r}] should reference dithering"
            )

    def test_color_theory_references_atmospheric_palette(self):
        """Mid and late color theory should cover the dark atmospheric palette technique."""
        pd = get_prompt_data("genesis")
        for era_key in ("mid", "late"):
            rules = pd.color_theory_rules[era_key].lower()
            assert "atmospher" in rules, (
                f"Genesis color_theory[{era_key!r}] should reference atmospheric palette technique"
            )

    def test_color_theory_mid_references_shinobi(self):
        """Mid era color theory should reference the Shinobi III spotlight technique."""
        pd = get_prompt_data("genesis")
        rules = pd.color_theory_rules["mid"].lower()
        assert "shinobi" in rules, (
            "Genesis mid color_theory should reference Shinobi III spotlight technique"
        )

    def test_color_theory_late_references_material_rendering(self):
        """Late era color theory should cover material differentiation."""
        pd = get_prompt_data("genesis")
        rules = pd.color_theory_rules["late"].lower()
        assert "metal" in rules, "Genesis late color_theory should mention metal material"
        assert "fabric" in rules, "Genesis late color_theory should mention fabric material"
        assert "skin" in rules, "Genesis late color_theory should mention skin tones"

    def test_tool_configs_have_whitelist_and_blacklist(self):
        pd = get_prompt_data("genesis")
        for era_key, config in pd.tool_configs.items():
            assert "whitelist" in config, f"Missing whitelist for {era_key}"
            assert "blacklist" in config, f"Missing blacklist for {era_key}"
            assert "rules" in config, f"Missing rules for {era_key}"

    def test_tool_configs_late_allows_dither(self):
        """Late era tool config should whitelist draw_with_dither."""
        pd = get_prompt_data("genesis")
        assert "draw_with_dither" in pd.tool_configs["late"]["whitelist"], (
            "Genesis late tool_config should whitelist draw_with_dither"
        )

    def test_tool_configs_early_blocks_dither(self):
        """Early era tool config should blacklist draw_with_dither."""
        pd = get_prompt_data("genesis")
        assert "draw_with_dither" in pd.tool_configs["early"]["blacklist"], (
            "Genesis early tool_config should blacklist draw_with_dither"
        )

    def test_genesis_is_distinct_from_nes(self):
        """Genesis should be a completely separate entry from NES."""
        nes = get_prompt_data("nes")
        genesis = get_prompt_data("genesis")
        assert nes is not genesis
        assert nes.name != genesis.name
        assert nes.display_name != genesis.display_name
        assert genesis.few_shot_examples is not nes.few_shot_examples
        # Genesis has no 'retro' era
        assert "retro" not in genesis.eras

    def test_era_reference_games(self):
        """Each era should reference appropriate Genesis games."""
        pd = get_prompt_data("genesis")
        assert "Sonic" in pd.eras["early"].reference_games
        assert "Golden Axe" in pd.eras["early"].reference_games
        assert "Streets of Rage 2" in pd.eras["mid"].reference_games
        assert "Gunstar Heroes" in pd.eras["mid"].reference_games
        assert "Comix Zone" in pd.eras["late"].reference_games
        assert "Vectorman" in pd.eras["late"].reference_games

    def test_era_year_ranges(self):
        """Each era should cover the correct year range."""
        pd = get_prompt_data("genesis")
        assert "1989" in pd.eras["early"].year_range
        assert "1991" in pd.eras["early"].year_range
        assert "1992" in pd.eras["mid"].year_range
        assert "1993" in pd.eras["mid"].year_range
        assert "1994" in pd.eras["late"].year_range
        assert "1996" in pd.eras["late"].year_range


# --- NES (regression) ---


class TestNES:
    def test_get_prompt_data(self):
        pd = get_prompt_data("nes")
        assert isinstance(pd, ConsolePromptData)
        assert pd.name == "nes"

    def test_eras_populated(self):
        pd = get_prompt_data("nes")
        assert set(pd.eras.keys()) == {"retro", "early", "mid", "late"}
        _assert_valid_prompt_data(pd)

    def test_default_era(self):
        pd = get_prompt_data("nes")
        assert pd.default_era == "mid"


# --- Registry edge cases ---


class TestRegistry:
    def test_unknown_console_raises(self):
        with pytest.raises(NotImplementedError):
            get_prompt_data("sega_saturn")

    def test_all_registered_entries_valid(self):
        """Every entry in the registry should pass validation."""
        from retrogaze.console_prompt_data import _REGISTRY
        for key, pd in _REGISTRY.items():
            _assert_valid_prompt_data(pd)
