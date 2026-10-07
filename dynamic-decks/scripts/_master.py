"""What a PowerPoint slide master says, beyond colors, fonts and backgrounds.

A template's master and its layouts hold the parts of a brand that are easy
to miss: which master is the real one when a file has several, where titles
align, where the footer and slide number sit, what a bullet looks like, how
big body text is. Each function here reads one of those from the file's XML
and returns plain values; add_theme.py turns them into tokens.

Positions come back in stage pixels (1920 x 1080), sizes in stage pixels too.
Nothing here needs more than the standard library.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile

from _backgrounds import NS, rels_of


# --------------------------------------------------------------------------
# Which master
# --------------------------------------------------------------------------
def list_masters(z: zipfile.ZipFile) -> list[dict]:
    """Every slide master in the file, in the order PowerPoint shows them.

    Each entry has: part, name (its theme's name), layouts (how many it has)
    and slides (how many slides in the file are built on it).
    """
    names = set(z.namelist())
    rels = rels_of(z, "ppt/presentation.xml")
    order = []
    try:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        for entry in pres.findall("p:sldMasterIdLst/p:sldMasterId", NS):
            target = rels.get(entry.get(f"{{{NS['r']}}}id", ""), ("", ""))[1]
            if target in names and target not in order:
                order.append(target)
    except ET.ParseError:
        pass
    for typ, target in rels.values():           # any the list above did not name
        if typ == "slideMaster" and target in names and target not in order:
            order.append(target)

    used: dict[str, int] = {}
    layout_master: dict[str, str] = {}
    for part in sorted(n for n in names if re.fullmatch(r"ppt/slides/[^/]+\.xml", n)):
        layout = next((t for typ, t in rels_of(z, part).values() if typ == "slideLayout"), None)
        if not layout:
            continue
        if layout not in layout_master:
            layout_master[layout] = next((t for typ, t in rels_of(z, layout).values() if typ == "slideMaster"), "")
        used[layout_master[layout]] = used.get(layout_master[layout], 0) + 1

    out = []
    for part in order:
        mrels = rels_of(z, part)
        name = ""
        theme = next((t for typ, t in mrels.values() if typ == "theme"), None)
        if theme in names:
            m = re.search(rb'<a:theme\b[^>]*\bname="([^"]*)"', z.read(theme)[:2000])
            name = m.group(1).decode("utf-8", "replace").strip() if m else ""
        out.append({"part": part, "name": name or f"Master {len(out) + 1}",
                    "layouts": sum(1 for typ, t in mrels.values() if typ == "slideLayout" and t in names),
                    "slides": used.get(part, 0)})
    return out


def pick_master(masters: list[dict], wanted: str | None = None) -> tuple[dict | None, str]:
    """The master to build the theme from, and why. `wanted` is a number (from 1) or a name."""
    if not masters:
        return None, "the file has no slide master"
    if wanted:
        text = str(wanted).strip()
        if text.isdigit():
            if 1 <= int(text) <= len(masters):
                return masters[int(text) - 1], "it was asked for"
            return None, f"--master {text}: the file has {len(masters)} slide master(s)"
        low = text.lower()
        exact = [m for m in masters if m["name"].lower() == low]
        close = exact or [m for m in masters if low in m["name"].lower()]
        if len(close) == 1 or exact:
            return close[0], "it was asked for"
        if close:
            return None, f"--master {text}: more than one slide master matches; use its number"
        return None, f"--master {text}: no slide master has that name"
    most = max(masters, key=lambda m: m["slides"])
    if most["slides"] and sum(1 for m in masters if m["slides"] == most["slides"]) == 1:
        return most, "most slides use it"
    return masters[0], ("it comes first and the file has no slides to go by" if not most["slides"]
                        else "it comes first and no master is used more than the others")


def describe_masters(masters: list[dict]) -> str:
    def one(i: int, m: dict) -> str:
        slides = f"{m['slides']} slide{'' if m['slides'] == 1 else 's'}"
        return f"{i} \"{m['name']}\" ({m['layouts']} layouts, {slides})"
    return ", ".join(one(i, m) for i, m in enumerate(masters, 1))


# --------------------------------------------------------------------------
# Placeholders: a layout's own, with the master's as the fallback
# --------------------------------------------------------------------------
TITLE_TYPES = ("title", "ctrTitle")
BODY_TYPES = (None, "body", "obj", "subTitle")


def placeholders(root, types: tuple) -> list:
    """The placeholder shapes of these types on a master or layout, in document order."""
    tree = root.find("p:cSld/p:spTree", NS) if root is not None else None
    out = []
    for sp in (tree.findall("p:sp", NS) if tree is not None else []):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is not None and ph.get("type") in types:
            out.append(sp)
    return out


def box_of(sp, size: tuple[int, int]) -> tuple | None:
    """A shape's box in stage px as (x, y, w, h), or None when it has no position of its own."""
    off, ext = sp.find("p:spPr/a:xfrm/a:off", NS), sp.find("p:spPr/a:xfrm/a:ext", NS)
    if off is None or ext is None:
        return None
    cx, cy = size
    return (int(off.get("x")) * 1920 / cx, int(off.get("y")) * 1080 / cy,
            int(ext.get("cx")) * 1920 / cx, int(ext.get("cy")) * 1080 / cy)


def _level(sp, level: int = 1):
    """<a:lvlNpPr> from a placeholder's own list style, or None."""
    return sp.find(f"p:txBody/a:lstStyle/a:lvl{level}pPr", NS) if sp is not None else None


def _first(*values):
    return next((v for v in values if v is not None), None)


# --------------------------------------------------------------------------
# Titles: alignment, and where the text sits on title and section slides
# --------------------------------------------------------------------------
ALIGN = {"l": "start", "just": "start", "dist": "start", "ctr": "center", "r": "end"}


def title_align(master, layout=None) -> str:
    """start, center or end: how this kind of slide aligns its title.

    The layout's title box decides, then the master's title box, then the
    master's title style. PowerPoint's own default master centers titles.
    """
    found = None
    for root in (layout, master):
        for sp in placeholders(root, TITLE_TYPES):
            lvl = _level(sp)
            para = sp.find("p:txBody/a:p/a:pPr", NS)
            found = _first(lvl.get("algn") if lvl is not None else None, para.get("algn") if para is not None else None)
            if found:
                break
        if found:
            break
    if not found and master is not None:
        style = master.find("p:txStyles/p:titleStyle/a:lvl1pPr", NS)
        found = style.get("algn") if style is not None else None
    return ALIGN.get(found or "l", "start")


def hero_place(master, layout, size: tuple[int, int]) -> str | None:
    """Where a title or section slide's text sits top to bottom: flex-start, center or flex-end.

    Goes by the middle of the layout's title and text boxes together. None
    when the layout places none of them itself.
    """
    boxes = [b for b in (box_of(sp, size) for sp in placeholders(layout, TITLE_TYPES + BODY_TYPES)) if b]
    if not boxes:
        return None
    top, bottom = min(b[1] for b in boxes), max(b[1] + b[3] for b in boxes)
    middle = (top + bottom) / 2 / 1080
    return "center" if 0.38 <= middle <= 0.62 else ("flex-end" if middle > 0.62 else "flex-start")


# --------------------------------------------------------------------------
# Footer and slide number
# --------------------------------------------------------------------------
def slides_on(z: zipfile.ZipFile, master_part: str) -> list[str]:
    """The slides in the file that are built on this master."""
    names = set(z.namelist())
    out, layout_master = [], {}
    for part in sorted(n for n in names if re.fullmatch(r"ppt/slides/[^/]+\.xml", n)):
        layout = next((t for typ, t in rels_of(z, part).values() if typ == "slideLayout"), None)
        if layout and layout not in layout_master:
            layout_master[layout] = next((t for typ, t in rels_of(z, layout).values() if typ == "slideMaster"), "")
        if layout and layout_master[layout] == master_part:
            out.append(part)
    return out


def _plain_color(node, resolve) -> str | None:
    """A solid fill's color when it is a plain one; a tint or shade of a theme color is left to the theme."""
    fill = node.find("a:solidFill", NS) if node is not None else None
    if fill is None:
        return None
    scheme = fill.find("a:schemeClr", NS)
    if scheme is not None and len(list(scheme)):
        return None
    return resolve(fill)


def footer(master, layout, size: tuple[int, int], px_per_pt: float, resolve, slides: list | None = None) -> dict:
    """Where the template puts its footer label and slide number, and whether it shows them.

    Returns {"label": {...}, "number": {...}}; each has `shown`, `why` (when
    not shown), `side` (left, center, right), `x` (where its text starts, stage
    px), `offset` (px from the bottom edge to the bottom of its text), `size`
    (px) and `color` (when the template gives a plain one). `slides` are the
    parsed slides built on this master, used as evidence of what the deck shows.
    """
    switches = {}
    for root in (master, layout):                # a layout's switches override its master's
        hf = root.find("p:hf", NS) if root is not None else None
        if hf is not None:
            switches.update({k: hf.get(k, "1") for k in ("sldNum", "ftr", "dt")})
    out = {}
    for key, kind in (("label", "ftr"), ("number", "sldNum")):
        on_layout = placeholders(layout, (kind,)) if layout is not None else []
        on_master = placeholders(master, (kind,))
        entry: dict = {"shown": True}
        if switches.get(kind) in ("0", "false"):
            entry.update(shown=False, why="it is switched off on the slide master")
        elif not on_master and not on_layout:
            entry.update(shown=False, why="the template has no box for it")
        elif layout is not None and not on_layout:
            entry.update(shown=False, why="its content layout has no box for it")
        elif slides is not None and len(slides) >= 3 and not any(placeholders(s, (kind,)) for s in slides):
            entry.update(shown=False, why=f"none of its {len(slides)} slides shows one")
        sources = [sp for sp in (on_layout[:1] + on_master[:1])]
        box = next((b for b in (box_of(sp, size) for sp in sources) if b), None)
        levels = [lvl for lvl in (_level(sp) for sp in sources) if lvl is not None]
        algn = _first(*[lvl.get("algn") for lvl in levels]) or ("r" if kind == "sldNum" else "l")
        runs = [lvl.find("a:defRPr", NS) for lvl in levels]
        runs = [r for r in runs if r is not None]
        sz = _first(*[r.get("sz") for r in runs])
        entry["size"] = round(int(sz) / 100 * px_per_pt) if sz and sz.isdigit() else None
        entry["color"] = _first(*[_plain_color(r, resolve) for r in runs])
        if box:
            anchor = box[0] + {"start": 0, "center": box[2] / 2, "end": box[2]}[ALIGN.get(algn, "start")]
            entry["x"] = round(anchor)
            entry["side"] = "left" if anchor < 0.36 * 1920 else ("right" if anchor > 0.64 * 1920 else "center")
            text = entry["size"] or 24
            entry["offset"] = round(1080 - (box[1] + box[3] / 2) - text / 2)
        out[key] = entry
    return out


# --------------------------------------------------------------------------
# Bullets
# --------------------------------------------------------------------------
DOTS = set("•●·∙⦁◦○⚫⚪")
SQUARES = set("▪■□◼◾▫◻⬛❒")
DASHES = set("–—-‒−―")
# Symbol fonts keep their pictures at ordinary letters (or the same letters moved up to U+F0xx).
SYMBOL_FONTS = {
    "wingdings": {"§": "square", "n": "square", "q": "square", "l": "dot", "Ø": "➢", "ü": "✓",
                  "v": "◆", "è": "→", "ð": "→", "à": "→"},
    "wingdings 2": {"£": "square", "\u0097": "dot", "¡": "square"},
    "wingdings 3": {"}": "▶", "u": "▶", "\u0084": "▶"},
    "symbol": {"·": "dot", "¾": "dash"},
    "webdings": {"=": "square", "4": "▶"},
    "courier new": {"o": "dot"},
}


def _bullet_shape(char: str, font: str) -> tuple[str, str | None, bool]:
    """(shape, character, understood) for a template's bullet character in its font."""
    code = ord(char[0]) if char else 0
    plain = chr(code - 0xF000) if 0xF000 <= code <= 0xF0FF else char[:1]     # symbol fonts' private-use copies
    table = SYMBOL_FONTS.get((font or "").strip().lower())
    if table is not None:
        hit = table.get(plain)
        if hit in ("dot", "square", "dash"):
            return hit, None, True
        if hit:
            return "char", hit, True
        return "dot", None, False                # a picture this table does not know
    if plain in DOTS:
        return "dot", None, True
    if plain in SQUARES:
        return "square", None, True
    if plain in DASHES:
        return "dash", None, True
    if 0xE000 <= code <= 0xF8FF or not plain.strip():
        return "dot", None, False
    return "char", plain, True


def bullets(master, layout, size: tuple[int, int], resolve) -> list[dict]:
    """The bullet at the first two levels of body text.

    Each entry has `shape` (dot, square, dash, char, none, number, picture),
    `char` (for char), `color` (a plain color, or None when the bullet takes
    the text's), `scale` (its size against the text, 1 = PowerPoint's own),
    `indent` (stage px from the bullet to the text) and `note` when the
    template's bullet could not be carried as it is.
    """
    bodies = placeholders(layout, BODY_TYPES)[:1] + placeholders(master, ("body",))[:1]
    out = []
    for level in (1, 2):
        sources = [lvl for lvl in (_level(sp, level) for sp in bodies) if lvl is not None]
        style = master.find(f"p:txStyles/p:bodyStyle/a:lvl{level}pPr", NS) if master is not None else None
        if style is not None:
            sources.append(style)
        entry: dict = {"shape": "dot", "char": None, "color": None, "text_color": True, "scale": 1.0, "indent": None}
        for src in sources:                       # the first source that says what the bullet is, decides
            none, char = src.find("a:buNone", NS), src.find("a:buChar", NS)
            if none is not None:
                entry["shape"] = "none"
            elif char is not None:
                font = next((f.get("typeface", "") for f in (s.find("a:buFont", NS) for s in sources) if f is not None), "")
                shape, glyph, understood = _bullet_shape(char.get("char", ""), font)
                entry.update(shape=shape, char=glyph)
                if not understood:
                    entry["note"] = f"a symbol from the font {font or 'of the text'} that is not carried over; a dot is used"
            elif src.find("a:buAutoNum", NS) is not None:
                entry.update(shape="number", note="numbering; lists stay bulleted unless a slide is written as a numbered list")
            elif src.find("a:buBlip", NS) is not None:
                entry.update(shape="picture", note="a picture; a dot is used")
            else:
                continue
            break
        for src in sources:
            color = src.find("a:buClr", NS)
            if color is not None:
                scheme = color.find("a:schemeClr", NS)
                entry["color"] = None if scheme is not None and len(list(scheme)) else resolve(color)
                entry["text_color"] = entry["color"] is None and color.find("a:srgbClr", NS) is None and scheme is None
                break
        for src in sources:
            pct = src.find("a:buSzPct", NS)
            if pct is not None and pct.get("val", "").rstrip("%").isdigit():
                value = int(pct.get("val").rstrip("%"))
                entry["scale"] = max(0.5, min(2.0, value / (100000 if value > 400 else 100)))
                break
        for src in sources:
            if src.get("marL", "").lstrip("-").isdigit():
                left = int(src.get("marL")) * 1920 / size[0]
                hang = abs(int(src.get("indent", "0") or 0)) * 1920 / size[0] if src.get("indent", "").lstrip("-").isdigit() else left
                entry["indent"] = round(min(left, hang) if level == 1 else hang)
                break
        out.append(entry)
    return out


# --------------------------------------------------------------------------
# Body text
# --------------------------------------------------------------------------
def body_text(master, layout) -> dict:
    """First-level body text: `size_pt` (points) and `line` (line spacing, 1 = PowerPoint's single).

    Either is None when the template does not say. The content layout's text
    box decides, then the master's, then the master's body style.
    """
    bodies = placeholders(layout, BODY_TYPES)[:1] + placeholders(master, ("body",))[:1]
    sources = [lvl for lvl in (_level(sp) for sp in bodies) if lvl is not None]
    style = master.find("p:txStyles/p:bodyStyle/a:lvl1pPr", NS) if master is not None else None
    if style is not None:
        sources.append(style)
    size = None
    for src in sources:
        run = src.find("a:defRPr", NS)
        if run is not None and run.get("sz", "").isdigit():
            size = int(run.get("sz")) / 100
            break
    line = None
    for src in sources:
        pct, pts = src.find("a:lnSpc/a:spcPct", NS), src.find("a:lnSpc/a:spcPts", NS)
        if pct is not None and pct.get("val", "").rstrip("%").isdigit():
            value = int(pct.get("val").rstrip("%"))
            line = value / (100000 if value > 400 else 100)
            break
        if pts is not None and pts.get("val", "").isdigit() and size:
            line = int(pts.get("val")) / 100 / (size * 1.2)      # exact spacing in points, against single spacing
            break
    return {"size_pt": size, "line": round(line, 3) if line else None}
