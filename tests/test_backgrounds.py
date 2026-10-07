"""Picture backgrounds: kept from a template, measured once, and obeyed by the slides.

The first half runs with LibreOffice switched off, so it runs everywhere. The
last part draws the templates with LibreOffice and is skipped when it is not
installed. The templates come from tests/fixtures/make_templates.py.
"""
from __future__ import annotations

import json
import re
import shutil

from playwright.sync_api import sync_playwright

from _common import FIXTURES, OUT, STARTER_SRC, Checks, build, launch, run

t = Checks("Picture backgrounds")

lib = OUT / "bg-library"
shutil.rmtree(lib, ignore_errors=True)
NO_LO = {"DYNAMIC_DECKS_HOME": str(lib), "DYNAMIC_DECKS_SOFFICE": "none"}
WITH_LO = {"DYNAMIC_DECKS_HOME": str(lib)}
DECK = FIXTURES / "backgrounds.src.html"


def make(template: str, name: str, env: dict, *args):
    proc = run("add_theme.py", "from-pptx", FIXTURES / template, "--name", name, *args, env=env)
    folder = lib / "themes" / name
    css = (folder / "theme.css").read_text(encoding="utf-8") if (folder / "theme.css").is_file() else ""
    meta = json.loads((folder / "theme.json").read_text(encoding="utf-8")) if (folder / "theme.json").is_file() else {}
    return proc, folder, css, meta


def px(css: str, token: str, block: str = "") -> int:
    """A px token's value; with `block`, from the first rule whose selector mentions it."""
    if block:
        m = re.search(re.escape(block) + r"[^{]*\{([^}]*)\}", css)
        css = m.group(1) if m else ""
    m = re.search(re.escape(token) + r":\s*(-?\d+)px", css)
    return int(m.group(1)) if m else -1


# ---- a picture background, without LibreOffice --------------------------------
proc, photo, css, meta = make("template-photo.pptx", "photo", NO_LO)
bgs = meta.get("backgrounds", {})
t.ok("a template with a picture background becomes a theme", proc.returncode == 0 and bool(css), proc.stdout[-400:] + proc.stderr[-400:])
t.ok("the content picture is kept in the theme, declared once and used by name", (photo / "backgrounds" / "content.webp").is_file()
     and '--bg-content: url("backgrounds/content.webp")' in css and "--bg-image: var(--bg-content)" in css
     and css.count('url("backgrounds/content.webp")') == 1)
t.ok("the margins keep text off the artwork", px(css, "--frame-right") >= 700 and 64 <= px(css, "--frame-left") <= 160,
     f"left {px(css, '--frame-left')} right {px(css, '--frame-right')}")
content = bgs.get("content", {})
t.ok("the picture is measured once: text area, text color, calm or busy",
     content.get("ink") == "dark" and content.get("calm") is True and len(content.get("safe") or []) == 4 and content.get("panel") is None, content)
t.ok("it is described in a sentence for composing by hand", "right third" in content.get("description", "") and "dark text" in content.get("description", ""))
t.ok("the title slide keeps its own picture, with light text", bgs.get("title", {}).get("ink") == "light"
     and (photo / "backgrounds" / "title.webp").is_file() and '.slide[data-bg="title"]' in css)
t.ok("a flat section slide stays a flat color", bgs.get("section") == {"flat": "#0E7C86"} and "--color-inverse-bg: #0E7C86" in css)
t.ok("a theme on a picture has one look", meta.get("variants") == ["light"] and "no automatic dark version" in proc.stdout)
t.ok("the report says what was done and what to review", "Backgrounds kept as pictures" in proc.stdout
     and "LibreOffice is not installed" in proc.stdout and "of width for text" in proc.stdout)
proc = run("add_theme.py", "check", "photo", env=NO_LO)
t.ok("the theme passes the theme check", proc.returncode == 0, proc.stdout[-300:])

