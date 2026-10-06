#!/usr/bin/env python3
"""Find the element a pasted reference points to.

    python scripts/locate.py talk.src.html '[slide 7 › card 2 › heading "Clickers and keys" @7.4.2.2]'
    python scripts/locate.py talk.src.html "make [slide 3 › title "Revenue grew" @3.1] shorter and drop [slide 3 › bar 2 @3.2.1.1.3]"
    python scripts/locate.py talk.html --json '[...]'

In a deck's edit mode (press E) the user clicks an element and gets a
reference to paste into their message. The part after @ is the element's
position: the slide number, then the index of each child element on the way
down. The quoted text is a cross-check. This script resolves a reference
against the deck source (or a built deck; the slides inside are the same) and
prints the file, the line range and the markup, so the edit goes to exactly
that element.

Pass the whole message if that is easier: every reference in it is resolved.

Each result says how it matched:
  exact         position and text both agree
  position      position found; the reference carries no text to check
  text differs  position found but its text is not what was copied. The slide
                may have been edited since, or a script writes that text. Read
                the markup shown before changing it.
  moved         nothing matches at that position, but the text was found
                elsewhere; that element is shown instead
  not found     neither position nor text matched. Ask the user to pick again
                in the current file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
P_CLOSERS = {
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table", "ul",
}
REF = re.compile(r"\[\s*(slide\s+\d+[^\[\]]*?)\s*@(\d+(?:\.\d+)*)(~?)\s*\]")
QUOTED = re.compile(r'"([^"]*)"\s*$')


class El:
    __slots__ = ("tag", "attrs", "parent", "content", "line", "end", "foreign")

    def __init__(self, tag, attrs, parent, line, foreign=False):
        self.tag, self.attrs, self.parent, self.line, self.end = tag, attrs, parent, line, line
        self.content: list = []          # text and child elements, in document order
        self.foreign = foreign           # inside <svg> or <math>

    @property
    def children(self) -> list["El"]:
        return [c for c in self.content if isinstance(c, El)]

    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class Tree(HTMLParser):
    """An element tree that follows the browser's parsing where it matters for
    counting children: void elements, self-closing tags in SVG, the implied end
    of <p>, <li>, <tr> and table cells, and the <tbody> a browser adds."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("#root", {}, None, 1)
        self.cur = self.root

    def _open(self, tag, attrs, closed):
        line = self.getpos()[0]
        foreign = self.cur.foreign or tag in ("svg", "math")
        if not self.cur.foreign:
            if tag == "li":
                self._close_until({"li"}, stop={"ul", "ol", "menu"})
            elif tag in ("td", "th"):
                self._close_until({"td", "th"}, stop={"tr", "table"})
            elif tag == "tr":
                self._close_until({"tr"}, stop={"table", "tbody", "thead", "tfoot"})
                if self.cur.tag == "table":
                    implied = El("tbody", {}, self.cur, line)
                    self.cur.content.append(implied)
                    self.cur = implied
            elif tag in ("tbody", "thead", "tfoot"):
                self._close_until({"tbody", "thead", "tfoot"}, stop={"table"})
            elif tag in ("dt", "dd"):
                self._close_until({"dt", "dd"}, stop={"dl"})
            if tag in P_CLOSERS and self.cur.tag == "p":
                self.cur.end = line
                self.cur = self.cur.parent
        node = El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur, line, foreign)
        self.cur.content.append(node)
        raw = self.get_starttag_text() or ""
        node.end = line + raw.count("\n")
        # a "/>" closes the element only for void tags and inside SVG or MathML
        if tag in VOID or (closed and foreign):
            return
        self.cur = node

    def _close_until(self, tags, stop):
        n = self.cur
        while n is not None and n.tag not in stop and n is not self.root:
            if n.tag in tags:
                n.end = self.getpos()[0]
                self.cur = n.parent
                return
            n = n.parent

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            n.end = self.getpos()[0]
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.content.append(data)


def parse(text: str) -> El:
    t = Tree()
    t.feed(text)
    t.close()
    return t.root


def slides_of(root: El) -> list[El]:
    deck = next((n for n in root.walk() if n.tag == "main" and "deck" in n.classes()), None)
    if deck is None:
        deck = next((n for n in root.walk() if "deck" in n.classes()), None)
    if deck is None:
        return []
    return [c for c in deck.children if c.tag == "section" and "slide" in c.classes()]


def text_of(node: El) -> str:
    out: list[str] = []

    def walk(n: El):
        for c in n.content:
            if isinstance(c, str):
                out.append(c)
            elif c.tag in ("style", "script", "title") or (c.tag == "aside" and "notes" in c.classes()):
                continue
            else:
                out.append(" ")
                walk(c)
                out.append(" ")
    walk(node)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def snippet_source(node: El) -> str:
    """The text the engine would have quoted for this element."""
    if "slide" in node.classes() and node.tag == "section":
        title = next((n for n in node.walk() if "slide-title" in n.classes()), None)
        return text_of(title) if title is not None else ""
    tip = next((c for c in node.children if c.tag == "title"), None)
    if tip is not None:
        return re.sub(r"\s+", " ", "".join(c for c in tip.content if isinstance(c, str))).strip()
    return text_of(node)


