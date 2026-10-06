"""The shortcuts panel opens with ? or H from every state and in both windows."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from _common import OUT, Checks, launch, starter

deck = starter()
url = deck.as_uri()
t = Checks("Shortcuts panel")


def shown(page) -> bool:
    return page.evaluate("!!document.querySelector('.deck-help') && getComputedStyle(document.querySelector('.deck-help')).display === 'flex'")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1400, "height": 800})

    def fresh():
        pg = ctx.new_page()
        pg.goto(url + "#3")
        pg.wait_for_function("document.documentElement.classList.contains('deck-ready')")
        return pg

    pg = fresh()
    pg.keyboard.press("Shift+Slash")
    t.ok("? opens it on a fresh deck", shown(pg))
    t.ok("it lists edit mode", "Edit mode" in pg.evaluate("document.querySelector('.deck-help').textContent"))
    starred = pg.evaluate("[...document.querySelectorAll('.deck-help-keys dd')].filter(d => d.textContent.trim().endsWith('*')).map(d => d.previousElementSibling.textContent.replace(/\\s+/g, ' ').trim())")
    note = pg.evaluate("document.querySelector('.deck-help-note').textContent")
    t.ok("an asterisk marks the presenter window and both print keys, and the footnote explains it",
         starred == ["S", "P", "Shift P"] and note.startswith("* Works once you download this file") and "not in an AI assistant" in note, (starred, note))
    panel = pg.evaluate("[document.querySelector('.deck-help-panel h2').textContent, document.querySelectorAll('.deck-help-panel button').length, document.querySelector('.deck-help-close').getAttribute('aria-label')]")
    t.ok("the panel is titled Hotkeys and its only button is the close X", panel == ["Hotkeys", 1, "Close"], panel)
    box = pg.evaluate("(() => { const p = document.querySelector('.deck-help-panel').getBoundingClientRect(), x = document.querySelector('.deck-help-close').getBoundingClientRect(); return [p.right - x.right, x.top - p.top]; })()")
    pg.click(".deck-help-close")
    t.ok("the X sits in the top right corner and closes the panel", 0 < box[0] < 30 and 0 < box[1] < 30 and not shown(pg), box)
    pg.keyboard.press("Shift+Slash")
    pg.keyboard.press("Shift+Slash")
    t.ok("? again closes it", not shown(pg))
    pg.keyboard.press("h")
    t.ok("H opens it", shown(pg))
    pg.keyboard.press("Escape")
    t.ok("Esc closes it", not shown(pg))
    pg.close()

    pg = fresh()
    pg.keyboard.press("e")
    pg.keyboard.press("Shift+Slash")
    t.ok("? opens it in edit mode", shown(pg))
    pg.keyboard.press("Escape")
    t.ok("closing it leaves edit mode on", not shown(pg) and pg.evaluate("document.documentElement.classList.contains('deck-edit')"))
    pg.close()

    pg = fresh()
    pg.keyboard.press("o")
    pg.keyboard.press("Shift+Slash")
    t.ok("? opens it in the overview", shown(pg))
    pg.close()

    pg = fresh()
    pg.keyboard.press("n")
    pg.keyboard.press("Shift+Slash")
    t.ok("? opens it with the notes overlay up", shown(pg))
    pg.close()

    pg = fresh()
    with ctx.expect_page() as pop:
        pg.keyboard.press("s")
    pv = pop.value
    pv.wait_for_function("document.documentElement.classList.contains('deck-ready')")
    pv.wait_for_timeout(500)
    pv.bring_to_front()
    pv.keyboard.press("Shift+Slash")
    t.ok("? opens a panel in the presenter window", shown(pv))
    t.ok("the audience window stays clean", not shown(pg))
    pv.keyboard.press("Escape")
    pv.keyboard.press("ArrowRight")
    pv.wait_for_timeout(250)
    t.ok("presenter keys work after closing it", pg.evaluate("Deck.index") == 3)
    pv.close()
    pg.close()

    pg = fresh()
    pg.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'?',code:'Minus',altKey:true,ctrlKey:true,bubbles:true}))")
    t.ok("? typed with AltGr opens it", shown(pg))
    pg.close()

    pg = fresh()
    pg.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'/',code:'Slash',shiftKey:true,ctrlKey:true,bubbles:true}))")
    t.ok("Ctrl+Shift+/ is left to the browser", not shown(pg))
    pg.close()

    # A deck shown inside another page (a preview pane) gets keys only after a click inside it.
    host_file = OUT / "host-frame.html"
    host_file.write_text('<body style="margin:0"><input id="chat" autofocus><br>'
                         f'<iframe src="{deck.name}#3" style="width:1200px;height:675px;border:0"></iframe></body>', encoding="utf-8")
    host = ctx.new_page()
    host.set_default_timeout(8000)
    host.goto(host_file.as_uri())
    host.wait_for_timeout(1200)
    frame = [f for f in host.frames if f != host.main_frame][0]
    host.mouse.click(600, 400)
    host.keyboard.press("Shift+Slash")
    t.ok("inside a preview frame it opens once the deck has been clicked", frame.evaluate("document.documentElement.classList.contains('deck-show-help')"))
    host.close()

    # An assistant's preview is a sandboxed frame: no second window, no printing.
    boxed_file = OUT / "host-sandbox.html"
    boxed_file.write_text('<body style="margin:0">'
                          f'<iframe sandbox="allow-scripts allow-same-origin" src="{deck.name}#3" style="width:1200px;height:675px;border:0"></iframe></body>', encoding="utf-8")
    host = ctx.new_page()
    host.set_default_timeout(8000)
    host.goto(boxed_file.as_uri())
    host.wait_for_timeout(1200)
    frame = [f for f in host.frames if f != host.main_frame][0]
    pages_before = len(ctx.pages)
    host.mouse.click(600, 400)
    said = []
    for key in ("s", "p", "Shift+P"):
        host.keyboard.press(key)
        host.wait_for_timeout(150)
        said.append(frame.evaluate("document.querySelector('.deck-toast.is-visible') ? document.querySelector('.deck-toast').textContent : ''"))
    t.ok("in a sandboxed preview, S says to download the file", said[0].startswith("The presenter window does not work in a preview. Download") and len(ctx.pages) == pages_before, said[0])
    t.ok("P and Shift+P each name what was asked for", said[1].startswith("Saving the slides as a PDF does not work in a preview") and said[2].startswith("Printing slides with notes does not work in a preview"), said[1:])
    t.ok("Shift+P leaves the slides in place rather than half-way into the notes layout", frame.evaluate("!document.querySelector('.deck-np-page') && Deck.index === 3"))
    b.close()

t.done()
