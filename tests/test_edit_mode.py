"""Edit mode: hover, click to copy a reference, widen and narrow, and resolving it to source lines."""
from __future__ import annotations

import json
import re

from playwright.sync_api import sync_playwright

from _common import OUT, STARTER_SRC, Checks, launch, run, starter

deck = starter()
out = OUT / "edit-mode"
out.mkdir(parents=True, exist_ok=True)
t = Checks("Edit mode")


def center(pg, sel, slide):
    return pg.evaluate("([sel, n]) => { const e=Deck.slides[n].querySelector(sel); const r=e.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]; }", [sel, slide])


def locate(ref):
    proc = run("locate.py", STARTER_SRC, "--json", ref)
    return json.loads(proc.stdout)["results"][0]


def tag(pg):
    return pg.evaluate("document.querySelector('.deck-edit-tag').textContent")


def clip(pg):
    pg.wait_for_timeout(90)
    return pg.evaluate("window.__clip")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1600, "height": 900})
    errs = []
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(deck.as_uri() + "#7")
    pg.wait_for_function("document.documentElement.classList.contains('deck-ready')")
    # stand in for the async clipboard so the test can read what was copied
    pg.evaluate("window.__clip=null; Object.defineProperty(navigator,'clipboard',{value:{writeText:(t)=>{window.__clip=t; return Promise.resolve();}},configurable:true})")

    pg.mouse.move(300, 300)
    t.ok("nothing is added to the slide outside edit mode", pg.evaluate(
        "!document.querySelector('.deck-edit-btn') && getComputedStyle(document.querySelector('.deck-edit-bar')).display==='none'"
        " && getComputedStyle(document.querySelector('.deck-edit-box')).display==='none'"))
    pg.keyboard.press("e")
    t.ok("E turns edit mode on", pg.evaluate("document.documentElement.classList.contains('deck-edit')"))
    t.ok("the bar is shown", pg.evaluate("getComputedStyle(document.querySelector('.deck-edit-bar')).display") == "flex")
    t.ok("the bar carries no key tips", not pg.evaluate("!!document.querySelector('.deck-edit-hint')"))

    x, y = center(pg, ".card:nth-of-type(2) h3", 6)
    pg.mouse.move(x, y)
    pg.wait_for_timeout(50)
    box = pg.evaluate("(() => { const r=document.querySelector('.deck-edit-box').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; })()")
    h3 = pg.evaluate("(() => { const r=Deck.slides[6].querySelectorAll('.card')[1].querySelector('h3').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; })()")
    t.ok("hover outlines the element under the pointer", all(abs(a - c) < 1.5 for a, c in zip(box, h3)), (box, h3))
    t.ok("the hover tag is readable", tag(pg) == 'slide 7 › card 2 › heading "Clickers and keys"', tag(pg))
    before = pg.evaluate("Deck.index")
    pg.mouse.click(x, y)
    c1 = clip(pg)
    t.ok("a click copies the reference", c1 == '[slide 7 › card 2 › heading "Clickers and keys" @7.2.2.2]', c1)
    t.ok("the click does not advance the slide", pg.evaluate("Deck.index") == before)
    t.ok("the bar shows the reference", pg.evaluate("document.querySelector('.deck-edit-field').value") == c1)
    r = locate(c1)
    t.ok("the reference resolves to the heading in the source", r["status"] == "exact" and r["element"] == "<h3>", r)
    line = STARTER_SRC.read_text(encoding="utf-8").split("\n")[r["line"] - 1]
    t.ok("that source line is the right one", "Clickers and keys" in line, line)
    pg.screenshot(path=str(out / "edit-mode.png"))

    pg.keyboard.press("ArrowUp")
    t.ok("Up widens to the card", tag(pg).startswith('slide 7 › card 2 "Clickers and keys'), tag(pg))
    pg.keyboard.press("ArrowUp")
    pg.keyboard.press("ArrowUp")
    t.ok("Up twice more reaches the slide", tag(pg).startswith('slide 7 "Presenting works'), tag(pg))
    pg.keyboard.press("Enter")
    c2 = clip(pg)
    t.ok("Enter copies the widened pick", c2 == '[slide 7 "Presenting works the way you expect" @7]', c2)
    r = locate(c2)
    t.ok("a slide reference resolves", r["status"] == "exact" and r["element"].startswith("<section"), r)
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("ArrowDown")
    t.ok("Down narrows back", tag(pg).startswith('slide 7 › card 2 "'), tag(pg))

    x, y = center(pg, ".card:nth-of-type(3) svg.icon", 6)
    pg.mouse.move(x, y)
    pg.wait_for_timeout(50)
    pg.mouse.click(x, y)
    c3 = clip(pg)
    t.ok("an icon reference names the icon", c3 == '[slide 7 › card 3 › icon "printer" @7.2.3.1~]', c3)
    r = locate(c3)
    t.ok("an icon reference resolves", r["status"] == "position" and "icon" in r["element"], r)

    for _ in range(5):
        pg.keyboard.press("ArrowLeft")
    t.ok("arrows move between slides", pg.evaluate("Deck.index") == 1, pg.evaluate("Deck.index"))
    vis = pg.evaluate("Array.from(Deck.slides[1].querySelectorAll('[data-step]')).map(e=>getComputedStyle(e).visibility)")
    t.ok("steps are revealed in edit mode", vis == ["visible"] * 3, vis)
    x, y = center(pg, "li:nth-child(3)", 1)
    pg.mouse.click(x, y)
    c4 = clip(pg)
    t.ok("a step-revealed bullet can be picked", c4.startswith("[slide 2 › bullet 3 \"The presenter view") and c4.endswith("@2.3.1.3]"), c4)
    r = locate(c4)
    t.ok("truncated text still resolves exactly", r["status"] == "exact" and r["element"] == "<li>", r)

    pg.evaluate("Deck.go(7)")
    pg.wait_for_timeout(80)
    bx = pg.evaluate("(() => { const e=Deck.slides[7].querySelectorAll('.chart-bar')[3]; const r=e.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]; })()")
    pg.mouse.move(*bx)
    pg.wait_for_timeout(50)
    pg.mouse.click(*bx)
    c5 = clip(pg)
    t.ok("a chart bar is named by its data", 'bar 4 "Q4: 410"' in c5, c5)
    r = locate(c5)
    t.ok("a chart bar resolves", r["status"] == "exact" and "chart-bar" in r["element"], r)

    wave = pg.evaluate("Deck.slides.findIndex(s => s.id === 'custom-wave')")
    pg.evaluate("(i) => Deck.go(i)", wave)
    pg.wait_for_timeout(80)
    wx = pg.evaluate("(i) => { const e=Deck.slides[i].querySelector('.wave rect:nth-child(20)'); const r=e.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]; }", wave)
    pg.mouse.move(*wx)
    pg.wait_for_timeout(50)
    pg.mouse.click(*wx)
    c6 = clip(pg)
    t.ok("script-drawn bars resolve to their authored parent", re.match(r"\[slide \d+ › graphic @\d+\.3\.1\]", c6) is not None, c6)
    r = locate(c6)
    t.ok("and that parent resolves", r["status"] == "position" and "wave" in r["element"], r)
    h1 = pg.evaluate("(i) => Deck.slides[i].querySelector('.wave rect').getAttribute('height')", wave)
    pg.wait_for_timeout(250)
    h2 = pg.evaluate("(i) => Deck.slides[i].querySelector('.wave rect').getAttribute('height')", wave)
    t.ok("animation is paused in edit mode", h1 == h2, (h1, h2))

    pg.evaluate("navigator.clipboard.writeText = () => Promise.reject(new Error('blocked')); document.execCommand = () => false;")
    tx = center(pg, ".slide-title", wave)
    pg.mouse.move(*tx)
    pg.mouse.click(*tx)
    pg.wait_for_timeout(120)
    msg = pg.evaluate("document.querySelector('.deck-edit-msg').textContent")
    foc = pg.evaluate("document.activeElement.className")
    val = pg.evaluate("document.querySelector('.deck-edit-field').value")
    t.ok("a blocked copy falls back to a selectable field", "blocked" in msg and foc == "deck-edit-field" and "title" in val, (msg, foc, val))
    pg.keyboard.press("Escape")
    t.ok("Esc leaves edit mode, even from that field", not pg.evaluate("document.documentElement.classList.contains('deck-edit')"))
    i0 = pg.evaluate("Deck.index")
    pg.mouse.click(700, 300)
    t.ok("normal clicks advance again", pg.evaluate("Deck.index") == i0 + 1, (i0, pg.evaluate("Deck.index")))
    t.ok("no script errors", not errs, errs[:3])
    b.close()

t.done()
