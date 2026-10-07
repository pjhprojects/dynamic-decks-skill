"""Slide backgrounds from a PowerPoint template.

A template's artwork (photos, gradients, bands, corner marks) is kept by
rendering it, not by rebuilding it: for each kind of slide a one-slide copy of
the template is made with nothing on the slide, LibreOffice draws it, and the
picture becomes that kind's background. The picture is then measured once, so
slides built later never have to look at it:

    safe area    where the template's own text boxes sit: the slide's margins
    ink          dark or light text, from the pixels under the safe area
    calm         whether text can sit straight on the picture, or needs a panel
    description  a sentence about where the artwork is, for composing by hand

Used by add_theme.py. Needs Pillow; rendering needs LibreOffice (soffice).
Without LibreOffice a background that is a single picture is still taken
straight from the file, and a simple gradient is turned into CSS.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
STAGE_W, STAGE_H = 1920, 1080
KINDS = ("content", "title", "section", "closing")
# which layout stands for which kind of slide, best match first
LAYOUT_TYPES = {
    "content": ("obj", "tx", "twoObj", "titleOnly"),
    "title": ("title",),
    "section": ("secHead",),
}
CLOSING_NAMES = re.compile(r"\b(closing|thank|end|final|last)\b", re.I)
SLIDE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:sld xmlns:a="{a}" xmlns:p="{p}" xmlns:r="{r}"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
    '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>'
    '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>').format(**NS)
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
LAYOUT_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"


# --------------------------------------------------------------------------
# Finding the layouts
# --------------------------------------------------------------------------
def rels_of(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (type, target part) for one part of the package."""
    folder, name = part.rsplit("/", 1)
    path = f"{folder}/_rels/{name}.rels"
    out: dict[str, tuple[str, str]] = {}
    if path not in z.namelist():
        return out
    for rel in ET.fromstring(z.read(path)).findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        if target.startswith("/"):
            target = target.lstrip("/")
        else:
            stack: list[str] = []
            for seg in (folder + "/" + target).split("/"):
                if seg == "..":
                    stack.pop()
                elif seg != ".":
                    stack.append(seg)
            target = "/".join(stack)
        out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], target)
    return out


def find_layouts(z: zipfile.ZipFile, master_part: str) -> dict[str, dict]:
    """Pick the layout that stands for each kind of slide.

    Returns kind -> {part, name, type}. 'closing' is only present when the
    template has a layout named for it; otherwise closing slides use the title's.
    """
    layouts = []
    for typ, target in rels_of(z, master_part).values():
        if typ != "slideLayout" or target not in z.namelist():
            continue
        root = ET.fromstring(z.read(target))
        csld = root.find("p:cSld", NS)
        layouts.append({"part": target, "type": root.get("type", ""), "name": (csld.get("name") if csld is not None else "") or ""})
    layouts.sort(key=lambda entry: [int(n) for n in re.findall(r"\d+", entry["part"])])
    chosen: dict[str, dict] = {}
    for kind, wanted in LAYOUT_TYPES.items():
        for typ in wanted:
            match = next((entry for entry in layouts if entry["type"] == typ), None)
            if match:
                chosen[kind] = match
                break
    closing = next((entry for entry in layouts if CLOSING_NAMES.search(entry["name"]) and entry is not chosen.get("title")), None)
    if closing:
        chosen["closing"] = closing
    return chosen


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def soffice() -> str | None:
    """The LibreOffice program, or None. DYNAMIC_DECKS_SOFFICE=none switches rendering off."""
    forced = os.environ.get("DYNAMIC_DECKS_SOFFICE")
    if forced:
        return None if forced.lower() in ("none", "off", "0") else forced
    return shutil.which("soffice") or shutil.which("libreoffice")


