"""Staying true to a template: sharp pictures.

A rendered background must not lose fine detail: a hairline rule and small
lettering stay sharp, so pictures are drawn at twice the stage size and kept
without loss.

Most of this needs LibreOffice to draw the templates and is skipped without it.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

from _common import FIXTURES, OUT, SCRIPTS, STARTER_SRC, Checks, build, launch, run

sys.path.insert(0, str(SCRIPTS))
import _backgrounds  # noqa: E402

t = Checks("Fidelity to the template")

lib = OUT / "fidelity-library"
shutil.rmtree(lib, ignore_errors=True)
ENV = {"DYNAMIC_DECKS_HOME": str(lib)}
NO_LO = {**ENV, "DYNAMIC_DECKS_SOFFICE": "none"}
DECK = FIXTURES / "boxes.src.html"


def make(template, name: str, *args, env=ENV):
    proc = run("add_theme.py", "from-pptx", FIXTURES / template, "--name", name, *args, env=env)
    folder = lib / "themes" / name
    css = (folder / "theme.css").read_text(encoding="utf-8") if (folder / "theme.css").is_file() else ""
    meta = json.loads((folder / "theme.json").read_text(encoding="utf-8")) if (folder / "theme.json").is_file() else {}
    return proc, folder, css, meta


def token(css: str, name: str) -> str:
    m = re.search(r"(?m)^:root[^{]*\{([^}]*)\}", css)
    m = re.search(re.escape(name) + r":\s*([^;]+);", m.group(1) if m else "")
    return m.group(1).strip() if m else ""


def px(css: str, name: str) -> int:
    m = re.fullmatch(r"(-?\d+)px", token(css, name))
    return int(m.group(1)) if m else -1


def kind_of(path) -> str:
    """lossless or lossy, from a WebP file's header."""
    head = path.read_bytes()[:16]
    return "lossless" if head[12:16] == b"VP8L" else "lossy" if head[12:16] in (b"VP8 ", b"VP8X") else "other"


# ---- pictures supplied by hand keep the sharpness they came with -------------------------
big = OUT / "supplied-big.png"
im = Image.new("RGB", (3200, 1800), "#FFFFFF")
im.paste((16, 60, 120), (2400, 0, 3200, 1800))   # a band down the right
for x in range(0, 2400, 2):
    im.putpixel((x, 900), (0, 0, 0))             # a one-pixel dotted line: gone if the picture is scaled down
im.save(big)
proc = run("add_theme.py", "new", "--name", "supplied-big", "--accent", "#2B6CF0", "--background", f"content={big}", env=NO_LO)
stored = lib / "themes" / "supplied-big" / "backgrounds" / "content.webp"
t.ok("a supplied picture is kept at its own size, up to twice the stage", stored.is_file() and Image.open(stored).size == (3200, 1800),
     Image.open(stored).size if stored.is_file() else proc.stdout[-300:])
t.ok("line artwork is stored without loss", stored.is_file() and kind_of(stored) == "lossless"
     and Image.open(stored).convert("RGB").getpixel((100, 900)) == (0, 0, 0) and Image.open(stored).convert("RGB").getpixel((101, 900)) == (255, 255, 255))
small = OUT / "supplied-small.png"
Image.new("RGB", (1280, 720), "#102030").save(small)
im = Image.open(small)
im.paste((240, 200, 40), (900, 100, 1200, 600))
im.save(small)
proc = run("add_theme.py", "new", "--name", "supplied-small", "--accent", "#2B6CF0", "--background", f"content={small}", env=NO_LO)
t.ok("a picture narrower than the stage is reported as soft", "only 1280px wide" in proc.stdout, proc.stdout[-400:])
deck = OUT / "fidelity-supplied.html"
proc = build(DECK, deck, "--theme", "supplied-big", env=NO_LO)
html = deck.read_text(encoding="utf-8") if deck.is_file() else ""
t.ok("the build puts a theme's picture in the deck exactly as the theme has it", stored.is_file()
     and base64.b64encode(stored.read_bytes()).decode()[:4000] in html, proc.stdout[-300:])

if not _backgrounds.soffice():
    print("  skip  LibreOffice is not installed: the templates were not drawn")
    t.done()

# ---- sharp pictures ---------------------------------------------------------------------
proc, rule, css, meta = make("template-rule.pptx", "rule")
rule_report = proc.stdout
pic_path = rule / "backgrounds" / "content.webp"
t.ok("a template with a rule under the title becomes a picture theme", proc.returncode == 0 and pic_path.is_file(), proc.stdout[-400:] + proc.stderr[-300:])
pic = Image.open(pic_path).convert("RGB") if pic_path.is_file() else Image.new("RGB", (1, 1))
t.ok("the picture is drawn at twice the stage size", pic.size == (3840, 2160), pic.size)
t.ok("and stored without loss", kind_of(pic_path) == "lossless", kind_of(pic_path))
if pic.size == (3840, 2160):
    # the rule is 0.4% of the slide's height, at 21.2%: rows 458 to 466 of 2160
    column = [pic.getpixel((2000, y)) for y in range(440, 485)]
    red = [i for i, c in enumerate(column) if c == (200, 16, 46)]
    white = [i for i, c in enumerate(column) if c == (255, 255, 255)]
    t.ok("the rule is its exact color with clean edges", len(red) >= 6 and len(red) + len(white) >= len(column) - 2, (len(red), len(white), len(column)))
    letters = pic.crop((2400, 150, 3600, 280)).convert("L").tobytes()   # "Quarterly Business Review", small gray text top right
    dark = sum(1 for v in letters if v < 140)
    t.ok("small text in the artwork has solid strokes, not a gray smear", dark > 1500, dark)
t.ok("such artwork costs a deck little", pic_path.stat().st_size < 60 * 1024, pic_path.stat().st_size)

proc, photo, pcss, pmeta = make("template-photo.pptx", "photo")
ppath = photo / "backgrounds" / "content.webp"
t.ok("a photograph is compressed instead, and gently", ppath.is_file() and kind_of(ppath) == "lossy" and 1920 <= Image.open(ppath).width <= 2560,
     (kind_of(ppath), Image.open(ppath).size) if ppath.is_file() else "missing")

t.done()
