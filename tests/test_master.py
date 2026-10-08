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
import zipfile

from playwright.sync_api import sync_playwright

from _common import FIXTURES, OUT, STARTER_SRC, Checks, build, launch, run

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

def rule(css: str, kind: str) -> str:
    """The one-line Decor rule a kind of slide gets for what its layout sets."""
    m = re.search(r'(?m)^\.slide\[data-layout="' + kind + r'"\] \{ ([^}]*)\}', css)
    return m.group(1) if m else ""


def open_deck(p, deck):
    browser = launch(p)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(deck.as_uri())
    page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck")
    page.evaluate("Deck.rest(true)")
    return browser, page


# ---- title alignment -------------------------------------------------------------
proc, brand, css, meta = make("template-brand.pptx", "brand-align")
t.ok("content titles follow the master's title style", token(css, "--title-align") == "start", token(css, "--title-align"))
t.ok("the title slide follows its own layout", "--title-align: center" in rule(css, "title"), rule(css, "title"))
t.ok("the title slide's text sits where its boxes are, top to bottom", "--hero-justify: center" in rule(css, "title"))
t.ok("a kind that matches the content slides gets no rule", rule(css, "section") == "", rule(css, "section"))
t.ok("the report says how titles align", "content slides left, title slides centered" in proc.stdout)
proc, flat, css, meta = make("template.pptx", "default-master")
t.ok("PowerPoint's default master centers titles, and the theme follows", token(css, "--title-align") == "center"
     and "--title-align: start" in rule(css, "section"), token(css, "--title-align") + " / " + rule(css, "section"))
proc, forced, css, meta = make("template.pptx", "forced-left", "--title-align", "left")
t.ok("--title-align overrides the template for every kind of slide", token(css, "--title-align") == "start" and "--title-align" not in rule(css, "section"))
proc = run("add_theme.py", "new", "--name", "centered", "--accent", "#2B6CF0", "--title-align", "center", env=ENV)
css = (lib / "themes" / "centered" / "theme.css").read_text(encoding="utf-8")
t.ok("a theme from brand values can ask for an alignment", proc.returncode == 0 and token(css, "--title-align") == "center")

ALIGNED = """() => Deck.slides.map((s) => {
  const title = s.querySelector(':scope > .slide-title'), eyebrow = s.querySelector(':scope > .slide-eyebrow');
  const r = title ? title.getBoundingClientRect() : null, sr = s.getBoundingClientRect();
  return { layout: s.dataset.layout || '', align: title ? getComputedStyle(title).textAlign : '',
           mid: r ? Math.round((r.left + r.right) / 2 - sr.left) : 0, middle: r ? Math.round((r.top + r.bottom) / 2 - sr.top) : 0,
           eyebrow: eyebrow ? getComputedStyle(eyebrow).textAlign : '' };
})"""
deck = OUT / "master-brand.html"
build(STARTER_SRC, deck, "--theme", "brand-align", env=ENV)
centered = OUT / "master-centered.html"
build(STARTER_SRC, centered, "--theme", "default-master", env=ENV)
with sync_playwright() as p:
    browser, page = open_deck(p, deck)
    slides = page.evaluate(ALIGNED)
    first, bullets = slides[0], next(s for s in slides if s["layout"] == "bullets")
    t.ok("in the deck, the title slide is centered left to right and top to bottom",
         first["align"] == "center" and abs(first["mid"] - 960) < 12 and 380 < first["middle"] < 640, first)
    t.ok("and content titles stay left", bullets["align"] == "start" and bullets["mid"] < 900, bullets)
    browser.close()
    browser, page = open_deck(p, centered)
    slides = page.evaluate(ALIGNED)
    bullets, number = next(s for s in slides if s["layout"] == "bullets"), next(s for s in slides if s["layout"] == "big-number")
    section = next(s for s in slides if s["layout"] == "section")
    t.ok("a centered master centers content titles", bullets["align"] == "center" and abs(bullets["mid"] - 960) < 12, bullets)
    t.ok("an eyebrow with no title under it stays with its content", number["eyebrow"] == "start", number)
    t.ok("a layout that sets its own alignment keeps it", section["align"] == "start" and section["mid"] < 900, section)
    browser.close()

