"""M1-25: the agent skill's rules block is generated from the rule registry, so it cannot drift."""

import re

from retrogaze.codemode.binding import render_cheatsheet

from ._codemode import REPO

SKILL = REPO / "skills" / "retrogaze-code-mode" / "SKILL.md"


def test_cheatsheet_is_generated():
    text = SKILL.read_text()
    assert text.startswith("---\nname: retrogaze-code-mode\ndescription: ")
    m = re.search(r"<!-- BEGIN GENERATED: rules nes -->\n(.*)<!-- END GENERATED: rules nes -->", text, re.S)
    assert m, "generated rules block missing"
    assert m.group(1) == render_cheatsheet("nes"), "regenerate the block from binding.render_cheatsheet('nes')"
