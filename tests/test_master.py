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

t.done()
