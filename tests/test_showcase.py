"""The showcase deck and the dynamic helpers it leans on: typing, travel, live controls."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from _common import OUT, Checks, build, launch, run, showcase

deck = showcase()
t = Checks("Showcase and dynamic helpers")

SMALL = OUT / "dynamic" / "small.src.html"
SMALL.parent.mkdir(parents=True, exist_ok=True)
SMALL.write_text("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Helpers</title></head>
<body><main class="deck">
<section class="slide" id="a">
  <h2 class="slide-title" data-type>Words that <em>type</em> themselves out across a long title that wraps to two lines</h2>
  <div class="slide-body">
    <p class="second" data-type data-type-caret>And a second line that follows the first.</p>
    <svg class="diagram" viewBox="0 0 1600 300">
      <circle class="mark" r="18" data-anim="travel" style="offset-path: path('M100 150 H1500'); --anim-dur: calc(var(--dur-slow) * 2)"/>
    </svg>
    <p class="late" data-step data-type>Typed on the first click.</p>
  </div>
  <aside class="notes"><p>Notes.</p></aside>
</section>
<section class="slide"><h2 class="slide-title">Two</h2><aside class="notes"><p>Notes.</p></aside></section>
</main></body></html>
""", encoding="utf-8")
small = OUT / "dynamic" / "small.html"
proc = build(SMALL, small)
t.ok("a deck using data-type and travel builds and passes the checks", proc.returncode == 0 and "all checks pass" in proc.stdout, proc.stdout[-300:])
t.ok("data-type counts as motion in the check report", "motion on 1 of them" in proc.stdout, proc.stdout[-200:])