# ---- a gradient, and artwork made of shapes, without LibreOffice --------------
proc, shapes, css, meta = make("template-shapes.pptx", "shapes-plain", NO_LO)
title = meta.get("backgrounds", {}).get("title", {})
t.ok("a simple gradient is kept as code, not as a picture", "--bg-image: linear-gradient(135deg, #C8102E 0%, #5A0613 100%)" in css
     and not (shapes / "backgrounds").exists(), title)
t.ok("the report says shape artwork needs LibreOffice", "artwork made of shapes was left out" in proc.stdout and "left out" in title.get("description", ""))
t.ok("with flat content slides the theme keeps its dark variant and the logo", meta.get("variants") == ["light", "dark"] and (shapes / "logo.png").is_file())

# ---- a background too busy to read over ----------------------------------------
proc, busy, css, meta = make("template-busy.pptx", "busy", NO_LO)
bgs = meta.get("backgrounds", {})
t.ok("a busy picture gets a panel behind the text", bgs.get("content", {}).get("calm") is False and re.search(r"--bg-panel: rgb\(\d+ \d+ \d+ / 0\.\d+\)", css) is not None)
t.ok("every kind of slide on the same picture uses the same text color", len({e.get("ink") for e in bgs.values()}) == 1, {k: e.get("ink") for k, e in bgs.items()})
t.ok("the same picture is stored once", [f.name for f in (busy / "backgrounds").glob("*")] == ["content.webp"])
hero = bgs.get("title", {}).get("safe") or [0, 0, 0, 0]
t.ok("the title slide's panel is big enough for a title", hero[2] >= 1100 and hero[3] >= 700, hero)
t.ok("the report mentions the panel", "panel behind the text" in proc.stdout)

# ---- more layouts as named backgrounds, without LibreOffice ------------------------
proc, brand, css, meta = make("template-brand.pptx", "brand", NO_LO)
bgs = meta.get("backgrounds", {})
t.ok("a layout with its own flat color becomes a named background", bgs.get("dark-content", {}).get("flat") == "#1B1B1B"
     and bgs["dark-content"].get("extra") is True and bgs["dark-content"].get("from") == "Dark Content", bgs.get("dark-content"))
t.ok("a layout with its own gradient becomes one too", bgs.get("quote", {}).get("picture", "").startswith("linear-gradient(120deg, #0B2545")
     and bgs["quote"].get("ink") == "light", bgs.get("quote"))
t.ok("layouts that look like the content one are not listed", set(bgs) == {"content", "title", "section", "dark-content", "quote"}
     or set(bgs) == {"dark-content", "quote", "content"} or {k for k, e in bgs.items() if e.get("extra")} == {"dark-content", "quote"}, sorted(bgs))
rule_dark = re.search(r'\.slide\[data-bg="dark-content"\]:where\(:not\(\[data-tone\]\)\) \{([^}]*)\}', css)
t.ok("each gets a rule with the colors that read on it", rule_dark is not None and "--color-bg: #1B1B1B" in rule_dark.group(1)
     and "--color-text: #FFFFFF" in rule_dark.group(1) and "--title-color: var(--color-text)" in rule_dark.group(1))
t.ok("the report names them for the slides to ask for", 'data-bg="dark-content", data-bg="quote"' in proc.stdout
     and 'Flat backgrounds from other layouts: data-bg="dark-content"' in proc.stdout, proc.stdout[-600:])
t.ok("the two-content layout's gap is carried", "--column-gap: 106px" in css, re.findall(r"--column-gap: [^;]+", css))
proc, lean_theme, css, meta = make("template-brand.pptx", "brand-four", NO_LO, "--no-extra-backgrounds")
t.ok("--no-extra-backgrounds keeps to the four kinds of slide", proc.returncode == 0 and 'data-bg="quote"' not in css and "backgrounds" not in meta, sorted(meta))

