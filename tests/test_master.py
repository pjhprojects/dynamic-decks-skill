"""What a theme takes from a PowerPoint slide master besides colors and backgrounds.

Which master when a file has several, title alignment, the footer and slide
number, bullets and body text. The templates come from
tests/fixtures/make_templates.py; LibreOffice is switched off here, since
none of this depends on drawing the template.
"""
from __future__ import annotations

import json
import re
import shutil

from _common import FIXTURES, OUT, Checks, run

t = Checks("Slide master")

lib = OUT / "master-library"
shutil.rmtree(lib, ignore_errors=True)
ENV = {"DYNAMIC_DECKS_HOME": str(lib), "DYNAMIC_DECKS_SOFFICE": "none"}


def make(template: str, name: str, *args):
    proc = run("add_theme.py", "from-pptx", FIXTURES / template, "--name", name, *args, env=ENV)
    folder = lib / "themes" / name
    css = (folder / "theme.css").read_text(encoding="utf-8") if (folder / "theme.css").is_file() else ""
    meta = json.loads((folder / "theme.json").read_text(encoding="utf-8")) if (folder / "theme.json").is_file() else {}
    return proc, folder, css, meta


def token(css: str, name: str, block: str = ":root") -> str:
    """A token's value in the first rule whose selector starts with `block`."""
    m = re.search(r"(?m)^" + re.escape(block) + r"[^{]*\{([^}]*)\}", css)
    m = re.search(re.escape(name) + r":\s*([^;]+);", m.group(1) if m else "")
    return m.group(1).strip() if m else ""


# ---- several slide masters -------------------------------------------------------
proc, folder, css, meta = make("template-masters.pptx", "masters")
t.ok("a file with two masters becomes a theme", proc.returncode == 0 and bool(css), proc.stdout[-300:] + proc.stderr[-300:])
t.ok("the report lists every master with its layouts and slides",
     '1 "Corporate Light" (11 layouts, 1 slide)' in proc.stdout and '2 "Corporate Dark" (11 layouts, 3 slides)' in proc.stdout)
t.ok("the master most slides use is taken", token(css, "--color-bg") == "#101820" and token(css, "--color-accent") == "#F2A541"
     and "because most slides use it" in proc.stdout, token(css, "--color-bg"))
t.ok("the theme records which master it came from", meta.get("master") == "Corporate Dark")
proc, folder, css, meta = make("template-masters.pptx", "masters-1", "--master", "1")
t.ok("--master picks one by number", token(css, "--color-bg") == "#FFFFFF" and token(css, "--color-accent") == "#0F7B4F"
     and meta.get("master") == "Corporate Light", token(css, "--color-bg"))
proc, folder, css, meta = make("template-masters.pptx", "masters-name", "--master", "corporate light")
t.ok("--master picks one by name", meta.get("master") == "Corporate Light" and "because it was asked for" in proc.stdout)
proc, folder, css, meta = make("template-masters.pptx", "masters-bad", "--master", "7")
t.ok("a master that is not there stops with the list", proc.returncode != 0 and not css and "Corporate Dark" in proc.stderr + proc.stdout,
     proc.stdout[-200:] + proc.stderr[-200:])
proc, folder, css, meta = make("template-masters.pptx", "masters-vague", "--master", "corporate")
t.ok("a name that fits two masters asks for the number", proc.returncode != 0 and "use its number" in proc.stderr + proc.stdout)
proc, folder, css, meta = make("template-brand.pptx", "brand")
t.ok("a file with one master says nothing about masters", proc.returncode == 0 and "slide masters" not in proc.stdout and "master" not in meta,
     proc.stdout[-300:] + proc.stderr[-300:])

t.done()
