"""Staying true to a template: sharp pictures, and text where the template's own boxes put it.

Two things a rendered background must not lose. Fine detail: a hairline rule
and small lettering stay sharp, so pictures are drawn at twice the stage size
and kept without loss. And the template's layout: its title box and text box
decide where text goes, not a guess from the picture, so a title sits above
the rule drawn under it and on the band drawn behind it.

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
t.ok("text that is part of the artwork is reported", "the backgrounds include text that is part of the template" in proc.stdout
     and "Northwind Trading" in proc.stdout)

proc, photo, pcss, pmeta = make("template-photo.pptx", "photo")
ppath = photo / "backgrounds" / "content.webp"
t.ok("a photograph is compressed instead, and gently", ppath.is_file() and kind_of(ppath) == "lossy" and 1920 <= Image.open(ppath).width <= 2560,
     (kind_of(ppath), Image.open(ppath).size) if ppath.is_file() else "missing")

# ---- the template's title box and text box decide where text goes --------------------------
area = meta.get("backgrounds", {}).get("content", {}).get("title_area") or {}
t.ok("the title gets an area as tall as the template's title box", 110 <= px(css, "--title-min") <= 140 and token(css, "--title-anchor") == "end",
     token(css, "--title-min") + " " + token(css, "--title-anchor"))
t.ok("the body starts where the template's text box starts", 50 <= px(css, "--title-gap") <= 90 and 60 <= px(css, "--frame-top") <= 95,
     token(css, "--title-gap") + " " + token(css, "--frame-top"))
t.ok("the title may be as wide as its box", 1250 <= px(css, "--title-measure") <= 1340, token(css, "--title-measure"))
t.ok("the rule under the title sets how tall a title may be", 130 <= px(css, "--title-max") <= 150 and area.get("lines") == 2 and area.get("room") == px(css, "--title-max"),
     (token(css, "--title-max"), area))
t.ok("theme.json records the two boxes", len(area.get("box") or []) == 4 and len(meta["backgrounds"]["content"].get("body_area") or []) == 4)
t.ok("the report says how much room a title has", "the template draws something under the title, so a title has room for 2 lines" in rule_report)

proc, band, bcss, bmeta = make("template-band.pptx", "band")
t.ok("a title box on a band stays on the band", 24 <= px(bcss, "--frame-top") <= 60 and token(bcss, "--title-anchor") == "center", token(bcss, "--frame-top"))
t.ok("titles take the color that reads on the band", re.search(r"\.slide:where\(:not\(\[data-tone\], \[data-bg\][^{]*\{ --title-color: #FFFFFF;", bcss) is not None
     and "the title sits on #0B2545 in the template" in proc.stdout, proc.stdout[-500:])
t.ok("body text takes its color from under the text box, not from the band", token(bcss, "--color-text") in ("#000000", "#111111")
     and bmeta["backgrounds"]["content"]["calm"] is True, token(bcss, "--color-text"))

proc, shapes, scss, smeta = make("template-shapes.pptx", "shapes")
t.ok("a template that draws nothing under the title puts no limit on it", token(scss, "--title-max") == "none" and px(scss, "--title-min") > 0, token(scss, "--title-max"))
t.ok("a box that runs a little under artwork at the slide's edge is pulled in, and reported",
     "on the section slide the template's text box runs under artwork along the left edge" in proc.stdout, proc.stdout[-600:])
proc, brand, brcss, brmeta = make("template-brand.pptx", "brand")
t.ok("a layout with no text boxes gets the built-in margins, not a guess from its picture",
     'the "Quote" layout has no title or text box with a position in the template, so the built-in margins are used' in proc.stdout, proc.stdout[-700:])

GEOMETRY = """(id) => {
  const s = document.getElementById(id), sr = s.getBoundingClientRect();
  const title = s.querySelector(':scope > .slide-title'), body = s.querySelector(':scope > .slide-body'), brow = s.querySelector(':scope > .slide-eyebrow');
  const t = title.getBoundingClientRect(), range = document.createRange();
  range.selectNodeContents(title);
  const ink = range.getBoundingClientRect();
  const c = getComputedStyle(title).color.match(/[\\d.]+/g).map(Number);
  return { top: Math.round((brow || title).getBoundingClientRect().top - sr.top), textBottom: Math.round(ink.bottom - sr.top),
           textTop: Math.round(ink.top - sr.top), boxBottom: Math.round(t.bottom - sr.top),
           body: Math.round(body.getBoundingClientRect().top - sr.top), light: (c[0] + c[1] + c[2]) / 3 > 170 };
}"""


def geometry(deck_path, ids):
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(deck_path.as_uri())
        page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck")
        page.evaluate("Deck.rest(true)")
        out = {name: page.evaluate(GEOMETRY, name) for name in ids}
        browser.close()
        return out


RULE_TOP, RULE_BOTTOM = 229, 233                # the rule: 21.2% down, 0.4% tall
rule_deck = OUT / "fidelity-rule.html"
build(DECK, rule_deck, "--theme", "rule", env=ENV)
g = geometry(rule_deck, ("s-one", "s-brow", "s-long"))
t.ok("in the deck, a title sits above the rule and the body below it", g["s-one"]["textBottom"] <= RULE_TOP and g["s-one"]["body"] >= RULE_BOTTOM
     and g["s-one"]["textTop"] > 110, g["s-one"])
t.ok("the title is placed in its area as the template has it: at the bottom", RULE_TOP - g["s-one"]["boxBottom"] < 30, g["s-one"])
t.ok("an eyebrow shares the area: the body starts in the same place", g["s-brow"]["body"] == g["s-one"]["body"] and g["s-brow"]["textBottom"] <= RULE_TOP,
     (g["s-brow"], g["s-one"]["body"]))
proc = run("render.py", rule_deck, "--out", OUT / "fidelity-rule-render", "--json")
report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"slides": []}
told = {s["number"]: [p for p in s["problems"] if "stays above it" in p] for s in report["slides"]}
t.ok("the render check reports the title that runs into the rule, and only that one", [n for n, p in told.items() if p] == [3], told)

BAND_BOTTOM = 216
band_deck = OUT / "fidelity-band.html"
build(DECK, band_deck, "--theme", "band", env=ENV)
g = geometry(band_deck, ("s-one", "s-flat"))
t.ok("in the deck, the title is on the band, in white, and the body is below it", g["s-one"]["light"] and g["s-one"]["textBottom"] < BAND_BOTTOM
     and g["s-one"]["body"] > BAND_BOTTOM, g["s-one"])
t.ok("a flat slide in the same theme keeps a dark title", not g["s-flat"]["light"], g["s-flat"])
proc = run("render.py", band_deck, "--out", OUT / "fidelity-band-render", "--json")
report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"slides": [{"number": 0, "low_contrast": "no report"}]}
low = {s["number"]: s["low_contrast"] for s in report["slides"] if s.get("low_contrast") and s["number"] in (1, 2, 4)}
t.ok("titles and text read well against what is behind them", not low, low)

starter = OUT / "fidelity-brand-starter.html"
build(STARTER_SRC, starter, "--theme", "brand", env=ENV)
proc = run("render.py", starter, "--out", OUT / "fidelity-brand-render", "--no-shots")
t.ok("without a rule or band, two-line titles are not reported", "stays above it" not in proc.stdout, proc.stdout[-400:])

t.done()