# ---- switches -------------------------------------------------------------------
proc, never, css, meta = make("template-photo.pptx", "photo-flat", NO_LO, "--backgrounds", "never")
t.ok("--backgrounds never gives a flat theme", proc.returncode == 0 and "backgrounds" not in meta and not (never / "backgrounds").exists()
     and 'url("backgrounds/' not in css and "data-bg" not in css and meta.get("variants") == ["light", "dark"], proc.stdout[-300:])
proc, flat, css, meta = make("template.pptx", "flat", NO_LO)
t.ok("a template with a flat background is unchanged by all this", "backgrounds" not in meta and not (flat / "backgrounds").exists()
     and meta.get("variants") == ["light", "dark"] and (flat / "logo.png").is_file())

# ---- pictures supplied by hand ---------------------------------------------------
from PIL import Image, ImageDraw  # noqa: E402

art = OUT / "supplied.png"
im = Image.new("RGB", (1600, 1200), "#101828")
draw = ImageDraw.Draw(im)
for i in range(40):
    draw.ellipse((900 + i * 14, 200 + i * 9, 1500 + i * 4, 900), outline=(80, 200, 255), width=3)
im.save(art)
proc = run("add_theme.py", "new", "--name", "supplied", "--accent", "#2B6CF0", "--background", f"content={art}",
           "--background", f"poster={art}", env=NO_LO)
sup = lib / "themes" / "supplied"
css = (sup / "theme.css").read_text(encoding="utf-8") if (sup / "theme.css").is_file() else ""
meta = json.loads((sup / "theme.json").read_text(encoding="utf-8")) if (sup / "theme.json").is_file() else {}
t.ok("a picture can be supplied with --background", proc.returncode == 0 and (sup / "backgrounds" / "content.webp").is_file(), proc.stdout[-300:] + proc.stderr[-300:])
t.ok("its empty part becomes the text area", 64 <= px(css, "--frame-left") <= 160 and px(css, "--frame-right") >= 500,
     f"left {px(css, '--frame-left')} right {px(css, '--frame-right')}")
t.ok("text and background colors come from the picture", meta.get("backgrounds", {}).get("content", {}).get("ink") == "light" and meta.get("variants") == ["dark"])
t.ok("a picture that is not 16:9 is cropped and reported", "cropped to fit" in proc.stdout)
t.ok("an unknown kind of slide is reported, not used", "'poster' is not a kind of slide" in proc.stdout)
(sup / "backgrounds" / "content.webp").unlink()
proc = run("add_theme.py", "check", "supplied", env=NO_LO)
t.ok("the theme check notices a missing picture", proc.returncode != 0 and "content.webp" in proc.stdout, proc.stdout[-300:])

# ---- decks built in these themes -------------------------------------------------
deck = OUT / "bg-photo.html"
proc = build(DECK, deck, "--theme", "photo", env=NO_LO)
html = deck.read_text(encoding="utf-8") if deck.is_file() else ""
t.ok("a deck builds in a picture theme", proc.returncode == 0, proc.stdout[-400:] + proc.stderr[-300:])
t.ok("the pictures travel inside the file", html.count("data:image/webp;base64,") >= 2 and 'url("backgrounds/' not in html and "url(backgrounds/" not in html)
proc = run("unpack.py", deck, "-o", OUT / "bg-photo.src.html", "--theme-to", OUT / "bg-recovered")
again = OUT / "bg-photo-again.html"
proc2 = build(DECK, again, "--theme", OUT / "bg-recovered", env=NO_LO)
t.ok("a theme recovered from a deck still carries its pictures", proc.returncode == 0 and proc2.returncode == 0
     and again.read_text(encoding="utf-8").count("data:image/webp;base64,") >= 2, proc.stdout[-200:] + proc2.stdout[-200:])
busy_deck = OUT / "bg-busy.html"
proc = build(DECK, busy_deck, "--theme", "busy", env=NO_LO)
t.ok("a picture shared by several kinds of slide is in the deck once", busy_deck.read_text(encoding="utf-8").count("data:image/webp;base64,") == 1)

