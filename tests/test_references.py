"""Every element of a deck gets a reference that resolves back to the right place in the source."""
from __future__ import annotations

import collections
import json
import shutil

from playwright.sync_api import sync_playwright

from _common import FIXTURES, OUT, STARTER_SRC, Checks, build, launch, run, starter

t = Checks("References")

ALL_REFS = """() => { const out=[]; Deck.slides.forEach(s => { const w=document.createTreeWalker(s, NodeFilter.SHOW_ELEMENT);
  let n=s; while(n){ if(n._deckPath && !n.closest('style,script')) out.push(Deck.ref(n)); n=w.nextNode(); } }); return out; }"""


def resolve(target, refs):
    results = []
    for i in range(0, len(refs), 150):
        proc = run("locate.py", target, "--json", *refs[i:i + 150])
        results += json.loads(proc.stdout)["results"]
    return results


board_src = OUT / "board-update.src.html"
OUT.mkdir(parents=True, exist_ok=True)
shutil.copyfile(FIXTURES / "board-update.src.html", board_src)
board = OUT / "board-update.html"
build(board_src, board)
decks = [("starter", starter(), STARTER_SRC), ("board update", board, board_src)]

with sync_playwright() as p:
    b = launch(p)
    for name, built, src in decks:
        pg = b.new_page(viewport={"width": 1600, "height": 900})
        pg.goto(built.as_uri())
        pg.wait_for_function("!!window.Deck")
        refs = pg.evaluate(ALL_REFS)
        pg.close()
        t.ok(f"{name}: every element has a reference", len(refs) > 150 and all(r.startswith("[slide ") for r in refs), len(refs))
        for label, target in (("source", src), ("built deck", built)):
            res = resolve(target, refs)
            counts = collections.Counter(x["status"] for x in res)
            bad = [x for x in res if x["status"] not in ("exact", "position")]
            t.ok(f"{name}: all {len(refs)} resolve against the {label}", not bad, (dict(counts), [x["reference"] for x in bad[:3]]))
    b.close()

# stale references
ref = '[slide 8 › card 2 › heading "Hire six engineers" @8.2.2.2]'
text = board_src.read_text(encoding="utf-8")
first_card = '    <article class="card" data-step>\n      <svg class="icon icon--lg" aria-hidden="true"><use href="#icon-globe"/></svg>'
moved = OUT / "moved.src.html"
moved.write_text(text.replace(first_card, '    <article class="card"><h3>New first card</h3><p>Inserted later.</p></article>\n' + first_card, 1), encoding="utf-8")
changed = OUT / "changed.src.html"
changed.write_text(text.replace("<h3>Hire six engineers</h3>", "<h3>Grow the platform team</h3>"), encoding="utf-8")

r = resolve(board_src, [ref])[0]
t.ok("a current reference is an exact match", r["status"] == "exact", r)
r2 = resolve(moved, [ref])[0]
t.ok("after an insert, the element is found again by its text", r2["status"] == "moved" and r2["line"] == r["line"] + 1, r2)
r3 = resolve(changed, [ref])[0]
t.ok("after a rewrite, the mismatch is reported", r3["status"] == "text differs" and "Grow the platform team" in r3.get("text_now", ""), r3)
proc = run("locate.py", board_src, '[slide 40 › title "Nope" @40.1]')
t.ok("a reference to nothing is reported as not found", proc.returncode == 1 and "not found" in proc.stdout, proc.stdout[:120])
proc = run("locate.py", board_src, f"please shorten {ref} and recolor [slide 3 › chart › bar 4 \"Q4: $2.6M\" @3.2.1.1.11]")
t.ok("references are picked out of a whole message", proc.stdout.count("exact match") == 2, proc.stdout[:200])

t.done()
