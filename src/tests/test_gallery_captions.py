"""Gallery captions stay inside spans that already exist on the sample cards.

The short NES line is appended only to FLUX sample spans whose art
matches the enforced NES limits. Aseprite and idle demos keep their
measured meta. The #console-limits section is owned by a separate
change and is not part of this contract.
"""
import hashlib
import re
from pathlib import Path

GALLERY = Path(__file__).resolve().parents[2] / "frontend" / "gallery.html"

CAPTION = "4/tile"

# Sample-card tag skeleton (text stripped), plus the style and script
# blocks after rebasing onto master. Caption text can change. Sample-card
# tags, CSS, and JS cannot. The console-limits section is excluded.
SAMPLE_STRUCTURE_SHA256 = "135c93d48bdc6217ac9b84ebcd126f03700722a14d69aab35ab76079f71a5e0f"
STYLE_SHA256 = "f865a8795bf87a2f4159cc23763222b76c573f00a28b9746c50d4709b3134227"
SCRIPT_SHA256 = "e0f9d9e9115c3e5fd072ce804037a503504f854899bf33a00ea375f3a52f0bc3"

SAMPLE_CLASSES = frozenset({
    "anim-card", "anim-label", "anim-prompt", "anim-strip",
    "divider",
    "era-card", "era-colors", "era-label", "era-strip", "era-years",
    "img-lg", "img-sm",
    "page-header",
    "section", "section-label", "section-note",
    "sprite-card", "sprite-grid", "sprite-img", "sprite-meta",
    "sprite-prompt", "sprite-type", "subtitle", "surface-bg",
})


def _html():
    return GALLERY.read_text(encoding="utf-8")


def _samples(html):
    """Sample cards only. Stops before the console-limits section."""
    main = html.split('<main id="main-content">', 1)[1]
    return main.split('<div class="section" id="console-limits">', 1)[0]


def _structure(html):
    return re.sub(r">[^<]*<", "><", html)


def _block(html, tag):
    match = re.search(rf"<{tag}>(.*)</{tag}>", html, re.S)
    assert match, tag
    return match.group(1)


def test_sample_cards_add_no_elements_css_or_js():
    html = _html()
    samples = _samples(html)
    assert hashlib.sha256(_structure(samples).encode()).hexdigest() == SAMPLE_STRUCTURE_SHA256
    assert hashlib.sha256(_block(html, "style").encode()).hexdigest() == STYLE_SHA256
    assert hashlib.sha256(_block(html, "script").encode()).hexdigest() == SCRIPT_SHA256
    classes = set()
    for class_attr in re.findall(r'class="([^"]*)"', samples):
        classes.update(class_attr.split())
    assert classes == SAMPLE_CLASSES
    assert "minmax(160px, 1fr)" in html
    for forbidden in (
        "shot-thumb",
        "shot-caption",
        "shot-footer",
        "shot-toggle",
        'class="shot',
        "is-open",
        "aria-controls",
        ">Details<",
    ):
        assert forbidden not in samples


def test_caption_is_text_inside_existing_spans():
    html = _html()
    samples = _samples(html)
    assert samples.count(CAPTION) == 14
    spans = re.findall(r"<span\b[^>]*>.*?</span>", samples, re.S)
    caption_spans = [span for span in spans if CAPTION in span]
    assert len(caption_spans) == 14
    for span in caption_spans:
        assert (
            'class="sprite-meta"' in span
            or 'class="era-colors"' in span
            or 'class="anim-prompt"' in span
        )
        assert "ASEPRITE" not in span
        assert "OPUS" not in span
        assert "SONNET" not in span
        assert "4 colors per sprite" not in span.lower()
        assert "8×8" not in span
        assert "8×16" not in span


def test_measured_meta_stays_and_non_nes_cards_are_unchanged():
    html = _html()
    assert html.count(
        f'<span class="sprite-meta">MID ERA &bull; 6 COLORS &bull; {CAPTION}</span>'
    ) == 4
    assert html.count(
        f'<span class="sprite-meta">EARLY ERA &bull; 4 COLORS &bull; {CAPTION}</span>'
    ) == 1
    assert f'<span class="sprite-meta">3 COLORS &bull; {CAPTION}</span>' in html
    assert html.count(f'<span class="era-colors">6 COLORS &bull; {CAPTION}</span>') == 2
    for prompt in (
        '"a rogue with daggers"',
        '"a paladin with longsword"',
        '"a goblin"',
        '"a wizard casting a spell"',
    ):
        assert f'<span class="anim-prompt">{prompt} &bull; {CAPTION}</span>' in html
    assert '<span class="sprite-meta">4 COLORS &bull; SEAMLESS</span>' in html
    assert (
        '<span class="sprite-meta">3&times;3 CONNECTED &bull; 4 COLORS</span>'
        in html
    )
    assert html.count('<span class="sprite-meta">RETRO &bull; ASEPRITE MODE</span>') == 4
    assert html.count('<span class="sprite-meta">EARLY &bull; ASEPRITE MODE</span>') == 4
    assert html.count('<span class="sprite-meta">MID &bull; OPUS</span>') == 1
    assert html.count('<span class="sprite-meta">LATE &bull; OPUS</span>') == 2
    assert html.count('<span class="sprite-meta">MID &bull; SONNET</span>') == 1
    assert html.count('<span class="sprite-meta">LATE &bull; SONNET</span>') == 2
    assert ">EARLY &bull; OPUS</span>" in html
    assert ">EARLY &bull; SONNET</span>" in html
    for src in (
        "/examples/brick.png",
        "/examples/dungeon.png",
        "/examples/aseprite_retro_alien.png",
        "/examples/aseprite_retro_brick.png",
        "/examples/aseprite_late_potion.png",
        "/examples/aseprite_late_mage_sonnet.png",
        "/examples/anim_idle_opus.gif",
        "/examples/anim_idle_sonnet.gif",
    ):
        card = html.split(f'src="{src}"', 1)[1].split("</div>", 1)[0]
        assert CAPTION not in card


def test_sample_cards_do_not_claim_unenforced_limits():
    """Page-wide bans that #console-limits now owns are checked on samples only."""
    samples = _samples(_html()).lower()
    for bad in (
        "8×8",
        "8×16",
        "8x8",
        "8x16",
        "sprite_sizes",
        "4 colors/sprite",
        "4 colors per sprite",
        "3 + clear",
        "54-color",
        "nes 4 colors per tile",
        "hire for 1.0",
        "sprite caps",
        "sprite limits",
        "multicolor",
        "called out in the generator",
        "mode 1",
    ):
        assert bad not in samples
    assert CAPTION in samples
