"""
Tests for console-specific prompt wiring in mcp_prompts.py.

Validates that _palette_rules, _tool_rules, _build_system_prompt use
console-specific data from console_prompt_data.py when available,
and fall back to module-level NES dicts when not.
"""

import pytest

from retrogaze.mcp_prompts import (
    _palette_rules,
    _tool_rules,
    build_mcp_prompt,
)
from retrogaze.console_prompt_data import get_prompt_data


# All consoles that have prompt data
ALL_CONSOLES = ["nes", "gb_dmg", "gb_pocket", "c64", "genesis", "snes", "gbc", "pc_engine"]

# Eras to test
ERAS = ["early", "mid", "late"]


# ---------------------------------------------------------------------------
# _palette_rules wiring
# ---------------------------------------------------------------------------


class TestPaletteRulesWiring:
    """Verify _palette_rules uses console-specific data."""

    def _dummy_colors_and_roles(self, n=4):
        colors = [f"#{i:02X}0000" for i in range(n)]
        roles = {c: f"role_{i}" for i, c in enumerate(colors)}
        return colors, roles

    @pytest.mark.parametrize("console", ALL_CONSOLES)
    def test_palette_rules_uses_console_data(self, console):
        """Each console's palette rules should come from console_prompt_data."""
        pd = get_prompt_data(console)
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console=console)
        # Result should be non-empty
        assert len(result) > 50
        assert "PALETTE RULES" in result

    def test_nes_uses_nes_specific_text(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="nes")
        # NES mid palette rules mention "colors" not "shades"
        assert "colors" in result.lower()

    def test_gb_dmg_uses_shade_language(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="gb_dmg")
        # GB DMG should talk about "shades" not generic "colors"
        assert "shade" in result.lower()

    def test_gb_pocket_uses_shade_language(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="gb_pocket")
        assert "shade" in result.lower()

    def test_genesis_mentions_9bit(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="genesis")
        assert "9-bit" in result or "Genesis" in result

    def test_snes_mentions_15bit(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="snes")
        assert "15-bit" in result or "SNES" in result

    def test_c64_mentions_fixed_palette(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="c64")
        assert "C64" in result or "fixed" in result.lower()

    def test_gbc_mentions_15bit(self):
        colors, roles = self._dummy_colors_and_roles()
        result = _palette_rules("mid", colors, roles, console="gbc")
        assert "15-bit" in result or "GBC" in result

    def test_different_consoles_produce_different_rules(self):
        """NES and GB DMG should not produce identical palette rules."""
        colors, roles = self._dummy_colors_and_roles()
        nes = _palette_rules("mid", colors, roles, console="nes")
        dmg = _palette_rules("mid", colors, roles, console="gb_dmg")
        assert nes != dmg

    @pytest.mark.parametrize("era", ERAS)
    def test_all_eras_produce_output(self, era):
        """Every era should produce non-empty palette rules for every console."""
        colors, roles = self._dummy_colors_and_roles(6 if era == "late" else 4)
        for console in ALL_CONSOLES:
            result = _palette_rules(era, colors, roles, console=console)
            assert len(result) > 20, f"{console}/{era} produced empty palette rules"


# ---------------------------------------------------------------------------
# _tool_rules wiring
# ---------------------------------------------------------------------------