def one_slide_copy(src: Path, layout_part: str, dest: Path) -> None:
    """Write a copy of the template holding a single empty slide on one layout."""
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        old_slides = {n for n in names if re.fullmatch(r"ppt/slides/(_rels/)?[^/]+", n)}
        pres_rels = ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
        for rel in list(pres_rels):
            if rel.get("Type") == SLIDE_TYPE:
                pres_rels.remove(rel)
        used = {rel.get("Id") for rel in pres_rels}
        rid = next(f"rId{n}" for n in range(900, 2000) if f"rId{n}" not in used)
        ET.SubElement(pres_rels, f"{{{NS['rel']}}}Relationship", {"Id": rid, "Type": SLIDE_TYPE, "Target": "slides/slide1.xml"})

        pres = z.read("ppt/presentation.xml").decode("utf-8")
        pres = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>|<p:sldIdLst\s*/>", "", pres, flags=re.S)
        entry = f'<p:sldIdLst><p:sldId id="256" r:id="{rid}"/></p:sldIdLst>'
        if 'xmlns:r=' not in pres.split(">", 2)[1] and "xmlns:r=" not in pres[:2000]:
            pres = pres.replace("<p:presentation ", f'<p:presentation xmlns:r="{NS["r"]}" ', 1)
        pres, n = re.subn(r"(<p:sldSz\b)", entry + r"\1", pres, count=1)
        if not n:
            pres = pres.replace("</p:presentation>", entry + "</p:presentation>")

        types = ET.fromstring(z.read("[Content_Types].xml"))
        for override in list(types.findall("ct:Override", NS)):
            part = override.get("PartName", "")
            if part.startswith("/ppt/slides/"):
                types.remove(override)
            elif part == "/ppt/presentation.xml":      # a .potx is opened as a presentation
                override.set("ContentType", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")
        ET.SubElement(types, f"{{{NS['ct']}}}Override", {
            "PartName": "/ppt/slides/slide1.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"})

        ET.register_namespace("", NS["rel"])
        rels_xml = ET.tostring(pres_rels, encoding="unicode")
        ET.register_namespace("", NS["ct"])
        types_xml = ET.tostring(types, encoding="unicode")
        target = os.path.relpath(layout_part, "ppt/slides")
        slide_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{NS["rel"]}">'
                      f'<Relationship Id="rId1" Type="{LAYOUT_TYPE}" Target="{target}"/></Relationships>')
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                if name in old_slides or name in ("ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "[Content_Types].xml"):
                    continue
                out.writestr(name, z.read(name))
            out.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + types_xml)
            out.writestr("ppt/presentation.xml", pres)
            out.writestr("ppt/_rels/presentation.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + rels_xml)
            out.writestr("ppt/slides/slide1.xml", SLIDE_XML)
            out.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)


def render(src: Path, layouts: dict[str, dict], work: Path, timeout: int = 180) -> tuple[dict[str, Path], str]:
    """Draw each kind's empty slide. Returns (kind -> PNG, why nothing came back)."""
    program = soffice()
    if not program:
        return {}, "LibreOffice is not installed"
    work.mkdir(parents=True, exist_ok=True)
    decks = []
    for kind, entry in layouts.items():
        deck = work / f"{kind}.pptx"
        try:
            one_slide_copy(src, entry["part"], deck)
        except Exception as exc:  # noqa: BLE001
            return {}, f"could not prepare the template for rendering ({exc})"
        decks.append(deck)
    size = ('png:impress_png_Export:{"PixelWidth":{"type":"long","value":"%d"},"PixelHeight":{"type":"long","value":"%d"}}'
            % (STAGE_W, STAGE_H))
    profile = work / "profile"                  # its own profile, so a running LibreOffice is left alone
    try:
        proc = subprocess.run([program, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", size,
                               "--outdir", str(work)] + [str(d) for d in decks],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"LibreOffice did not finish ({exc.__class__.__name__})"
    out = {kind: work / f"{kind}.png" for kind in layouts if (work / f"{kind}.png").is_file()}
    if not out:
        return {}, "LibreOffice produced no pictures: " + (proc.stderr or proc.stdout or "").strip()[:200]
    return out, ""


# --------------------------------------------------------------------------
# What the template says about one layout: text boxes, artwork, fill
# --------------------------------------------------------------------------
TITLE_TYPES = ("title", "ctrTitle")
BODY_TYPES = (None, "body", "obj", "subTitle")
DEFAULT_SAFE = (120, 88, 1680, 872)             # the built-in theme's frame


def _boxes(root, size: tuple[int, int]) -> dict[str, list]:
    cx, cy = size
    out: dict[str, list] = {"title": [], "body": []}
    tree = root.find("p:cSld/p:spTree", NS)
    for sp in (tree.findall("p:sp", NS) if tree is not None else []):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is None:
            continue
        typ = ph.get("type")
        role = "title" if typ in TITLE_TYPES else "body" if typ in BODY_TYPES else None
        if role is None:
            continue
        off, ext = sp.find("p:spPr/a:xfrm/a:off", NS), sp.find("p:spPr/a:xfrm/a:ext", NS)
        box = None
        if off is not None and ext is not None:
            box = (int(off.get("x")) * STAGE_W / cx, int(off.get("y")) * STAGE_H / cy,
                   int(ext.get("cx")) * STAGE_W / cx, int(ext.get("cy")) * STAGE_H / cy)
        out[role].append(box)
    return out


def text_area(layout, master, size: tuple[int, int]) -> tuple | None:
    """The rectangle the template's own title and text boxes cover on this layout, in stage px."""
    mine, parent = _boxes(layout, size), _boxes(master, size)
    found = []
    for role in ("title", "body"):
        for box in mine[role]:
            box = box or next((b for b in parent[role] if b), None)   # a box with no position takes the master's
            if box:
                found.append(box)
    if not found:
        return None
    left, top = min(b[0] for b in found), min(b[1] for b in found)
    right, bottom = max(b[0] + b[2] for b in found), max(b[1] + b[3] for b in found)
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(STAGE_W), right), min(float(STAGE_H), bottom)
    if right - left < 200 or bottom - top < 120:
        return None
    return (round(left), round(top), round(right - left), round(bottom - top))


