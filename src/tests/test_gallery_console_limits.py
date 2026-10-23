"""Hardware-limits section on the gallery page.

Separate from per-image captions. Existing sample cards keep their
metadata spans. Limit cards state only limits the generator enforces.
"""
import re
from pathlib import Path

GALLERY = Path(__file__).resolve().parents[2] / "frontend" / "gallery.html"

FOOTER = (
    "Playtest and prototype art under real console limits. "
    "Commission a pixel artist for ship art when the game earns it."
)

THUMBS = {
    "nes": "NES · 4 colors/sprite · 8×8 or 8×16 sprites",
    "snes": "SNES · up to 16 colors/sprite · console sprite and tile sizes",
    "genesis": "Genesis · 16 colors/sprite · 512-color set",
    "gb": "Game Boy · 4 shades · 8×8 or 8×16 sprites",
    "gbp": "Game Boy Pocket · 4 grays · 8×8 or 8×16 sprites · beta",
    "gbc": "GBC · 4-color palette banks",
    "c64": "C64 · 16 colors · hires",
    "pce": "PC Engine · 16-color palettes",
}

CAPTIONS = {
    "nes": (
        "4 colors per sprite (3 + clear). 8×8 or 8×16 sprites. "
        "54-color master palette. Built for mocks that look like NES hardware, "
        "not a soft filter on a PNG."
    ),
    "snes": (
        "Up to 16 colors per sprite from the SNES palette. "
        "Sprite and tile sizes match what the console expects. "
        "Stub bosses and UI while you playtest."
    ),
    "genesis": (
        "16 colors per sprite from the 512-color Genesis set. "
        "Same tile grammar as a real Mega Drive sheet. "
        "Stub enemies and HUD before you lock art direction."
    ),
    "gb": (
        "4 shades. 8×8 or 8×16 sprites. The green-gray look comes from the hardware. "
        "Stub your GB demo sprites here, then commission final pixels."
    ),
    "gbp": (
        "The Game Boy's limits with the Pocket's gray screen instead of green. Beta: available through the API and the MCP server, not in the web app's console menu."
    ),
    "gbc": (
        "GBC sprite and BG palette banks (4 colors each). "
        "More color than DMG, still a console budget. "
        "Placeholder sheets that stay honest about what GBC can show."
    ),
    "c64": (
        "16-color C64 hires palette. The generator offers hires only, "
        "with 2 colors per 8×8 cell. Prototype sprites that fit a C64 screen, "
        "then bring in an artist for the release build."
    ),
    "pce": (
        "PC Engine palette limits enforced. 16 colors per palette. "
        "Stub HuCard-era tiles for playtests. "
        "Ship art still belongs to a human pixel artist."
    ),
}


def _html():
    return GALLERY.read_text(encoding="utf-8")


def _section(html):
    opener = '<div class="section" id="console-limits">'
    start = html.find(opener)
    assert start != -1, "missing #console-limits"
    depth = 1
    index = start + len(opener)
    while index < len(html) and depth:
        next_open = html.find("<div", index)
        next_close = html.find("</div>", index)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            index = next_open + 4
        else:
            depth -= 1
            index = next_close + len("</div>")
    assert depth == 0, "unclosed #console-limits"
    return html[start + len(opener) : index - len("</div>")]


def _card(section, card_id):
    opener = f'<div class="sprite-card shot" id="{card_id}">'
    start = section.find(opener)
    assert start != -1, f"missing {card_id}"
    depth = 1
    index = start + len(opener)
    while index < len(section) and depth:
        next_open = section.find("<div", index)
        next_close = section.find("</div>", index)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            index = next_open + 4
        else:
            depth -= 1
            index = next_close + len("</div>")
    return section[start:index]


def test_limits_section_follows_the_sample_grids():
    html = _html()
    limits_at = html.find('id="console-limits"')
    assert limits_at != -1
    before = html[:limits_at]
    last_grid = max(
        before.rfind('class="sprite-grid"'),
        before.rfind('class="anim-strip"'),
        before.rfind('class="era-strip"'),
    )
    assert last_grid != -1
    main_end = html.find("</main>")
    assert main_end > limits_at
    assert "/examples/" not in html[limits_at:main_end]
    assert html.find('src="/examples/knight.png"') < limits_at


def test_limits_section_does_not_reflow_the_sample_grid():
    html = _html()
    assert 'id="console-limits"' in html
    assert "minmax(160px, 1fr)" in html
    assert "minmax(210px" not in html
    assert ".grid-3" not in html
    assert ".grid-4" not in html
    assert "hire for 1.0" not in html
    assert "[data-console" not in html
    assert "retrograzeai.com" not in html.lower()
    # Hosted SaaS domain removed in the open-source frontend.
    assert "retrogazeai.com" not in html.lower()


def test_limit_cards_use_enforceable_copy():
    section = _section(_html())
    assert section.count(FOOTER) == 8
    for key, thumb in THUMBS.items():
        card = _card(section, f"shot-{key}")
        assert thumb in card
        assert CAPTIONS[key] in card
        assert FOOTER in card
        assert "hire for 1.0" not in card


def test_gbc_pce_and_c64_do_not_claim_unenforced_limits():
    html = _html()
    section = _section(html).lower()
    assert "sprite caps" not in section
    assert "sprite limits" not in section
    assert "multicolor" not in section
    assert "called out in the generator" not in section
    assert "mode 1" not in section
    assert "4-color palette banks" in section
    assert "palette limits enforced" in section
    assert "hires only" in section
    assert "mode 1" not in html.lower()


def test_sample_shots_keep_metadata_and_are_not_rewritten():
    html = _html()
    knight = re.search(
        r'<img class="sprite-img" src="/examples/knight.png".*?</div>',
        html,
        re.S,
    )
    assert knight
    card = knight.group(0)
    assert "MID ERA &bull; 6 COLORS" in card
    assert "shot-thumb" not in card
    assert "shot-footer" not in card
    assert html.count("4 COLORS &bull; SEAMLESS") == 1
    assert html.count("3&times;3 CONNECTED &bull; 4 COLORS") == 1
    assert html.count('class="shot-thumb"') == 8


def test_limits_toggle_is_scoped_to_the_section():
    html = _html()
    assert "getElementById('console-limits')" in html
    assert "textContent = thumb" not in html
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