plain = OUT / "bg-content-only.src.html"
source = DECK.read_text(encoding="utf-8")
keep = [m for m in re.findall(r"<section.*?</section>", source, flags=re.S) if 'id="s-content"' in m or 'id="s-none"' in m]
plain.write_text(re.sub(r"<section.*</section>", "\n".join(keep), source, flags=re.S), encoding="utf-8")
lean = OUT / "bg-content-only.html"
proc = build(plain, lean, "--theme", "photo", env=NO_LO)
html = lean.read_text(encoding="utf-8") if lean.is_file() else ""
t.ok("a deck with no title slide leaves the title picture out", proc.returncode == 0 and html.count("data:image/webp;base64,") == 1
     and "--bg-title: none" in html.replace(":none", ": none") and "not used by this deck and were left out: title" in proc.stdout, proc.stdout[-400:])
t.ok("and is smaller for it", lean.stat().st_size < deck.stat().st_size - 20000, (lean.stat().st_size, deck.stat().st_size))
titled = OUT / "bg-title-later-in.html"             # the built deck, edited, rebuilt where its theme is not installed
titled.write_text(html.replace('data-bg="none"', 'data-bg="title"'), encoding="utf-8")
proc = build(titled, OUT / "bg-title-later.html", env={**NO_LO, "DYNAMIC_DECKS_HOME": str(OUT / "no-such-library")})
t.ok("asking later for a picture the deck left out is explained", "the picture for it was left out" in proc.stdout, proc.stdout[-500:])
odd = OUT / "bg-unknown.src.html"
odd.write_text(source.replace('data-bg="none"', 'data-bg="poster"'), encoding="utf-8")
proc = build(odd, OUT / "bg-unknown.html", "--theme", "photo", env=NO_LO)
t.ok("a background the theme does not have is reported by name", 'data-bg="poster" is not a background in the theme' in proc.stdout, proc.stdout[-400:])

STATE = """(id) => {
  const s = document.getElementById(id), cs = getComputedStyle(s), panel = getComputedStyle(s, '::before');
  const title = s.querySelector('.slide-title');
  const light = (c) => { const m = c.match(/[\\d.]+/g).map(Number); return (m[0] * 0.2126 + m[1] * 0.7152 + m[2] * 0.0722) > 140; };
  return { image: cs.backgroundImage, picture: cs.backgroundImage.slice(0, 96), panel: panel.backgroundColor,
           lightText: light(getComputedStyle(title).color), left: title.getBoundingClientRect().left, right: title.getBoundingClientRect().right,
           pad: cs.paddingLeft + ' ' + cs.paddingRight };
}"""

with sync_playwright() as p:
    browser = launch(p)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(deck.as_uri())
    page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck")
    page.evaluate("Deck.rest(true)")
    s = {name: page.evaluate(STATE, name) for name in ("s-title", "s-content", "s-tone", "s-none", "s-optin", "s-over", "s-closing")}
    t.ok("content slides show the content picture", s["s-content"]["image"].startswith("url(") and not s["s-content"]["lightText"])
    t.ok("their text stays in the text area", s["s-content"]["right"] <= 1920 - 700 + 2, s["s-content"]["right"])
    t.ok("the title slide shows a different picture, with light text", s["s-title"]["image"].startswith("url(")
         and s["s-title"]["image"] != s["s-content"]["image"] and s["s-title"]["lightText"])
    t.ok("the closing slide shares the title picture", s["s-closing"]["image"] == s["s-title"]["image"])
    t.ok("a slide with a tone of its own shows no picture", s["s-tone"]["image"] == "none")
    t.ok('data-bg="none" shows no picture', s["s-none"]["image"] == "none")
    t.ok('data-bg="title" puts a content slide on the title picture, with its colors and margins',
         s["s-optin"]["image"] == s["s-title"]["image"] and s["s-optin"]["lightText"] and s["s-optin"]["pad"] == s["s-title"]["pad"],
         (s["s-optin"]["pad"], s["s-title"]["pad"]))
    t.ok("a calm picture has no panel", s["s-content"]["panel"] in ("rgba(0, 0, 0, 0)", "transparent"), s["s-content"]["panel"])

    page.goto(busy_deck.as_uri())
    page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck")
    page.evaluate("Deck.rest(true)")
    b = page.evaluate(STATE, "s-content")
    alpha = re.search(r"rgba\(\d+, \d+, \d+, ([\d.]+)\)", b["panel"])
    t.ok("a busy picture has a panel behind the text", alpha is not None and 0.7 <= float(alpha.group(1)) < 1, b["panel"])
    t.ok("a slide with a tone of its own has no panel either", page.evaluate(STATE, "s-tone")["panel"] in ("rgba(0, 0, 0, 0)", "transparent"))
    browser.close()