def art_count(layout, master) -> int:
    """Shapes and pictures that are decoration, not text boxes, visible on this layout."""
    def count(root) -> int:
        tree = root.find("p:cSld/p:spTree", NS)
        if tree is None:
            return 0
        n = len(tree.findall("p:pic", NS)) + len(tree.findall("p:grpSp", NS)) + len(tree.findall("p:cxnSp", NS))
        return n + sum(1 for sp in tree.findall("p:sp", NS) if sp.find("p:nvSpPr/p:nvPr/p:ph", NS) is None)
    n = count(layout)
    if layout.get("showMasterSp", "1") not in ("0", "false"):
        n += count(master)
    return n


def fill_of(layout, master, layout_part: str, master_part: str):
    """(kind, element, owning part) of the background fill a layout ends up with."""
    for root, part in ((layout, layout_part), (master, master_part)):
        bg = root.find("p:cSld/p:bg", NS)
        if bg is None:
            continue
        for kind, path in (("solid", "p:bgPr/a:solidFill"), ("gradient", "p:bgPr/a:gradFill"), ("picture", "p:bgPr/a:blipFill"),
                           ("pattern", "p:bgPr/a:pattFill"), ("ref", "p:bgRef")):
            el = bg.find(path, NS)
            if el is not None:
                return kind, el, part
    return "none", None, master_part


def css_gradient(grad, resolve) -> str | None:
    """A straight-line PowerPoint gradient as CSS, or None when it is another kind."""
    lin = grad.find("a:lin", NS)
    stops = []
    for gs in grad.findall("a:gsLst/a:gs", NS):
        color = resolve(gs)
        if not color or any(child.find("a:alpha", NS) is not None for child in gs):
            return None
        stops.append((int(gs.get("pos", "0")) / 1000, color))
    if lin is None or len(stops) < 2:
        return None
    stops.sort()
    angle = (int(lin.get("ang", "0")) / 60000 + 90) % 360   # PowerPoint counts from "left to right", CSS from "bottom to top"
    return f"linear-gradient({angle:g}deg, " + ", ".join(f"{c} {p:g}%" for p, c in stops) + ")"


def paint_gradient(css: str):
    """A small picture of a CSS linear-gradient, to measure it without a browser."""
    import math
    from PIL import Image
    m = re.match(r"linear-gradient\(([\d.]+)deg,\s*(.*)\)$", css)
    angle = math.radians(float(m.group(1)))
    stops = [(float(p) / 100, tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)))
             for c, p in re.findall(r"(#[0-9A-Fa-f]{6})\s+([\d.]+)%", m.group(2))]
    w, h = STAGE_W // 4, STAGE_H // 4
    dx, dy = math.sin(angle), -math.cos(angle)
    half = (abs(w * dx) + abs(h * dy)) / 2
    data = []
    for y in range(h):
        for x in range(w):
            t = ((x - w / 2) * dx + (y - h / 2) * dy) / (2 * half) + 0.5
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1 or (p1, c1) == stops[-1]:
                    f = 0 if p1 == p0 else max(0.0, min(1.0, (t - p0) / (p1 - p0)))
                    data.append(tuple(round(a + (b - a) * f) for a, b in zip(c0, c1)))
                    break
    im = Image.new("RGB", (w, h))
    im.putdata(data)
    return im.resize((STAGE_W, STAGE_H))


# --------------------------------------------------------------------------
# Measuring a picture
# --------------------------------------------------------------------------
def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _pixels(im) -> list:
    """The pixels of an RGB picture as (r, g, b) tuples, row by row."""
    data = im.tobytes()
    return list(zip(data[0::3], data[1::3], data[2::3]))


def _mean(pixels) -> tuple:
    n = max(1, len(pixels))
    return tuple(sum(p[i] for p in pixels) / n for i in range(3))