# ---- footer and slide number ---------------------------------------------------------
proc, brand, css, meta = make("template-brand.pptx", "brand-footer")
t.ok("the footer's text size and color come from the master", token(css, "--footer-size") == "20px" and token(css, "--footer-color") == "#6B6B6B",
     token(css, "--footer-size") + " " + token(css, "--footer-color"))
t.ok("the number and the label are placed as in the template", ".slide-footer > .slide-number { order: 1; margin-left: 0; }" in css
     and ".slide-footer > .slide-footer-text { position: absolute; left: 50%;" in css)
t.ok("both are shown when the template shows them", token(css, "--footer-label") == "block" and token(css, "--footer-number") == "block")
t.ok("the report says how the footer was arranged", "the footer follows the template: slide number left and label center, 20px text" in proc.stdout)
proc, m, css, meta = make("template-masters.pptx", "masters-footer")
t.ok("a deck whose slides show no number gets a theme that hides it", token(css, "--footer-number") == "none"
     and "the slide number is hidden because none of its 3 slides shows one" in proc.stdout, token(css, "--footer-number"))
proc, m, css, meta = make("template-masters.pptx", "masters-footer-on", "--slide-number", "right", "--footer-label", "left")
t.ok("--slide-number and --footer-label override the template", token(css, "--footer-number") == "block" and token(css, "--footer-label") == "block"
     and "is hidden" not in proc.stdout)

import zipfile  # noqa: E402

