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