# ---- the render check compares text with the pixels behind it ------------------------
proc = run("render.py", deck, "--out", OUT / "bg-photo-render", "--json")
report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"slides": []}
flagged = {s["number"]: s.get("low_contrast", []) for s in report["slides"] if s.get("low_contrast")}
t.ok("text pushed onto the artwork is flagged", list(flagged) == [6] and "pushed onto the picture" in flagged[6][0]["text"], flagged or proc.stdout[-300:] + proc.stderr[-300:])
t.ok("the report gives the contrast it measured, and says the patch is busy", bool(flagged.get(6)) and flagged[6][0]["contrast"] < 4.5
     and flagged[6][0]["busy_behind"] is True, flagged.get(6))
proc = run("render.py", busy_deck, "--out", OUT / "bg-busy-render", "--json")
report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"slides": [{"low_contrast": "no report"}]}
low = {s["number"]: s["low_contrast"] for s in report["slides"] if s.get("low_contrast") and s["number"] != 6}
t.ok("text on a panel over a busy picture reads well", not low, low)
proc = run("render.py", deck, "--out", OUT / "bg-photo-render", "--no-contrast", "--no-shots")
t.ok("--no-contrast skips the comparison", "hard to read against" not in proc.stdout)

# ---- drawn by LibreOffice -----------------------------------------------------------
import sys  # noqa: E402

sys.path.insert(0, str((FIXTURES.parent.parent / "dynamic-decks" / "scripts")))
import _backgrounds  # noqa: E402

if not _backgrounds.soffice():
    print("  skip  LibreOffice is not installed: the templates were not drawn")
    t.done()

proc, shapes, css, meta = make("template-shapes.pptx", "shapes", WITH_LO)
bgs = meta.get("backgrounds", {})
t.ok("LibreOffice draws artwork made of shapes", proc.returncode == 0 and bgs.get("content", {}).get("drawn_by_libreoffice") is True
     and (shapes / "backgrounds" / "content.webp").is_file(), proc.stdout[-400:] + proc.stderr[-300:])
if (shapes / "backgrounds" / "content.webp").is_file():
    pic = Image.open(shapes / "backgrounds" / "content.webp").convert("RGB")
    band, paper, strip = pic.getpixel((120, 1000)), pic.getpixel((1800, 1000)), pic.getpixel((1800, 2140))
    t.ok("the picture has the template's band, strip and paper", band[0] > 170 and band[1] < 60 and min(paper) > 240 and max(strip) < 60, (band, paper, strip))
    t.ok("it is drawn at twice the stage size", pic.size == (3840, 2160), pic.size)
t.ok("the text area starts clear of the band", px(css, "--frame-left") >= 190, px(css, "--frame-left"))
t.ok("the logo is part of the picture, not placed twice", not (shapes / "logo.png").exists() and meta.get("logo") is None)
t.ok("the title slide is drawn with its own shapes", bgs.get("title", {}).get("drawn_by_libreoffice") is True and (shapes / "backgrounds" / "title.webp").is_file())
t.ok("a section number sits on its title on a picture", "--section-number-gap" in css)