switched = OUT / "template-number-off.pptx"
with zipfile.ZipFile(FIXTURES / "template-brand.pptx") as zin, zipfile.ZipFile(switched, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.namelist():
        data = zin.read(item)
        if item == "ppt/slideMasters/slideMaster1.xml":
            data = data.replace(b'<p:hf dt="0"/>', b'<p:hf sldNum="0" dt="0"/>')
        zout.writestr(item, data)
proc = run("add_theme.py", "from-pptx", switched, "--name", "number-off", env=ENV)
css = (lib / "themes" / "number-off" / "theme.css").read_text(encoding="utf-8")
t.ok("a slide number switched off on the master is hidden, and the label stays", token(css, "--footer-number") == "none"
     and token(css, "--footer-label") == "block" and "switched off on the slide master" in proc.stdout, proc.stdout[-400:])
proc = run("add_theme.py", "new", "--name", "foot-new", "--accent", "#2B6CF0", "--slide-number", "left", "--footer-label", "off", env=ENV)
css = (lib / "themes" / "foot-new" / "theme.css").read_text(encoding="utf-8")
t.ok("a theme from brand values can place or hide them too", token(css, "--footer-label") == "none"
     and ".slide-footer > .slide-number { order: 1; margin-left: 0; }" in css, proc.stdout[-300:])

FOOTER = """() => {
  const s = Deck.slides.find((x) => x.dataset.layout === 'bullets'), f = s.querySelector(':scope > .slide-footer');
  const at = (sel) => { const e = f.querySelector(sel), r = e.getBoundingClientRect(), sr = s.getBoundingClientRect();
    return { shown: getComputedStyle(e).display !== 'none', mid: Math.round((r.left + r.right) / 2 - sr.left) }; };
  return { number: at('.slide-number'), label: at('.slide-footer-text'), size: getComputedStyle(f).fontSize };
}"""
deck = OUT / "master-footer.html"
build(STARTER_SRC, deck, "--theme", "brand-footer", env=ENV)
hidden = OUT / "master-footer-hidden.html"
build(STARTER_SRC, hidden, "--theme", "masters-footer", env=ENV)
with sync_playwright() as p:
    browser, page = open_deck(p, deck)
    f = page.evaluate(FOOTER)
    t.ok("in the deck, the number is on the left and the label in the middle", f["number"]["mid"] < 500 and abs(f["label"]["mid"] - 960) < 6, f)
    t.ok("and the footer text has the template's size", f["size"] == "20px", f["size"])
    browser.close()
    browser, page = open_deck(p, hidden)
    f = page.evaluate(FOOTER)
    t.ok("a hidden number and label are not drawn", not f["number"]["shown"] and not f["label"]["shown"], f)
    browser.close()

# ---- bullets -----------------------------------------------------------------------------
proc, brand, css, meta = make("template-brand.pptx", "brand-bullets")
t.ok("a square bullet in the brand color is carried", token(css, "--bullet-width") == "0.3em" and token(css, "--bullet-height") == "0.3em"
     and token(css, "--bullet-radius") == "0px" and token(css, "--bullet-color") == "#C8102E", token(css, "--bullet-radius") + " " + token(css, "--bullet-color"))
t.ok("the second level's dash is carried", token(css, "--bullet-2-width") == "0.5em" and token(css, "--bullet-2-height") == "var(--stroke-thin)")
t.ok("the indent comes from the template", token(css, "--bullet-indent") == "45px", token(css, "--bullet-indent"))
t.ok("the report says what the bullets are", "bullets follow the template: level 1 a square in #C8102E, level 2 a dash" in proc.stdout)
t.ok("a fixed bullet color is checked against the dark variant too", token(css, "--bullet-color", ':root[data-variant="dark"]').startswith("#"))
proc, flat, css, meta = make("template.pptx", "default-bullets")
t.ok("PowerPoint's default dot takes the text color", token(css, "--bullet-radius") == "var(--radius-pill)" and token(css, "--bullet-width") == "0.3em"
     and token(css, "--bullet-color") == "var(--color-text)", token(css, "--bullet-color"))
proc, forced, css, meta = make("template.pptx", "forced-bullets", "--bullet", "dash")
t.ok("--bullet overrides the template", token(css, "--bullet-width") == "0.5em", token(css, "--bullet-width"))
proc = run("add_theme.py", "new", "--name", "no-bullets", "--accent", "#2B6CF0", "--bullet", "none", env=ENV)
css = (lib / "themes" / "no-bullets" / "theme.css").read_text(encoding="utf-8")
t.ok("a theme can have no bullets at all", token(css, "--bullet-width") == "0px" and token(css, "--bullet-indent") == "0px")
proc = run("add_theme.py", "new", "--name", "plain", "--accent", "#2B6CF0", env=ENV)
css = (lib / "themes" / "plain" / "theme.css").read_text(encoding="utf-8")
t.ok("a theme that says nothing keeps the built-in dash", token(css, "--bullet-width") == "var(--space-4)" and token(css, "--bullet-color") == "var(--color-accent)")

import sys  # noqa: E402

sys.path.insert(0, str(FIXTURES.parent.parent / "dynamic-decks" / "scripts"))
import _master  # noqa: E402

shape = _master._bullet_shape
t.ok("symbol-font bullets are read as the shapes they draw",
     shape("\u00a7", "Wingdings")[0] == "square" and shape("\uf0a7", "Wingdings")[0] == "square" and shape("\uf0b7", "Symbol")[0] == "dot"
     and shape("o", "Courier New")[0] == "dot" and shape("\u00d8", "Wingdings")[:2] == ("char", "\u27a2"))
t.ok("an ordinary character is kept as a character", shape("\u2192", "Arial") == ("char", "\u2192", True))
t.ok("a symbol nobody can name falls back to a dot and says so", shape("\uf0e3", "Wingdings") == ("dot", None, False))

BULLET = """() => {
  const li = Deck.slides.find((x) => x.dataset.layout === 'bullets').querySelector('.slide-body ul > li');
  const b = getComputedStyle(li, '::before'), r = (v) => Math.round(parseFloat(v));
  return { width: r(b.width), height: r(b.height), radius: b.borderTopLeftRadius, color: b.backgroundColor, pad: r(getComputedStyle(li).paddingLeft) };
}"""
deck = OUT / "master-bullets.html"
build(STARTER_SRC, deck, "--theme", "brand-bullets", env=ENV)
with sync_playwright() as p:
    browser, page = open_deck(p, deck)
    b = page.evaluate(BULLET)
    t.ok("in the deck, bullets are red squares at the template's indent",
         b["width"] == b["height"] and 8 <= b["width"] <= 18 and b["radius"] == "0px" and b["color"] == "rgb(200, 16, 46)" and b["pad"] == 45, b)
    browser.close()

# ---- body text ---------------------------------------------------------------------------
def with_body_size(points: int):
    """The brand template with another first-level body size."""
    out = OUT / f"template-body-{points}.pptx"
    with zipfile.ZipFile(FIXTURES / "template-brand.pptx") as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "ppt/slideMasters/slideMaster1.xml":
                data = data.replace(b'<a:defRPr sz="2400" kern="1200">', f'<a:defRPr sz="{points * 100}" kern="1200">'.encode())
            zout.writestr(item, data)
    return out


proc, brand, css, meta = make("template-brand.pptx", "brand-body")
t.ok("body text in the usual range leaves the type scale alone", token(css, "--text-md") == "44px" and token(css, "--text-base") == "36px"
     and "body text in the template is 24pt; the theme keeps its own text sizes" in proc.stdout, token(css, "--text-md"))
t.ok("line spacing follows the template", token(css, "--leading-snug") == "1.10" and token(css, "--leading-normal") == "1.28"
     and "line spacing follows the template (90% of single)" in proc.stdout, token(css, "--leading-snug"))
proc = run("add_theme.py", "from-pptx", with_body_size(18), "--name", "body-small", env=ENV)
css = (lib / "themes" / "body-small" / "theme.css").read_text(encoding="utf-8")
t.ok("a template with small body text makes the theme's text 10% smaller, no more",
     [token(css, n) for n in ("--text-sm", "--text-base", "--text-md", "--text-lg")] == ["27px", "32px", "40px", "49px"]
     and "reduced by 10%" in proc.stdout and "the most the layouts allow" in proc.stdout, token(css, "--text-md"))
t.ok("display sizes and the smallest size are not touched", token(css, "--text-xs") == "24px" and token(css, "--text-display") == "164px")
proc = run("add_theme.py", "from-pptx", with_body_size(22), "--name", "body-22", env=ENV)
css = (lib / "themes" / "body-22" / "theme.css").read_text(encoding="utf-8")
t.ok("a template a little under the range leans a little", token(css, "--text-md") == "40px" and "reduced by 8%" in proc.stdout, token(css, "--text-md"))
proc = run("add_theme.py", "from-pptx", with_body_size(40), "--name", "body-large", env=ENV)
css = (lib / "themes" / "body-large" / "theme.css").read_text(encoding="utf-8")
t.ok("a template with large body text makes the theme's text 10% larger, no more", token(css, "--text-md") == "48px" and "increased by 10%" in proc.stdout,
     token(css, "--text-md"))
proc, flat, css, meta = make("template.pptx", "default-body")
t.ok("a template that sets no line spacing keeps the built-in one", token(css, "--leading-snug") == "1.22" and "line spacing" not in proc.stdout)

# ---- a template built the way real ones are: layouts with no type, a title that is not a title placeholder ----
proc, custom, css, meta = make("template-custom.pptx", "custom")
out = proc.stdout
t.ok("layouts that do not say what they are for are matched by name", proc.returncode == 0
     and 'content slides from "Title and Content" (its name says so)' in out and 'title slides from "Title Slide"' in out, out[-600:])
t.ok("the import is not reported as incomplete", "IMPORT INCOMPLETE" not in out and "no ordinary content layout" not in out)
t.ok("the theme is recorded under its own name", meta.get("name") == "custom" and "THEME: custom" in css, meta.get("name"))
t.ok("a text placeholder named Title is read as the title: its size and weight", token(css, "--title-size") == "56px" and token(css, "--title-weight") == "700",
     token(css, "--title-size") + " " + token(css, "--title-weight"))
t.ok("and it is not mistaken for the body: bullets and body size come from the text box", token(css, "--bullet-radius") == "var(--radius-pill)"
     and token(css, "--bullet-width") == "0.3em" and "body text in the template is 18pt" in out, token(css, "--bullet-width"))
title_rule = re.search(r'\.slide\[data-bg="title"\][^{]*\{([^}]*)\}', css)
t.ok("title slides keep the template's own color pairing, white on its orange", title_rule is not None
     and "--color-inverse-bg: #F58220" in title_rule.group(1) and "--color-inverse-text: #FFFFFF" in title_rule.group(1),
     title_rule.group(1)[:300] if title_rule else "no rule")
t.ok("the report gives the contrast of that pairing and says why it was kept", "the template sets #FFFFFF text on #F58220, which is 2.6:1" in out
     and "It was kept because the template sets it" in out)
t.ok("the render check is told not to report it", title_rule is not None and "--contrast-floor: 2.2" in title_rule.group(1))

anon = OUT / "template-anonymous.pptx"             # the same template with layout names that say nothing
with zipfile.ZipFile(FIXTURES / "template-custom.pptx") as zin, zipfile.ZipFile(anon, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.namelist():
        data = zin.read(item)
        if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", item):
            number = re.search(r"(\d+)\.xml", item).group(1)
            data = re.sub(rb'<p:cSld name="[^"]*"', f'<p:cSld name="Custom Layout {number}"'.encode(), data)
        zout.writestr(item, data)
proc = run("add_theme.py", "from-pptx", anon, "--name", "anonymous", env=ENV)
t.ok("with no type and no telling name, the content layout is found by what is on it and how much it is used",
     'content slides from "Custom Layout 2" (it has a title and one text box, and most slides use it)' in proc.stdout, proc.stdout[-700:])
proc = run("add_theme.py", "from-pptx", anon, "--name", "picked", "--layout", "content=Custom Layout 4", "--layout", "title=1", env=ENV)
t.ok("--layout names the layout for a kind of slide, by name or number", proc.returncode == 0
     and 'content slides from "Custom Layout 4" (it was asked for)' in proc.stdout and 'title slides from "Custom Layout 1" (it was asked for)' in proc.stdout,
     proc.stdout[-500:])
proc = run("add_theme.py", "from-pptx", anon, "--name", "picked-wrong", "--layout", "content=Agenda", env=ENV)
t.ok("a layout that is not there stops with the list of layouts", proc.returncode != 0 and '"Custom Layout 2" (3 slides)' in proc.stderr + proc.stdout
     and not (lib / "themes" / "picked-wrong").exists(), (proc.stdout + proc.stderr)[-400:])

import _backgrounds  # noqa: E402

with zipfile.ZipFile(FIXTURES / "template-custom.pptx") as zc:
    layouts = _backgrounds.list_layouts(zc, "ppt/slideMasters/slideMaster1.xml")
    import xml.etree.ElementTree as ET  # noqa: E402
    content_xml = ET.fromstring(zc.read(layouts[1]["part"]))
    title_sp, text_sps = _backgrounds.text_shapes(content_xml)
t.ok("the title is told from the other text boxes", title_sp is not None and len(text_sps) == 1
     and title_sp.find("{http://schemas.openxmlformats.org/presentationml/2006/main}nvSpPr/"
                       "{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr").get("name") == "Title 1")
named = _backgrounds.NAMED
t.ok("layout names are read sensibly", all(named["content"].search(n) for n in ("Title and Content", "Title, Content", "Title & Text", "1 Column", "Standard"))
     and not any(named["content"].search(n) for n in ("Title Slide", "Title Only", "Title and Vertical Text", "Content with Caption", "Two Content"))
     and named["title"].search("Cover") and named["section"].search("Section Divider"))

# ---- fonts: an open-licensed font with the same letter widths stands in ---------------------
def tiny_font(path, family: str) -> None:
    """A minimal font file with a family name, enough for the import to recognize."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((250, 700))
    pen.closePath()
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (600, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    fb.save(str(path))


fonts = OUT / "stand-in-fonts"
fonts.mkdir(exist_ok=True)
tiny_font(fonts / "LiberationSans-Regular.ttf", "Liberation Sans")
proc, f1, css, meta = make("template-custom.pptx", "fonts-auto", "--fonts", fonts)
t.ok("a template that names Arial takes an embedded Liberation Sans as its stand-in", token(css, "--font-body").startswith('"Arial", "Liberation Sans"')
     and 'font "Arial" (body) is not embedded; "Liberation Sans" is, and stands in for it' in proc.stdout, token(css, "--font-body"))
t.ok("and Arial is no longer reported as missing", 'font "Arial" (body) is not embedded: decks will use it only' not in proc.stdout
     and "which is not embedded" not in run("add_theme.py", "check", "fonts-auto", env=ENV).stdout)
tiny_font(fonts / "Brandon.ttf", "Brandon")
proc, f2, css, meta = make("template-custom.pptx", "fonts-alias", "--fonts", fonts, "--font-alias", "Arial=Brandon")
t.ok("--font-alias names another stand-in", token(css, "--font-body").startswith('"Arial", "Brandon"') and "line breaks may differ" in proc.stdout,
     token(css, "--font-body"))
proc, f3, css, meta = make("template-custom.pptx", "fonts-none")
t.ok("with nothing embedded, the report says which open font would stand in", "Or embed Liberation Sans or Arimo" in proc.stdout, proc.stdout[-500:])

t.done()