def _clear_of_art(safe: tuple, far: list, w: int, h: int) -> tuple:
    """Pull the text area in from artwork that runs along one of its edges (a band, a strip).

    Works on the quarter-size mask. An area that is artwork all over is left
    alone: trimming cannot help it, and it gets a panel instead.
    """
    left, top = max(0, safe[0] // 4), max(0, safe[1] // 4)
    right, bottom = min(w, (safe[0] + safe[2]) // 4), min(h, (safe[1] + safe[3]) // 4)

    def share(x0, y0, x1, y1) -> float:
        cells = [far[y * w + x] for y in range(y0, y1) for x in range(x0, x1)]
        return sum(cells) / len(cells) if cells else 0.0
    if right - left < 40 or bottom - top < 30 or share(left, top, right, bottom) > 0.5:
        return safe
    step, limit_x, limit_y = 3, (right - left) * 3 // 10, (bottom - top) * 3 // 10
    moved = {"left": 0, "right": 0, "top": 0, "bottom": 0}
    while moved["left"] < limit_x and share(left, top, left + step, bottom) > 0.4:
        left += step; moved["left"] += step
    while moved["right"] < limit_x and share(right - step, top, right, bottom) > 0.4:
        right -= step; moved["right"] += step
    while moved["top"] < limit_y and share(left, top, right, top + step) > 0.4:
        top += step; moved["top"] += step
    while moved["bottom"] < limit_y and share(left, bottom - step, right, bottom) > 0.4:
        bottom -= step; moved["bottom"] += step
    if not any(moved.values()) or share(left, top, right, bottom) > 0.08:
        return safe                             # nothing along the edges, or what is left is not clear either (a gradient, a photo)
    gap = 8                                     # breathing room between the artwork and the text
    left += gap if moved["left"] else 0
    right -= gap if moved["right"] else 0
    top += gap if moved["top"] else 0
    bottom -= gap if moved["bottom"] else 0
    return (left * 4, top * 4, (right - left) * 4, (bottom - top) * 4)


def _largest_clear(far: list, w: int, h: int, within: tuple) -> tuple | None:
    """The biggest rectangle inside `within` with no artwork in it, for a picture that comes with no text boxes.

    Works on blocks of the quarter-size mask (32 stage px a side). Returns None
    when the empty part is too small to lay a slide out in.
    """
    cell = 8
    x0, y0 = within[0] // 4 // cell, within[1] // 4 // cell
    x1, y1 = -(-(within[0] + within[2]) // 4 // cell), -(-(within[1] + within[3]) // 4 // cell)
    cols, rows = x1 - x0, y1 - y0
    if cols < 4 or rows < 4:
        return None

    def busy(cx: int, cy: int) -> bool:
        cells = [far[y * w + x] for y in range(cy * cell, min(h, (cy + 1) * cell)) for x in range(cx * cell, min(w, (cx + 1) * cell))]
        return bool(cells) and sum(cells) / len(cells) > 0.04
    best, heights = (0, None), [0] * cols
    for r in range(rows):
        for c in range(cols):
            heights[c] = 0 if busy(x0 + c, y0 + r) else heights[c] + 1
        stack: list[int] = []                    # largest rectangle under a histogram, one row at a time
        for c in range(cols + 1):
            height = heights[c] if c < cols else 0
            while stack and heights[stack[-1]] >= height:
                top = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                if top * (c - left) > best[0]:
                    best = (top * (c - left), (left, r - top + 1, c - left, top))
            stack.append(c)
    if best[1] is None:
        return None
    left, top, bw, bh = best[1]
    box = (max(within[0], (x0 + left) * cell * 4), max(within[1], (y0 + top) * cell * 4), bw * cell * 4, bh * cell * 4)
    box = (box[0], box[1], min(box[2], within[0] + within[2] - box[0]), min(box[3], within[1] + within[3] - box[1]))
    if box[2] < 900 or box[3] < 520:
        return None
    if box[0] > within[0]:                      # breathing room on a side that was moved in from the frame
        box = (box[0] + 32, box[1], box[2] - 32, box[3])
    if box[0] + box[2] < within[0] + within[2]:
        box = (box[0], box[1], box[2] - 32, box[3])
    return box


def measure(im, safe: tuple | None) -> dict:
    """Facts about a background picture: is it flat, where the artwork is, and the colors under the text area."""
    from collections import Counter
    from PIL import Image
    w, h = STAGE_W // 4, STAGE_H // 4
    small = im.convert("RGB").resize((w, h), Image.BILINEAR)
    px = _pixels(small)
    top = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in px).most_common(1)[0][0]
    dominant = _mean([p for p in px if (p[0] >> 4, p[1] >> 4, p[2] >> 4) == top])
    far = [max(abs(p[i] - dominant[i]) for i in range(3)) > 24 for p in px]
    grid = [[0.0] * 3 for _ in range(3)]
    for row in range(3):
        for col in range(3):
            cells = [far[y * w + x] for y in range(row * h // 3, (row + 1) * h // 3) for x in range(col * w // 3, (col + 1) * w // 3)]
            grid[row][col] = sum(cells) / len(cells)
    near = [max(abs(p[i] - dominant[i]) for i in range(3)) for p, is_far in zip(px, far) if not is_far]
    plain = sum(near) / max(1, len(near)) < 4   # one flat color with artwork on it, as opposed to a gradient or a photo
    found = None
    if safe is None and plain:                  # no text boxes to go by: look for the empty part of the picture
        found = _largest_clear(far, w, h, DEFAULT_SAFE)
    safe = found or (_clear_of_art(safe or DEFAULT_SAFE, far, w, h) if plain else (safe or DEFAULT_SAFE))
    x0, y0, bw, bh = safe
    crop = [px[y * w + x] for y in range(max(0, y0 // 4), min(h, (y0 + bh) // 4)) for x in range(max(0, x0 // 4), min(w, (x0 + bw) // 4))] or px
    crop.sort(key=lambda p: 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2])
    k = max(1, len(crop) // 20)
    below = y0 + bh                             # how far down the slide stays empty under the text area
    if plain:
        cols = range(max(0, x0 // 4), min(w, (x0 + bw) // 4))
        row = min(h, (y0 + bh) // 4)
        while row < h and cols and sum(far[row * w + x] for x in cols) / len(cols) < 0.01:
            row += 1
        below = row * 4
    return {
        "safe": safe,                           # the text area, pulled in from any artwork along its edges
        "found": found is not None and tuple(found) != DEFAULT_SAFE,   # worked out from the picture, not from text boxes
        "clear_below": below,
        "overall": _hex(_mean(px)),
        "dominant": _hex(dominant),
        "art": sum(far) / len(far),             # share of the slide that is not the main color
        "grid": grid,                           # the same, for each ninth of the slide
        "mean": _hex(_mean(crop)),              # under the text area
        "dark": _hex(_mean(crop[:k])),          # its darkest twentieth
        "light": _hex(_mean(crop[-k:])),        # its lightest twentieth
        "art_in_text": sum(1 for p in crop if max(abs(p[i] - dominant[i]) for i in range(3)) > 24) / len(crop),
    }


def footer_offset(im, left: int, right: int, offset: int = 44, limit: int = 160) -> int:
    """How far above the bottom edge the footer line has to sit to stay off artwork (a strip, a band)."""
    from collections import Counter
    from PIL import Image
    w, h = STAGE_W // 4, STAGE_H // 4
    px = _pixels(im.convert("RGB").resize((w, h), Image.BILINEAR))
    top = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in px).most_common(1)[0][0]
    dominant = _mean([q for q in px if (q[0] >> 4, q[1] >> 4, q[2] >> 4) == top])
    x0, x1 = max(0, left // 4), min(w, (STAGE_W - right) // 4)
    for candidate in range(offset, limit + 1, 8):
        y1 = (STAGE_H - candidate) // 4 + 1
        y0 = y1 - 9                             # the footer's line of text, 36 stage px
        cells = [max(abs(px[y * w + x][i] - dominant[i]) for i in range(3)) > 24 for y in range(max(0, y0), min(h, y1)) for x in range(x0, x1)]
        if cells and sum(cells) / len(cells) < 0.02:
            return candidate
    return offset


def choose_ink(stats: dict, dark_text: str, light_text: str) -> dict:
    """Text color for a picture, and a panel behind the text when the picture is too busy to read over."""
    from _deck import contrast, ensure_contrast, luminance, mix
    on_dark_pixels, on_light_pixels = contrast(dark_text, stats["dark"]), contrast(light_text, stats["light"])
    if max(on_dark_pixels, on_light_pixels) < 3:        # busy either way: go by the whole picture, so every
        ink = "dark" if luminance(stats.get("overall", stats["mean"])) >= 0.3 else "light"   # slide on it agrees
    else:
        ink = "dark" if on_dark_pixels >= on_light_pixels else "light"
    text = dark_text if ink == "dark" else light_text
    worst = stats["dark"] if ink == "dark" else stats["light"]
    plan = {"ink": ink, "bg": stats["mean"], "worst": worst, "panel": None, "calm": True}
    if contrast(text, worst) < 4.5:
        base = mix(stats["mean"], "#FFFFFF", 0.82) if ink == "dark" else mix(stats["mean"], "#000000", 0.78)
        other = stats["light"] if ink == "dark" else stats["dark"]
        alpha = 0.95
        for candidate in (0.74, 0.82, 0.88, 0.92, 0.95):
            # readable on the worst pixels, and the picture's own texture faint enough not to fight the text
            if (contrast(text, mix(worst, base, candidate)) >= 7
                    and contrast(mix(worst, base, candidate), mix(other, base, candidate)) <= 1.3):
                alpha = candidate
                break
        plan.update(panel={"color": base, "alpha": alpha}, calm=False,
                    worst=mix(worst, base, alpha), bg=mix(stats["mean"], base, alpha))
    plan["text"] = ensure_contrast(text, plan["worst"], 7, prefer="darker" if ink == "dark" else "lighter")
    return plan


def describe(stats: dict, plan: dict) -> str:
    """One plain sentence about where the artwork is, for whoever composes a slide by hand."""
    from _deck import luminance
    grid, art = stats["grid"], stats["art"]
    cols = [sum(grid[r][c] for r in range(3)) / 3 for c in range(3)]
    rows = [sum(grid[r]) / 3 for r in range(3)]
    tone = "A light" if luminance(stats["dominant"]) >= 0.3 else "A dark"
    if art > 0.7 and min(min(r) for r in grid) > 0.35:
        where = "Artwork fills the whole slide"
    else:
        col_names, row_names = ("the left third", "the middle third", "the right third"), ("the top", "the middle", "the bottom")
        spots = [col_names[c] for c in range(3) if cols[c] > 0.5]
        if not spots:
            spots = [("a band across " + row_names[r]) for r in range(3) if rows[r] > 0.5]
        if not spots:
            corner = (("the upper left", "the top", "the upper right"), ("the left edge", "the center", "the right edge"),
                      ("the lower left", "the bottom", "the lower right"))
            cells = sorted(((grid[r][c], corner[r][c]) for r in range(3) for c in range(3)), reverse=True)
            spots = [name for share, name in cells[:3] if share > 0.12]
        where = (f"{tone} background with artwork in " + " and ".join(spots)) if spots else f"{tone} background with only small marks"
    ink = "dark text" if plan["ink"] == "dark" else "light text"
    tail = f"Use {ink}." if plan["calm"] else f"It is too busy to read over, so the theme puts a panel behind the text; use {ink}."
    return f"{where}. {tail}"


# --------------------------------------------------------------------------
# From a template to one entry per kind of slide
# --------------------------------------------------------------------------
def _entry(im, safe, dark_text: str, light_text: str, mode: str) -> dict:
    stats = measure(im, safe)
    from _deck import contrast
    if stats["art"] < 0.003 and contrast(stats["dark"], stats["light"]) < 1.12:
        return {"flat": stats["dominant"]}
    if mode != "always" and stats["art"] < 0.025:
        return {"flat": stats["dominant"], "marks": round(stats["art"], 4)}
    plan = choose_ink(stats, dark_text, light_text)
    known = bool(safe) or stats["found"]
    return {"image": im, "safe": tuple(stats["safe"]) if known else None, "art": round(stats["art"], 3),
            "clear_below": stats["clear_below"] if safe else None,
            "description": describe(stats, plan), **plan}


def roomy(safe: tuple, min_w: int = 1100, min_h: int = 720, margin: int = 64) -> tuple:
    """Grow a text area about its center to a least size, staying on the slide.

    For title and section slides on a picture too busy to read over: the panel
    is drawn over this area, so it has to hold a two-line title whatever size
    the template's own box was.
    """
    x, y, w, h = safe
    if w < min_w:
        x, w = x - (min_w - w) / 2, min_w
    if h < min_h:
        y, h = y - (min_h - h) / 2, min_h
    x = max(margin, min(x, STAGE_W - margin - w))
    y = max(margin, min(y, STAGE_H - margin - h))
    return (round(x), round(y), round(min(w, STAGE_W - 2 * margin)), round(min(h, STAGE_H - 2 * margin)))


RESERVED = {"none", "content", "title", "section", "closing", "image", "panel"}   # names a layout may not take
MAX_MORE = 12


def other_layouts(z: zipfile.ZipFile, master_part: str, taken: set[str]) -> list[dict]:
    """The master's remaining layouts that may have a look of their own.

    A layout qualifies when it sets its own background, carries its own
    artwork, or switches the master's shapes off. Whether it really differs
    from the content layout is decided later, from the pictures.
    """
    names = set(z.namelist())
    found = []
    for typ, target in rels_of(z, master_part).values():
        if typ != "slideLayout" or target in taken or target not in names:
            continue
        root = ET.fromstring(z.read(target))
        csld = root.find("p:cSld", NS)
        tree = root.find("p:cSld/p:spTree", NS)
        art = 0
        if tree is not None:
            art = (len(tree.findall("p:pic", NS)) + len(tree.findall("p:grpSp", NS)) + len(tree.findall("p:cxnSp", NS))
                   + sum(1 for sp in tree.findall("p:sp", NS) if sp.find("p:nvSpPr/p:nvPr/p:ph", NS) is None))
        own_bg = root.find("p:cSld/p:bg", NS) is not None
        if own_bg or art or root.get("showMasterSp", "1") in ("0", "false"):
            found.append({"part": target, "type": root.get("type", ""), "own_bg": own_bg,
                          "name": (csld.get("name") if csld is not None else "") or root.get("type", "") or "layout"})
    found.sort(key=lambda entry: [int(n) for n in re.findall(r"\d+", entry["part"])])
    return found


def slug(name: str, used: set[str]) -> str:
    """A layout's name as a word a slide can put in data-bg."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "layout"
    word, n = base, 2
    while word in RESERVED or word in used:
        word, n = f"{base}-{n}", n + 1
    used.add(word)
    return word


def _same_look(a: dict, b: dict) -> bool:
    """Whether two entries would look the same behind a slide."""
    if "flat" in a or "flat" in b:
        if not ("flat" in a and "flat" in b):
            return False
        ca, cb = (tuple(int(e["flat"][i:i + 2], 16) for i in (1, 3, 5)) for e in (a, b))
        return max(abs(x - y) for x, y in zip(ca, cb)) <= 6
    if a.get("css") or b.get("css"):
        return a.get("css") == b.get("css")
    from PIL import Image, ImageChops, ImageStat
    small = [e["image"].convert("RGB").resize((96, 54), Image.BILINEAR) for e in (a, b)]
    return max(ImageStat.Stat(ImageChops.difference(*small)).mean) < 1.5


def from_template(src: Path, z: zipfile.ZipFile, master_part: str, size: tuple[int, int], resolve,
                  dark_text: str, light_text: str, mode: str = "auto", work: Path | None = None,
                  more: bool = True) -> tuple[dict, dict, list[str]]:
    """Backgrounds from a template. Returns (kind -> entry, name -> entry, notes).

    The first dict has the four kinds of slide (content, title, section,
    closing). The second has every other layout that looks different from all
    of those, under a name made from the layout's own; a slide asks for one
    with data-bg. An entry is {"flat": color} for a plain background, or a
    picture entry: image (PIL) or css (a gradient), safe, ink, text, bg,
    worst, panel, calm, art, description, layout, rendered.
    """
    notes: list[str] = []
    if mode == "never":
        return {}, {}, notes
    try:
        from PIL import Image
    except ImportError:
        return {}, {}, ["Pillow is not installed, so the template's backgrounds could not be examined; flat colors were used"]
    layouts = find_layouts(z, master_part)
    if "content" not in layouts:
        return {}, {}, ["the template has no ordinary content layout; its backgrounds were not examined"]
    others = other_layouts(z, master_part, {entry["part"] for entry in layouts.values()}) if more else []
    if len(others) > MAX_MORE:
        notes.append(f"the template has {len(others)} more layouts with a look of their own; the first {MAX_MORE} were examined")
        others = others[:MAX_MORE]
    work = work or Path(tempfile.mkdtemp(prefix="dynamic-decks-bg-"))
    to_draw = dict(layouts)
    to_draw.update({f"more{i}": entry for i, entry in enumerate(others)})
    pictures, why = render(src, to_draw, work / "render")
    master = ET.fromstring(z.read(master_part))
    state: dict = {"skipped_art": False, "marks": []}

    def examine(key: str, entry: dict, what: str, hero: bool) -> dict | None:
        layout = ET.fromstring(z.read(entry["part"]))
        safe = text_area(layout, master, size)
        fill, el, owner = fill_of(layout, master, entry["part"], master_part)
        shapes = art_count(layout, master)
        css = css_gradient(el, resolve) if fill == "gradient" else None
        im = None
        if key in pictures:
            im = Image.open(pictures[key]).convert("RGB")
        elif fill == "picture":
            blip = el.find("a:blip", NS)
            target = rels_of(z, owner).get(blip.get(f"{{{NS['r']}}}embed") if blip is not None else "", ("", ""))[1]
            if target in z.namelist():
                try:
                    import io
                    im = Image.open(io.BytesIO(z.read(target))).convert("RGB").resize((STAGE_W, STAGE_H), Image.LANCZOS)
                except Exception:  # noqa: BLE001
                    im = None
        elif css:
            im = paint_gradient(css)
        if key not in pictures and shapes and fill != "solid":
            state["skipped_art"] = True
        if im is None:
            if key not in pictures and fill in ("gradient", "pattern"):
                notes.append(f"the background of {what} is a {fill} that could not be read without LibreOffice; a flat color was used")
            if key not in pictures and shapes:
                state["skipped_art"] = True
            if fill == "solid" and resolve(el):   # not drawn, but the file says which flat color it is
                return {"flat": resolve(el)}
            return None
        result = _entry(im, safe, dark_text, light_text, mode)
        if "flat" not in result:
            if css and (shapes == 0 or key not in pictures):
                # a plain gradient stays as code: exact, sharp, and tiny. So does one whose shapes could not be drawn.
                result["css"], result["image"] = css, None
                colors = re.findall(r"#[0-9A-Fa-f]{6}", css)
                extra = " with nothing else on it" if shapes == 0 else "; the shapes the template draws over it were left out"
                result["description"] = (f"A gradient from {colors[0]} to {colors[-1]}{extra}. "
                                         + result["description"].rsplit(". ", 1)[-1])
            if hero and not result["calm"] and result.get("safe"):
                result["safe"] = roomy(result["safe"])
            result.update(layout=entry["name"] or entry["type"], rendered=key in pictures)
        elif result.get("marks"):
            state["marks"].append((what, result["marks"]))
        return result

    out: dict[str, dict] = {}
    for kind, entry in layouts.items():
        result = examine(kind, entry, f"the {kind} slide", kind != "content")
        if result is not None:
            out[kind] = result

    extra: dict[str, dict] = {}
    used: set[str] = set()
    for i, entry in enumerate(others):
        if f"more{i}" not in pictures and not entry["own_bg"]:
            continue                              # nothing to go by without a drawing
        result = examine(f"more{i}", entry, f"the \"{entry['name']}\" layout", False)
        if result is None or any(_same_look(result, seen) for seen in list(out.values()) + list(extra.values())):
            continue
        result.setdefault("layout", entry["name"])
        extra[slug(entry["name"], used)] = result

    if state["marks"]:
        where = [what for what, _ in state["marks"]]
        listed = where[0] if len(where) == 1 else ", ".join(where[:-1]) + " and " + where[-1]
        notes.append(f"{listed} {'has' if len(where) == 1 else 'have'} small marks ({max(m for _, m in state['marks']) * 100:.1f}% of the "
                     "slide, often a logo) that were left out of the background; pass --backgrounds always to keep them as a picture")
    if not pictures:
        notes.append(f"{why}, so backgrounds were read from the file instead of being drawn"
                     + ("; artwork made of shapes was left out" if state["skipped_art"] else "")
                     + ". Install LibreOffice and run this again for an exact copy.")
    elif len(pictures) < len(to_draw):
        notes.append("LibreOffice drew only some of the layouts; the others use a flat color")
    return out, extra, notes


def from_files(files: dict[str, Path], dark_text: str, light_text: str) -> tuple[dict, list[str]]:
    """Backgrounds from pictures the user supplies, one per kind of slide."""
    from PIL import Image
    out, notes = {}, []
    for kind, path in files.items():
        if kind not in KINDS:
            notes.append(f"'{kind}' is not a kind of slide (use one of: {', '.join(KINDS)}); {path} was not used")
            continue
        try:
            im = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"could not read the background {path} ({exc})")
            continue
        if abs(im.width / im.height - 16 / 9) > 0.03:
            notes.append(f"the {kind} background is {im.width}x{im.height}, not 16:9; it was cropped to fit")
            scale = max(STAGE_W / im.width, STAGE_H / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            left, top = (im.width - STAGE_W) // 2, (im.height - STAGE_H) // 2
            im = im.crop((left, top, left + STAGE_W, top + STAGE_H))
        else:
            im = im.resize((STAGE_W, STAGE_H), Image.LANCZOS)
        result = _entry(im, None, dark_text, light_text, "always")
        if "flat" not in result:
            result.update(layout=Path(path).name, rendered=False)
        out[kind] = result
    return out, notes


def save(entry: dict, folder: Path, kind: str, saved: dict[str, str]) -> str | None:
    """Write an entry's picture into the theme and return its file name. Identical pictures share a file."""
    im = entry.get("image")
    if im is None:
        return None
    import io
    key = hashlib.sha1(im.tobytes()).hexdigest()
    if key in saved:
        return saved[key]
    folder.mkdir(parents=True, exist_ok=True)
    name, data = f"{kind}.png", None
    try:
        buf = io.BytesIO()
        im.save(buf, "WEBP", lossless=True, method=4)
        if buf.tell() > 350 * 1024:               # a photo: lossless is too heavy for every deck to carry
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=88, method=5)
        name, data = f"{kind}.webp", buf.getvalue()
    except Exception:  # noqa: BLE001  (Pillow built without WebP)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
    (folder / name).write_bytes(data)
    saved[key] = name
    return name
