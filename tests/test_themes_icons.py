"""Adding a theme and an icon set, and keeping them apart from the skill."""
from __future__ import annotations

import hashlib
import json
import shutil

from _common import FIXTURES, OUT, SKILL, STARTER_SRC, Checks, build, run

t = Checks("Themes and icon sets")

lib = OUT / "library"
shutil.rmtree(lib, ignore_errors=True)
env = {"DYNAMIC_DECKS_HOME": str(lib)}


def tree_hash(folder):
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(f.relative_to(folder)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


before = tree_hash(SKILL)

proc = run("add_theme.py", "from-pptx", FIXTURES / "template.pptx", "--name", "greenfield", env=env)
theme = lib / "themes" / "greenfield"
t.ok("a theme is created from a PowerPoint template", proc.returncode == 0 and (theme / "theme.css").is_file(), proc.stdout[-300:] + proc.stderr[-300:])
css = (theme / "theme.css").read_text(encoding="utf-8") if (theme / "theme.css").is_file() else ""
t.ok("it takes the template's colors", "--color-accent: #0F7B4F" in css and "--color-text: #1B2A22" in css)
t.ok("it takes the template's fonts, with a fallback", '--font-display: "Georgia"' in css and '--font-body: "Calibri"' in css)
t.ok("it derives a dark variant", ':root[data-variant="dark"]' in css)
t.ok("it finds the logo on the slide master", (theme / "logo.png").is_file())
t.ok("it reports what to review", "is not embedded" in proc.stdout and "derived automatically" in proc.stdout)
proc = run("add_theme.py", "check", "greenfield", env=env)
t.ok("the new theme passes the theme check", proc.returncode == 0, proc.stdout[-300:])

green = OUT / "starter-green.html"
proc = build(STARTER_SRC, green, "--theme", "greenfield", env=env)
html = green.read_text(encoding="utf-8") if green.is_file() else ""
t.ok("the starter builds in the new theme with no slide edits", proc.returncode == 0 and 'data-theme="greenfield"' in html, proc.stdout[-200:] + proc.stderr[-200:])
t.ok("the logo is embedded", 'data-logo="yes"' in html and "--logo-url:url(data:image/png" in html)

proc = build(OUT / "starter.html" if (OUT / "starter.html").is_file() else STARTER_SRC, OUT / "starter-rethemed.html", "--theme", "greenfield", "--variant", "dark", env=env)
t.ok("a built deck can be re-themed directly", proc.returncode == 0 and 'data-variant="dark"' in (OUT / "starter-rethemed.html").read_text(encoding="utf-8"))
proc = build(green, OUT / "starter-green-rebuilt.html")          # the theme is not installed in this library
t.ok("a deck keeps its embedded theme when that theme is not installed", proc.returncode == 0 and "was kept" in proc.stdout
     and "0F7B4F" in (OUT / "starter-green-rebuilt.html").read_text(encoding="utf-8").upper(), proc.stdout[-300:])
proc = run("unpack.py", green, "-o", OUT / "green.src.html", "--theme-to", OUT / "recovered-theme")
proc2 = build(STARTER_SRC, OUT / "starter-recovered.html", "--theme", OUT / "recovered-theme")
t.ok("a theme can be recovered from a deck and reused", proc.returncode == 0 and proc2.returncode == 0, proc2.stdout[-200:] + proc2.stderr[-200:])

proc = run("add_theme.py", "new", "--name", "brandx", "--bg", "#FFFDF7", "--text", "#22201C", "--accent", "#F5C400",
           "--accent2", "#7A1FA2", "--shape", "sharp", env=env)
bx = (lib / "themes" / "brandx" / "theme.css")
t.ok("a theme is created from brand values", proc.returncode == 0 and bx.is_file(), proc.stdout[-200:])
t.ok("a hard-to-read accent is adjusted and reported", "was too close to the background" in proc.stdout)
t.ok("a light brand color gets dark text on title slides", "--color-inverse-text: #22201C" in bx.read_text(encoding="utf-8"))
proc = run("add_theme.py", "list", env=env)
t.ok("both themes are listed as the user's", proc.stdout.count("yours") == 2 and "built-in" in proc.stdout, proc.stdout)

proc = run("add_icons.py", FIXTURES / "icons", "--name", "acme", "--strip-prefix", "ic_", "--license", "Test icons", "--two-tone", env=env)
pack = lib / "icons" / "acme" / "icons.json"
icons = json.loads(pack.read_text(encoding="utf-8")) if pack.is_file() else {}
t.ok("an icon set is imported from a folder of SVGs", proc.returncode == 0 and set(icons) == {"growth-chart", "rocket-launch", "shield", "team"}, sorted(icons))
body = json.dumps(icons)
t.ok("colors become currentColor", "#0A66C2" not in body and "currentColor" in body)
t.ok("scripts and event handlers are removed", "alert" not in body and "onclick" not in body)
t.ok("a second tone is kept as a variable", "--icon-secondary" in icons.get("team", {}).get("b", ""))
t.ok("an unreadable file is skipped and reported", "broken.svg" in proc.stdout)
t.ok("a catalog page is written", (lib / "icons" / "acme" / "catalog.html").is_file())

mini = OUT / "icons.src.html"
mini.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Icons</title><meta name="deck:icons" content="acme"></head><body>'
                '<main class="deck"><section class="slide"><h2 class="slide-title">Icons</h2><div class="slide-body">'
                '<svg class="icon"><use href="#icon-team"/></svg><svg class="icon"><use href="#icon-shield"/></svg></div>'
                '<aside class="notes"><p>n</p></aside></section></main></body></html>', encoding="utf-8")
proc = build(mini, OUT / "icons.html", env=env)
t.ok("a deck builds with the custom set", proc.returncode == 0 and "icons 'acme' (2 used)" in proc.stdout, proc.stdout[-200:] + proc.stderr[-200:])
mini.write_text(mini.read_text(encoding="utf-8").replace("#icon-shield", "#icon-rocket"), encoding="utf-8")
proc = build(mini, OUT / "icons-missing.html", env=env)
t.ok("an icon missing from the active set fails, sets are not mixed", proc.returncode == 1 and "not in the 'acme' set" in proc.stderr)
(lib / "settings.json").write_text('{"icon_fallback": "default"}', encoding="utf-8")
proc = build(mini, OUT / "icons-fallback.html", env=env)
t.ok("unless the user allows borrowing from the built-in set", proc.returncode == 0 and "came from the built-in set" in proc.stdout, proc.stdout[-200:])

t.ok("nothing was written into the skill folder", tree_hash(SKILL) == before)
t.done()
