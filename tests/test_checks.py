"""The build and the delivery checks: a clean deck passes, a broken one is caught."""
from __future__ import annotations

import re

from _common import FIXTURES, OUT, SKILL, Checks, build, run, showcase, starter

t = Checks("Build and delivery checks")

deck = starter()
html = deck.read_text(encoding="utf-8")
proc = run("check.py", deck)
t.ok("the starter deck passes every check", proc.returncode == 0 and "all checks pass" in proc.stdout, proc.stdout[-300:])
t.ok("the build output is one file under 2 MB", deck.stat().st_size < 2 * 1024 * 1024, deck.stat().st_size)
remote = sorted(set(re.findall(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)""", html)) - {"http://www.w3.org/2000/svg"})
t.ok("it references nothing on the internet", not remote, remote)
t.ok("it carries the engine's license credit", "Engine and layouts: MIT License" in html)
t.ok("it carries the icon and font credits", "Icons: Lucide" in html and "SIL Open Font License" in html)
t.ok("only the icons it uses are embedded", 5 < html.count("<symbol id=\"icon-") < 60, html.count("<symbol id=\"icon-"))

proc = run("check.py", FIXTURES / "violations.src.html")
out = proc.stdout
t.ok("a broken deck fails", proc.returncode == 1)
for kind, needle in [
    ("a hard-coded color in a style attribute", 'style="color: red" hard-codes red'),
    ("a hard-coded color in an SVG attribute", 'fill="#00ff00" hard-codes a color'),
    ("a hard-coded color in a script", "slide script: hard-codes #abcdef"),
    ("a hard-coded font", "hard-codes a font"),
    ("an icon that is not in the library", 'icon "not-a-real-icon" is not in the'),
    ("an image loaded from the internet", "loads from the internet"),
    ("an @import", "@import loads another file"),
    ("a network call in a script", "reaches outside the file"),
    ("a slide without notes", "no speaker notes"),
    ("an unknown layout", 'unknown layout "nonsense"'),
    ("an unscoped style", "needs the data-slide-scope attribute, or it would restyle"),
    ("an unscoped script", "so the engine runs it for this slide only"),
    ("a state selector that can never match", "never matches"),
    ("an animation that relies on forwards", "relies on 'forwards'"),
    ("an animated script with no resting state", "no 'deck:rest' handler"),
]:
    t.ok("it catches " + kind, needle in out, needle)
t.ok("an element marked data-raw is exempt and listed", "keeps its own colors (customer logo colors)" in out)
t.ok("dense slides get a warning", "7 bullets in one list" in out)

bad = OUT / "bad-icon.src.html"
bad.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>x</title></head><body><main class="deck">'
               '<section class="slide"><h2 class="slide-title">x</h2><svg class="icon"><use href="#icon-rockett"/></svg>'
               '<img src="missing.png" alt=""><aside class="notes"><p>n</p></aside></section></main></body></html>', encoding="utf-8")
proc = build(bad, OUT / "bad-icon.html")
t.ok("the build fails on a missing icon and suggests close names", proc.returncode == 1 and "rocket" in proc.stderr, proc.stderr[:200])
t.ok("the build fails on a missing image file", "does not exist: missing.png" in proc.stderr, proc.stderr[:300])

proc = run("unpack.py", deck, "-o", OUT / "roundtrip" / "starter.src.html")
again = OUT / "roundtrip" / "starter.html"
build(OUT / "roundtrip" / "starter.src.html", again)
t.ok("unpack then build reproduces the deck", again.is_file() and again.stat().st_size == deck.stat().st_size, (proc.stdout[:80], again.stat().st_size if again.is_file() else None, deck.stat().st_size))

proc = run("chart.py", "--type", "bar", "--categories", "A,B,C", "--values", "1,2,3", "--name", "N", "--highlight", "C")
t.ok("chart.py draws a bar chart with theme classes only", proc.returncode == 0 and proc.stdout.count("chart-bar series-1") == 3
     and not re.search(r'(?:fill|stroke)="#', proc.stdout), proc.stdout[:120])
proc = run("find_icon.py", "growth", "--limit", "3")
t.ok("find_icon.py finds icons by meaning", "trending-up" in proc.stdout, proc.stdout[:160])
proc = run("find_icon.py", "--check", "rocket", "not-a-real-icon")
t.ok("find_icon.py --check reports a missing name", proc.returncode == 1 and "MISSING not-a-real-icon" in proc.stdout)

example = SKILL.parent / "examples" / "dynamic-decks-starter.html"
t.ok("the starter in examples/ is up to date (run tools/package.py to refresh it)",
     example.is_file() and example.read_bytes() == deck.read_bytes())
show = showcase()
proc = run("check.py", show)
t.ok("the showcase deck passes every check, with no warnings", proc.returncode == 0 and "all checks pass" in proc.stdout and "warn" not in proc.stdout.lower(), proc.stdout[-300:])
example = SKILL.parent / "examples" / "dynamic-decks-showcase.html"
t.ok("the showcase in examples/ is up to date (run tools/package.py to refresh it)",
     example.is_file() and example.read_bytes() == show.read_bytes())
front = (SKILL.parent / "index.html").read_text(encoding="utf-8")
target = re.search(r'url=([^"]+)"', front)
t.ok("the live site's front page forwards to the showcase in examples/",
     target is not None and (SKILL.parent / target.group(1)).resolve() == example.resolve() and f"location.replace('{target.group(1)}'" in front, front[:200])
t.ok("the showcase's closing slide links to the project page", 'href="https://github.com/pjhprojects/dynamic-decks-skill"' in show.read_text(encoding="utf-8"))
t.ok("the license inside the skill matches the repository's", (SKILL / "LICENSE.txt").read_text() == (SKILL.parent / "LICENSE").read_text())
t.done()