def squash(s: str) -> str:
    return re.sub(r"[\W_]+", "", s, flags=re.UNICODE)


def text_matches(node: El, quoted: str) -> bool:
    want = squash(quoted.rstrip("…"))
    have = squash(snippet_source(node))
    if not want:
        return not have
    return have.startswith(want) if quoted.endswith("…") else have == want


def describe(node: El) -> str:
    cls = node.attrs.get("class")
    return "<" + node.tag + (' class="' + cls + '"' if cls else "") + ">"


def resolve(ref: re.Match, slides: list[El]) -> dict:
    label, path, loose = ref.group(1).strip(), ref.group(2), bool(ref.group(3))
    q = QUOTED.search(label)
    quoted = q.group(1) if q else ""
    idx = [int(x) for x in path.split(".")]
    out = {"reference": ref.group(0), "path": path, "quoted": quoted, "status": "not found"}

    node = None
    if 1 <= idx[0] <= len(slides):
        node = slides[idx[0] - 1]
        for k in idx[1:]:
            kids = node.children
            if 1 <= k <= len(kids):
                node = kids[k - 1]
            else:
                node = None
                break

    checkable = bool(quoted) and not loose
    if node is not None and (not checkable or text_matches(node, quoted)):
        out["status"] = "exact" if checkable else "position"
    elif checkable:
        # look for the quoted text: first on the same slide, then anywhere
        order = []
        if 1 <= idx[0] <= len(slides):
            order.append(slides[idx[0] - 1])
        order += [s for s in slides if s not in order]
        found = None
        for slide in order:
            hits = [n for n in slide.walk() if n is not slide and n.tag not in ("style", "script") and text_matches(n, quoted)]
            if hits:
                found = max(hits, key=lambda n: _depth(n))      # the innermost element with that text
                break
        if found is not None:
            out["status"] = "moved"
            if node is not None:
                out["at_position"] = describe(node) + (" on line %d" % node.line if node.line == node.end
                                                       else " on lines %d-%d" % (node.line, node.end))
            node = found
        elif node is not None:
            out["status"] = "text differs"
            out["text_now"] = snippet_source(node)[:80]
        else:
            node = None
    if node is None:
        return out
    slide = node
    while slide.parent is not None and slide not in slides:
        slide = slide.parent
    out.update({"element": describe(node), "line": node.line, "end": node.end,
                "slide": slides.index(slide) + 1 if slide in slides else None})
    return out


def _depth(n: El) -> int:
    d = 0
    while n.parent is not None:
        d += 1
        n = n.parent
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve element references copied from a deck's edit mode.")
    ap.add_argument("deck", help="deck source (.src.html) or built deck")
    ap.add_argument("text", nargs="+", help="one or more references, or a whole message that contains them")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lines", type=int, default=14, help="how many lines of markup to show per element (default 14)")
    args = ap.parse_args()

    path = Path(args.deck).expanduser()
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        sys.exit(2)
    source = path.read_text(encoding="utf-8")
    slides = slides_of(parse(source))
    if not slides:
        print("error: no slides found in " + str(path), file=sys.stderr)
        sys.exit(2)
    refs = list(REF.finditer(" ".join(args.text)))
    if not refs:
        print("error: no reference found. A reference looks like  [slide 7 › heading \"Text\" @7.4.2]", file=sys.stderr)
        sys.exit(2)

    results = [resolve(r, slides) for r in refs]
    if args.json:
        print(json.dumps({"file": str(path), "results": results}, indent=2, ensure_ascii=False))
    else:
        lines = source.split("\n")
        for r in results:
            print(r["reference"])
            if "line" not in r:
                print("  not found: nothing at that position and no element with that text. Ask the user to pick it again in the current deck.\n")
                continue
            span = f"line {r['line']}" if r["line"] == r["end"] else f"lines {r['line']}-{r['end']}"
            note = {
                "exact": "exact match",
                "position": "matched by position (no text to cross-check)",
                "text differs": f"position found, but its text is now \"{r.get('text_now', '')}\". Check this is the element meant.",
                "moved": "found by its text; it is no longer at the copied position" + (f" (which now holds {r['at_position']})" if r.get("at_position") else ""),
            }[r["status"]]
            print(f"  {path.name} {span}, slide {r['slide']}, {r['element']}: {note}")
            shown = lines[r["line"] - 1:r["end"]]
            for n, text in enumerate(shown[:args.lines], r["line"]):
                print(f"  {n:>5} | {text[:160]}")
            if len(shown) > args.lines:
                print(f"        | ... {len(shown) - args.lines} more line(s)")
            print()
    sys.exit(1 if any(r["status"] == "not found" for r in results) else 0)


if __name__ == "__main__":
    main()
