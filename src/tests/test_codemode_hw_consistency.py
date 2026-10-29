"""The code-mode hardware model agrees with ConsoleProfile, except where the profile is known to be loose.

KNOWN_PROFILE_DIFFS lists those places exactly (CODE-MODE-SPEC §3.3). If someone fixes the profile,
this test fails and says which entry to delete.
"""

from retrogaze.codemode.binding import NES_COLORS, NES_LIMITS
from retrogaze.console_profile import NES, SNES_MODE1

KNOWN_PROFILE_DIFFS = {
    # field: (profile value, hardware value, why)
    ("nes", "max_colors_per_tile"): (4, 3, "a sprite tile has 3 opaque colors + transparent; BG 3 + shared backdrop"),
    ("snes", "max_colors_per_tile"): (16, 15, "pixel value 0 is transparent at every depth"),
    ("snes", "max_sprite_pixels_per_scanline"): (256, 272, "34 slivers x 8 px"),
}


def test_nes_profile_agrees():
    assert NES_LIMITS["oam"] == NES.max_sprites == 64
    assert NES_LIMITS["perLine"] == NES.max_sprites_per_scanline == 8
    assert NES_LIMITS["bgPalettes"] == NES.bg_palettes and NES_LIMITS["objPalettes"] == NES.sprite_palettes
    assert (NES_LIMITS["screenW"], NES_LIMITS["screenH"]) == NES.resolution
    assert set(NES_COLORS) == {h.upper() for h in NES.master_palette_hex}
    assert NES.attribute_block_size == 16 and NES.tile_size == 8
    assert set(NES.sprite_sizes) == {(8, 8), (8, 16)}


def test_known_profile_differences_are_exact():
    profiles = {"nes": NES, "snes": SNES_MODE1}
    for (console, fieldname), (profile_value, hardware_value, why) in KNOWN_PROFILE_DIFFS.items():
        got = getattr(profiles[console], fieldname)
        assert got == profile_value, (
            f"ConsoleProfile {console}.{fieldname} is now {got}; if it was fixed to the hardware value "
            f"{hardware_value} ({why}), delete this KNOWN_PROFILE_DIFFS entry")
        assert got != hardware_value
