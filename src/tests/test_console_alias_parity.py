"""Alias-parity tests between console_profile and console_prompt_data.

Ensures every console string accepted by ``console_profile.get_profile`` is
either generation-supported (resolves in ``console_prompt_data``) or is one of
the documented profile-only modes that reject with a clean 422 at generation.
Closes the alias-mismatch bug documented in docs/PIXEL-GEN-STUDY-2026-07-04.md
(live failure: ``console="gameboy"`` 500ing instead of resolving).

Profile-only modes (c64_multicolor, snes_mode1, snes_mode7) intentionally have
NO prompt data — see ``is_generation_supported``'s docstring and
test_byok_aseprite.TestUnsupportedConsole. Supporting them is a product
decision, not an alias fix.
"""

import pytest

from retrogaze.console_profile import _PROFILES, get_profile
from retrogaze.console_prompt_data import (
    _PROFILE_ONLY_MODES,
    _REGISTRY,
    get_prompt_data,
    is_generation_supported,
)


class TestAliasParity:
    """Every profile-registry key must resolve OR be a documented profile-only mode."""

    def test_all_profile_keys_accounted_for(self):
        """Each key in _PROFILES is either in _REGISTRY or profile-only."""
        missing = sorted(set(_PROFILES) - set(_REGISTRY) - _PROFILE_ONLY_MODES)
        assert missing == [], (
            f"console_profile keys neither generation-supported nor declared "
            f"profile-only: {missing}"
        )

    def test_profile_only_modes_have_profiles(self):
        """The profile-only set must stay in sync with _PROFILES."""
        orphans = sorted(_PROFILE_ONLY_MODES - set(_PROFILES))
        assert orphans == [], f"_PROFILE_ONLY_MODES not in console_profile: {orphans}"

    def test_profile_only_modes_not_in_registry(self):
        """Profile-only modes must not silently gain prompt data."""
        overlap = sorted(_PROFILE_ONLY_MODES & set(_REGISTRY))
        assert overlap == [], (
            f"profile-only modes unexpectedly generation-supported: {overlap} "
            f"(if intentional, remove from _PROFILE_ONLY_MODES and update "
            f"TestUnsupportedConsole)"
        )

    def test_all_prompt_registry_keys_in_profile_registry(self):
        """Each key in _REGISTRY must be in _PROFILES (no orphan prompt keys)."""
        missing = sorted(set(_REGISTRY) - set(_PROFILES))
        assert missing == [], (
            f"console_prompt_data keys missing from console_profile: {missing}"
        )

    def test_get_prompt_data_accepts_every_supported_profile_alias(self):
        """get_prompt_data must not raise for any generation-supported key."""
        for key in sorted(set(_PROFILES) - _PROFILE_ONLY_MODES):
            data = get_prompt_data(key)
            assert data is not None, f"get_prompt_data({key!r}) returned None"

    def test_profile_only_modes_reject_cleanly(self):
        """Profile-only modes raise NotImplementedError and report unsupported."""
        for key in sorted(_PROFILE_ONLY_MODES):
            assert is_generation_supported(key) is False
            with pytest.raises(NotImplementedError):
                get_prompt_data(key)


class TestNormalizationParity:
    """get_prompt_data must normalize the same way get_profile does."""

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("NES", "nes"),
            ("SNES", "snes"),
            ("Super Nintendo", "super_nintendo"),
            ("Game Boy", "game_boy"),
            ("Game-Boy", "game_boy"),
            ("C64", "c64"),
            ("GENESIS", "genesis"),
            ("Mega Drive", "mega_drive"),
            ("GBC", "gbc"),
            ("PC-Engine", "pc_engine"),
            ("TurboGrafx-16", "turbografx_16"),
        ],
    )
    def test_normalized_lookup_matches_profile(self, alias, canonical):
        """A normalized alias must resolve to the same prompt data as the
        canonical name that get_profile returns."""
        profile = get_profile(alias)
        expected = get_prompt_data(profile.name)
        assert get_prompt_data(alias) is expected, (
            f"get_prompt_data({alias!r}) did not match canonical {canonical!r}"
        )

    def test_is_generation_supports_normalized_aliases(self):
        """is_generation_supported must accept normalized aliases too."""
        assert is_generation_supported("SNES") is True
        assert is_generation_supported("Game Boy") is True
        assert is_generation_supported("snes_mode7") is False
        assert is_generation_supported("c64_multicolor") is False
        assert is_generation_supported("dreamcast") is False