with sync_playwright() as p:
    b = launch(p)

    # ---- the helpers, on the small deck ---------------------------------
    pg = b.new_page(viewport={"width": 1280, "height": 720})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(small.as_uri())
    pg.wait_for_function("document.documentElement.classList.contains('deck-ready')")
    full_height = pg.evaluate("(() => { Deck.rest(true); const h = document.querySelector('h2').getBoundingClientRect().height; Deck.rest(false); return h; })()")
    pg.evaluate("Deck.go(1); Deck.go(0)")
    pg.wait_for_timeout(700)
    mid = pg.evaluate("""(() => { const h = document.querySelector('h2'); return {
        chars: h.querySelectorAll('.deck-type-ch').length, typed: h.querySelectorAll('.is-typed').length,
        height: h.getBoundingClientRect().height, text: h.textContent, em: !!h.querySelector('em .deck-type-ch'),
        second: document.querySelector('.second').querySelectorAll('.is-typed').length,
        x: document.querySelector('circle').getBoundingClientRect().left }; })()""")
    t.ok("typing is under way: some characters shown, not all", 0 < mid["typed"] < mid["chars"], mid)
    t.ok("the text keeps its full size while it types, so nothing reflows", abs(mid["height"] - full_height) < 1, (mid["height"], full_height))
    t.ok("the words themselves are untouched", mid["text"] == "Words that type themselves out across a long title that wraps to two lines", mid["text"])
    t.ok("inline markup inside typed text is kept", mid["em"])
    t.ok("the second typed element waits its turn", mid["second"] == 0, mid["second"])
    pg.evaluate("window.__typed = []; document.addEventListener('deck:typed', e => window.__typed.push(e.target.className || e.target.tagName))")
    pg.wait_for_function("document.querySelector('.second').querySelectorAll('.is-typed').length === document.querySelector('.second').querySelectorAll('.deck-type-ch').length", timeout=8000)
    pg.wait_for_timeout(120)
    done = pg.evaluate("""(() => { const h = document.querySelector('h2'), s = document.querySelector('.second'); return {
        typing: h.classList.contains('deck-typing') || s.classList.contains('deck-typing'),
        carets: [h.querySelectorAll('.is-caret').length, s.querySelectorAll('.is-caret').length],
        late: getComputedStyle(document.querySelector('.late')).visibility, events: window.__typed,
        x: document.querySelector('circle').getBoundingClientRect().left }; })()""")
    t.ok("both elements finish typing, in order", not done["typing"], done)
    t.ok("the caret leaves, unless data-type-caret asks it to stay", done["carets"] == [0, 1], done["carets"])
    t.ok("a deck:typed event fires when an element finishes", "second" in done["events"], done["events"])
    t.ok("travel moved the element along its path", mid["x"] < done["x"] and done["x"] > 900, (mid["x"], done["x"]))
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(350)
    late = pg.evaluate("(() => { const l = document.querySelector('.late'); return [l.querySelectorAll('.is-typed').length, l.querySelectorAll('.deck-type-ch').length, Deck.step]; })()")
    t.ok("typed text inside a step starts when the step is revealed", 0 < late[0] <= late[1] and late[2] == 1, late)
    pg.keyboard.press("ArrowRight")
    pg.keyboard.press("ArrowLeft")
    pg.wait_for_timeout(100)
    rest = pg.evaluate("[document.querySelectorAll('.deck-typing').length, document.querySelectorAll('.is-caret').length, document.querySelector('.late').textContent]")
    t.ok("coming back shows the finished text with no caret", rest == [0, 0, "Typed on the first click."], rest)
    t.ok("no script errors from the helpers", not errs, errs)
    pg.close()

    # ---- the showcase deck -------------------------------------------------
    ctx = b.new_context(viewport={"width": 1600, "height": 900})
    reqs, errs = [], []
    ctx.on("request", lambda r: reqs.append(r.url))
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(deck.as_uri())
    pg.wait_for_function("document.documentElement.classList.contains('deck-ready')")
    total = pg.evaluate("Deck.total")
    ids = pg.evaluate("Deck.slides.map(s => s.id)")

    def show(slide_id: str, wait: int = 0):
        pg.evaluate("i => Deck.go(i)", ids.index(slide_id))
        if wait:
            pg.wait_for_timeout(wait)

    t.ok("the showcase has its seventeen slides", total == 17, total)
    text = pg.evaluate("document.querySelector('.deck').textContent")
    t.ok("it says what it is: a skill for an AI agent", "a skill for your AI agent" in text and "ChatGPT" in text and "Claude" in text)
    t.ok("and is honest about what was tested", "Built and tested with Claude" in text)

    # every slide's resting frame is its finished frame
    pg.evaluate("Deck.rest(true)")
    still = pg.evaluate("""(() => ({
        word: document.querySelector('.hero-word').textContent, num: document.querySelector('.hero-num').textContent,
        built: document.querySelector('#typing').classList.contains('is-built'),
        stops: document.querySelectorAll('#route .stop.is-on').length,
        van: parseFloat(document.querySelector('.route-van').style.left),
        year: document.querySelector('.race-year').textContent,
        top: [...document.querySelectorAll('.race-row')].find(r => r.style.getPropertyValue('--rank') === '0').querySelector('span').textContent,
        whatif: [document.querySelector('.hero-out b').textContent, document.querySelector('.hero-out span').textContent,
                 document.querySelector('.hero-whatif').style.getPropertyValue('--v'), document.querySelector('.hero-slider').className,
                 document.querySelector('.hero-line').getAttribute('d').length > 50],
        typing: document.querySelectorAll('.deck-typing').length }))()""")
    t.ok("at rest the opening shows its first word, final number and the slider at its resting value",
         still["word"] == "move." and still["num"] == "128" and still["whatif"] == ["$3.3M", "at 4.2% growth", "62.0%", "hero-slider", True], still)
    t.ok("at rest the built slide, the route and the ranking are complete",
         still["built"] and still["stops"] == 5 and still["van"] > 90 and still["year"] == "2026" and still["top"] == "Delta" and still["typing"] == 0, still)
    pg.evaluate("Deck.rest(false)")

    show("skill")
    show("hero")
    pg.wait_for_function("document.querySelector('.hero-word').textContent.trim() !== 'move.'", timeout=6000)
    t.ok("the opening word retypes itself", pg.evaluate("document.querySelector('.hero-word').classList.contains('is-live')"))
    pg.wait_for_function("document.querySelector('.hero-slider.is-held')", timeout=8000)
    pg.wait_for_function("parseFloat(document.querySelector('.hero-whatif').style.getPropertyValue('--v')) > 90", timeout=8000)
    high = pg.evaluate("[document.querySelector('.hero-out b').textContent, document.querySelector('.hero-out span').textContent]")
    pg.wait_for_function("parseFloat(document.querySelector('.hero-whatif').style.getPropertyValue('--v')) < 15", timeout=8000)
    low = pg.evaluate("[document.querySelector('.hero-out b').textContent, document.querySelector('.hero-out span').textContent]")
    t.ok("a cursor drags the slider and the figure follows it up and down",
         float(high[0][1:-1]) > 4.2 and float(low[0][1:-1]) < 2.2 and high[1] != low[1], (high, low))

    show("typing", 300)
    t.ok("the mock slide waits while the request types", not pg.evaluate("document.querySelector('#typing').classList.contains('is-built')"))
    pg.wait_for_function("document.querySelector('#typing').classList.contains('is-built')", timeout=8000)
    t.ok("and builds once the request has finished typing", True)

    show("route", 250)
    early = pg.evaluate("[document.querySelectorAll('#route .stop.is-on').length, parseFloat(document.querySelector('.route-van').style.left)]")
    pg.wait_for_function("document.querySelectorAll('#route .stop.is-on').length === 5", timeout=9000)
    t.ok("the truck starts at the first stop and lights the rest as it passes", early[0] < 5 and early[1] < 40, early)

    show("race", 300)
    first = pg.evaluate("document.querySelector('.race-year').textContent")
    pg.wait_for_function("document.querySelector('.race-year').textContent === '2026'", timeout=12000)
    t.ok("the ranking plays from the first year to the last", first in ("2019", "2020"), first)

    show("story", 200)
    seen = [pg.evaluate("getComputedStyle(document.querySelector('#story .fix')).visibility")]
    for _ in range(3):
        pg.keyboard.press("ArrowRight")
    seen.append(pg.evaluate("getComputedStyle(document.querySelector('#story .goal')).visibility"))
    t.ok("the stepped chart holds parts back until their click", seen == ["hidden", "visible"] and pg.evaluate("Deck.step") == 3, seen)

    show("forecast", 200)
    before = pg.evaluate("document.querySelector('.fc-result-value').textContent")
    box = pg.locator(".fc-growth").bounding_box()
    at = pg.evaluate("Deck.index")
    pg.mouse.click(box["x"] + box["width"] * 0.95, box["y"] + box["height"] / 2)
    after = pg.evaluate("[document.querySelector('.fc-result-value').textContent, document.querySelector('.fc-growth-out').textContent, document.querySelector('.fc-result-delta').textContent, Deck.index]")
    t.ok("dragging a slider recalculates the slide", before == "$3.39M" and after[0] != before and after[2].endswith("above plan"), (before, after))
    t.ok("and does not advance the deck", after[3] == at, after)
    pg.locator(".fc-growth").focus()
    pg.keyboard.press("ArrowLeft")
    t.ok("arrow keys adjust a focused slider instead of changing slide", pg.evaluate("Deck.index") == at and pg.evaluate("document.querySelector('.fc-growth-out').textContent") != after[1])
    pg.evaluate("document.activeElement.blur()")

    show("system", 600)
    packets = pg.evaluate("[document.querySelectorAll('#system .packet').length, getComputedStyle(document.querySelector('#system .packet')).animationName]")
    t.ok("requests ride every connection of the diagram", packets == [16, "system-flow"], packets)

    show("anything", 300)
    pg.mouse.move(800, 450)
    pg.mouse.move(900, 500)
    pg.wait_for_timeout(200)
    painted = pg.evaluate("(() => { const c = document.querySelector('.sky'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4000) if (d[i]) n++; return n; })()")
    t.ok("the canvas slide draws, and follows the pointer without errors", painted > 5 and not errs, (painted, errs))

    show("theme", 200)
    at = pg.evaluate("Deck.index")
    pg.click(".look-switch button[data-variant=dark]")
    dark = pg.evaluate("[document.documentElement.dataset.variant, document.querySelector('.look-switch button[data-variant=dark]').getAttribute('aria-pressed'), Deck.index]")
    t.ok("the Dark button switches the whole deck's theme variant", dark == ["dark", "true", at], dark)
    pg.keyboard.press("t")
    light = pg.evaluate("[document.documentElement.dataset.variant, document.querySelector('.look-switch button[data-variant=light]').getAttribute('aria-pressed')]")
    t.ok("and the buttons follow the T key", light == ["light", "true"], light)

    for i in range(total):
        pg.evaluate("i => Deck.go(i)", i)
        pg.wait_for_timeout(120)
    t.ok("walking every slide raises no script errors", not errs, errs)
    t.ok("and makes no network requests", all(u.startswith("file:") or u.startswith("data:") or u.startswith("about:") or u.startswith("blob:") for u in reqs), [u for u in reqs if not u.startswith(("file:", "data:"))][:3])
    ctx.close()
    b.close()

proc = run("render.py", deck, "--no-shots", "--out", OUT / "dynamic" / "render")
t.ok("render.py finds nothing overflowing in the showcase", proc.returncode == 0 and "LOOK" not in proc.stdout, proc.stdout[-400:])
t.ok("the showcase is one file under 1 MB", deck.stat().st_size < 1024 * 1024, deck.stat().st_size)
t.done()