class TestToolRulesWiring:
    """Verify _tool_rules uses console-specific data."""

    @pytest.mark.parametrize("console", ALL_CONSOLES)
    def test_tool_rules_returns_triple(self, console):
        """_tool_rules should return (rules_text, whitelist, blacklist)."""
        rules, wl, bl = _tool_rules("mid", "character", console=console)
        assert isinstance(rules, str)
        assert isinstance(wl, list)
        assert isinstance(bl, list)
        assert len(rules) > 20
        assert "create_canvas" in wl
        assert "set_palette" in wl

    def test_gb_dmg_tool_rules_differ_from_nes(self):
        """GB DMG should have different tool rules than NES."""
        nes_rules, _, _ = _tool_rules("mid", "character", console="nes")
        dmg_rules, _, _ = _tool_rules("mid", "character", console="gb_dmg")
        # GB DMG mentions shades; NES mentions NES
        assert nes_rules != dmg_rules

    @pytest.mark.parametrize("console", ALL_CONSOLES)
    def test_blacklist_always_includes_auto_shading(self, console):
        """apply_auto_shading should be blacklisted for all consoles."""
        _, _, bl = _tool_rules("mid", "character", console=console)
        assert "apply_auto_shading" in bl

    @pytest.mark.parametrize("era", ERAS)
    @pytest.mark.parametrize("console", ALL_CONSOLES)
    def test_all_eras_all_consoles(self, era, console):
        """Every era+console combo should produce valid tool rules."""
        rules, wl, bl = _tool_rules(era, "character", console=console)
        assert len(rules) > 20
        assert len(wl) >= 2  # at minimum create_canvas and set_palette


# ---------------------------------------------------------------------------
# build_mcp_prompt wiring (integration)
# ---------------------------------------------------------------------------


class TestBuildMcpPromptConsoleWiring:
    """Integration tests: build_mcp_prompt should produce console-specific output."""

    @pytest.mark.parametrize("console", ALL_CONSOLES)
    def test_builds_successfully_for_all_consoles(self, console):
        """build_mcp_prompt should not raise for any console."""
        result = build_mcp_prompt(
            "knight with sword",
            "character",
            (16, 16),
            "side",
            "auto",
            "Black",
            "mid",
            console=console,
        )
        assert "system_prompt" in result
        assert "user_prompt" in result
        assert "palette" in result
        assert len(result["system_prompt"]) > 200

    def test_nes_system_prompt_mentions_nes(self):
        result = build_mcp_prompt("knight", console="nes")
        sp = result["system_prompt"]
        # NES view rules mention "NES convention"
        assert "NES" in sp

    def test_gb_dmg_system_prompt_uses_gb_content(self):
        result = build_mcp_prompt("knight", console="gb_dmg")
        sp = result["system_prompt"]
        # GB DMG palette rules use "shade"
        assert "shade" in sp.lower()
        # GB DMG few-shot uses "GB" in the reference
        assert "GB" in sp

    def test_genesis_system_prompt_uses_genesis_content(self):
        result = build_mcp_prompt("knight", console="genesis")
        sp = result["system_prompt"]
        assert "Genesis" in sp or "9-bit" in sp

    @pytest.mark.parametrize("view", ["side", "front", "top-down", "3/4"])
    def test_view_rules_are_console_specific(self, view):
        """View rules for non-NES consoles should differ from NES."""
        nes = build_mcp_prompt("knight", view=view, console="nes")
        dmg = build_mcp_prompt("knight", view=view, console="gb_dmg")
        # Extract view section
        nes_sp = nes["system_prompt"]
        dmg_sp = dmg["system_prompt"]
        # They should differ (GB DMG has shade-based view rules)
        assert nes_sp != dmg_sp

    @pytest.mark.parametrize("era", ERAS)
    def test_few_shot_examples_are_console_specific(self, era):
        """Few-shot examples for non-NES consoles should differ from NES."""
        nes = build_mcp_prompt("knight", era=era, console="nes")
        dmg = build_mcp_prompt("knight", era=era, console="gb_dmg")
        nes_sp = nes["system_prompt"]
        dmg_sp = dmg["system_prompt"]
        # NES and GB DMG reference examples should be different
        assert nes_sp != dmg_sp

    @pytest.mark.parametrize("console", ALL_CONSOLES)
    @pytest.mark.parametrize("era", ERAS)
    def test_no_format_errors(self, console, era):
        """No KeyError or ValueError from template formatting."""
        result = build_mcp_prompt(
            "green slime blob",
            "enemy",
            (16, 16),
            "side",
            "auto",
            "Black",
            era,
            console=console,
        )
        sp = result["system_prompt"]
        # No unformatted placeholders should remain
        assert "{c0}" not in sp
        assert "{r0}" not in sp
        assert "{n}" not in sp
        assert "{extra_color}" not in sp
