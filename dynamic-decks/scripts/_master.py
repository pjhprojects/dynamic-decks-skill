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