proc, drawn, css, meta = make("template-photo.pptx", "photo-drawn", WITH_LO)
t.ok("a picture background is drawn too", meta.get("backgrounds", {}).get("content", {}).get("drawn_by_libreoffice") is True and px(css, "--frame-right") >= 700)
proc, small, css, meta = make("template.pptx", "flat-drawn", WITH_LO)
t.ok("a flat template drawn by LibreOffice is still a flat theme", "backgrounds" not in meta and meta.get("variants") == ["light", "dark"] and (small / "logo.png").is_file(),
     proc.stdout[-300:])
proc, kept, css, meta = make("template.pptx", "flat-kept", WITH_LO, "--backgrounds", "always")
t.ok("--backgrounds always is accepted", proc.returncode == 0, proc.stdout[-300:] + proc.stderr[-300:])

proc, brand, css, meta = make("template-brand.pptx", "brand-drawn", WITH_LO)
bgs = meta.get("backgrounds", {})
side = bgs.get("sidebar", {})
t.ok("a layout with its own artwork is drawn and named", side.get("drawn_by_libreoffice") is True and side.get("extra") is True
     and (brand / "backgrounds" / "sidebar.webp").is_file() and '--bg-sidebar: url("backgrounds/sidebar.webp")' in css, sorted(bgs))
t.ok("its text area keeps clear of its artwork", bool(side.get("safe")) and side["safe"][0] + side["safe"][2] <= 0.72 * 1920 + 2, side.get("safe"))
t.ok("the eight layouts that look like the content one add nothing", {k for k, e in bgs.items() if e.get("extra")} == {"dark-content", "quote", "sidebar"},
     sorted(bgs))
more_deck = OUT / "bg-more.html"
more_src = OUT / "bg-more.src.html"
more_src.write_text(DECK.read_text(encoding="utf-8").replace('data-bg="none" id="s-none"', 'data-bg="sidebar" id="s-none"')
                    .replace('data-bg="title" id="s-optin"', 'data-bg="dark-content" id="s-optin"'), encoding="utf-8")
proc = build(more_src, more_deck, "--theme", "brand-drawn", env=WITH_LO)
with sync_playwright() as p:
    browser = launch(p)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(more_deck.as_uri())
    page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck")
    page.evaluate("Deck.rest(true)")
    side_slide, dark_slide, plain_slide = (page.evaluate(STATE, name) for name in ("s-none", "s-optin", "s-content"))
    bg_color = page.evaluate("getComputedStyle(document.getElementById('s-optin')).backgroundColor")
    t.ok('data-bg="sidebar" shows that layout\'s picture and keeps text off the band', side_slide["image"].startswith("url(")
         and side_slide["right"] <= 0.72 * 1920 + 2 and plain_slide["image"] == "none", (side_slide["picture"][:30], side_slide["right"]))
    t.ok('data-bg="dark-content" gives a dark slide with light text', bg_color == "rgb(27, 27, 27)" and dark_slide["lightText"], bg_color)
    browser.close()
proc = run("render.py", more_deck, "--out", OUT / "bg-more-render", "--json")
report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"slides": [{"number": 0, "low_contrast": "no report"}]}
low = {s["number"]: s["low_contrast"] for s in report["slides"] if s.get("low_contrast") and s["number"] != 6}
t.ok("text reads well on every one of them", not low, low)

starter = OUT / "bg-starter-shapes.html"
proc = build(STARTER_SRC, starter, "--theme", "shapes", env=WITH_LO)
t.ok("the starter deck builds in a drawn theme", proc.returncode == 0, proc.stdout[-300:] + proc.stderr[-300:])
proc = run("add_theme.py", "check", "shapes", env=WITH_LO)
t.ok("the drawn theme passes the theme check", proc.returncode == 0, proc.stdout[-300:])

t.done()
