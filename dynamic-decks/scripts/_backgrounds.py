"""Slide backgrounds from a PowerPoint template.

A template's artwork (photos, gradients, bands, corner marks) is kept by
rendering it, not by rebuilding it: for each kind of slide a one-slide copy of
the template is made with nothing on the slide, LibreOffice draws it, and the
picture becomes that kind's background. The picture is then measured once, so
slides built later never have to look at it:

    text area    where the template's own title and text boxes sit. The boxes
                 are the authority: text goes where the template puts text,
                 over a band or a tint included
    ink          dark or light text, from the pixels under each box
    calm         whether text can sit straight on the picture, or needs a panel
    description  a sentence about where the artwork is, for composing by hand

Pictures are drawn at twice the stage size, so fine lines and any text
that is part of the artwork stay sharp full screen and on dense displays.

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
RENDER_SCALE = 2                                # pictures are drawn and kept at twice the stage size
MAX_W, MAX_H = STAGE_W * RENDER_SCALE, STAGE_H * RENDER_SCALE
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


NAMED = {                                       # what layouts are usually called, for templates that give no type
    "title": re.compile(r"^(title|cover|opening|front)( slide| page)?( \d+)?$|title slide|cover slide", re.I),
    "section": re.compile(r"section|divider|chapter|break|transition", re.I),
    "content": re.compile(r"title\s*(and|&|\+|,|with)?\s*(content|text|body|bullets?)\b(?! with)|^(content|text|bullets?|body|standard|default|basic)"
                          r"( slide)?( \d+)?$|^(1|one)[ -]?(column|content)", re.I),
}
FOOTER_TYPES = ("dt", "ftr", "sldNum", "hdr")


def text_shapes(root, size: tuple[int, int] | None = None) -> tuple:
    """A layout's text placeholders as (the title's shape or None, the other text shapes).

    The title is the title placeholder when there is one. Templates do not
    always have one: the box may be an ordinary text placeholder that only its
    name ("Title 1") marks as the title, or nothing but its place, a short box
    above all the others. Both count, so that such a layout is read like any other.
    """
    tree = root.find("p:cSld/p:spTree", NS) if root is not None else None
    texts, title = [], None
    for sp in (tree.findall("p:sp", NS) if tree is not None else []):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is None or ph.get("type") in FOOTER_TYPES:
            continue
        if ph.get("type") in TITLE_TYPES and title is None:
            title = sp
        elif ph.get("type") in BODY_TYPES:
            texts.append(sp)
    if title is None:
        named = [sp for sp in texts if re.match(r"\s*title\b", (sp.find("p:nvSpPr/p:cNvPr", NS).get("name") or ""), re.I)
                 and "sub" not in (sp.find("p:nvSpPr/p:cNvPr", NS).get("name") or "").lower()]
        if named:
            title = named[0]
        elif len(texts) >= 2:
            def frame(sp):
                off, ext = sp.find("p:spPr/a:xfrm/a:off", NS), sp.find("p:spPr/a:xfrm/a:ext", NS)
                return (int(off.get("y")), int(ext.get("cy"))) if off is not None and ext is not None else None
            placed = [(frame(sp), sp) for sp in texts if frame(sp)]
            if len(placed) == len(texts):
                placed.sort(key=lambda item: item[0][0])
                (top, tall), first = placed[0]
                slide_h = size[1] if size else 6858000
                if tall < 0.25 * slide_h and all(top + tall <= other[0][0] + 0.02 * slide_h for other in placed[1:]):
                    title = first
        if title is not None:
            texts = [sp for sp in texts if sp is not title]
    return title, texts


def list_layouts(z: zipfile.ZipFile, master_part: str) -> list[dict]:
    """Every layout of a master, in PowerPoint's order: part, name, type, how many slides use it, what text it holds."""
    names = set(z.namelist())
    used: dict[str, int] = {}
    for part in (n for n in names if re.fullmatch(r"ppt/slides/[^/]+\.xml", n)):
        layout = next((t for typ, t in rels_of(z, part).values() if typ == "slideLayout"), None)
        if layout:
            used[layout] = used.get(layout, 0) + 1
    layouts = []
    for typ, target in rels_of(z, master_part).values():
        if typ != "slideLayout" or target not in names:
            continue
        root = ET.fromstring(z.read(target))
        csld = root.find("p:cSld", NS)
        title, texts = text_shapes(root)
        layouts.append({"part": target, "type": root.get("type", ""), "name": (csld.get("name") if csld is not None else "") or "",
                        "slides": used.get(target, 0), "has_title": title is not None, "texts": len(texts)})
    layouts.sort(key=lambda entry: [int(n) for n in re.findall(r"\d+", entry["part"])])
    return layouts


def describe_layouts(layouts: list[dict]) -> str:
    return ", ".join(f'{i} "{entry["name"] or entry["type"] or "unnamed"}"'
                     + (f' ({entry["slides"]} slide{"" if entry["slides"] == 1 else "s"})' if entry["slides"] else "")
                     for i, entry in enumerate(layouts, 1))


def find_layouts(z: zipfile.ZipFile, master_part: str, picks: dict | None = None, problems: list | None = None) -> dict[str, dict]:
    """Pick the layout that stands for each kind of slide.

    Returns kind -> {part, name, type, how}. `picks` names a layout for a kind
    outright (a number from 1, or a name). Otherwise a layout is known by its
    type; when the template gives none, as custom layouts do not, by its name;
    and for the content kind, failing both, by what is on it: a title and one
    text box, and of those the one most slides use. 'closing' is only present
    when a layout is named for it; otherwise closing slides use the title's.
    A pick that matches nothing is added to `problems`.
    """
    layouts = list_layouts(z, master_part)
    chosen: dict[str, dict] = {}

    def take(kind: str, entry: dict, how: str) -> None:
        chosen[kind] = dict(entry, how=how)

    for kind, wanted in (picks or {}).items():
        text = str(wanted).strip()
        match = None
        if text.isdigit() and 1 <= int(text) <= len(layouts):
            match = layouts[int(text) - 1]
        else:
            exact = [e for e in layouts if e["name"].lower() == text.lower()]
            close = exact or [e for e in layouts if text.lower() in e["name"].lower()]
            match = close[0] if len(close) == 1 or exact else None
        if match is not None and kind in KINDS:
            take(kind, match, "it was asked for")
        elif problems is not None:
            problems.append(f'--layout {kind}="{text}" matches no single layout')
    taken = lambda: {e["part"] for e in chosen.values()}          # noqa: E731
    for kind in ("title", "section", "content"):
        if kind in chosen:
            continue
        for typ in LAYOUT_TYPES[kind]:
            match = next((e for e in layouts if e["type"] == typ and e["part"] not in taken()), None)
            if match:
                take(kind, match, "its type says so")
                break
    for kind in ("title", "section", "content"):
        if kind in chosen:
            continue
        named = [e for e in layouts if NAMED[kind].search(e["name"]) and e["part"] not in taken()
                 and (kind != "content" or e["texts"] >= 1)]
        if named:
            take(kind, max(named, key=lambda e: e["slides"]) if kind == "content" else named[0], "its name says so")
    if "content" not in chosen:
        likely = [e for e in layouts if e["has_title"] and e["texts"] == 1 and e["part"] not in taken()]
        if likely:
            best = max(likely, key=lambda e: e["slides"])
            take("content", best, "it has a title and one text box" + (", and most slides use it" if best["slides"] else ""))
    if "closing" not in chosen:
        closing = next((e for e in layouts if CLOSING_NAMES.search(e["name"]) and e["part"] not in taken()), None)
        if closing:
            take("closing", closing, "its name says so")
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


SHAPE = re.compile(rb"<p:(sp|cxnSp|pic)\b.*?</p:\1>", re.S)
SHAPE_PROPS = re.compile(rb"<p:spPr\b.*?</p:spPr>", re.S)


def cancel_effects(xml: bytes) -> bytes:
    """Make a shape's "no effects" explicit enough for LibreOffice.

    A PowerPoint shape can carry a style that asks for one of the theme's
    effects, usually a shadow, and then switch it off with an empty effect
    list of its own. PowerPoint honors the empty list. LibreOffice ignores it
    and draws the shadow, which turns a thin rule into a rule with a gray
    smear under it. Pointing such a shape's style at "no effect" gives the
    same picture in both.
    """
    def fix(match):
        shape = match.group(0)
        props = SHAPE_PROPS.search(shape)
        if props is None or b"<a:effectLst/>" not in props.group(0):
            return shape
        return re.sub(rb'(<a:effectRef\b[^>]*\bidx=")[1-9]\d*(")', rb"\g<1>0\2", shape)
    return SHAPE.sub(fix, xml)


SAMPLE = {"title": "A title for this slide", "sub": "A line of supporting text",
          "body": ["First point", ("A detail under it", 1), "Second point"]}


def sample_slide(layout_xml: bytes, points: bool = True) -> str:
    """A slide that fills a layout's own placeholders with a few words, to see how the template sets text there.

    `points` puts bullet points in the first text box (a content slide);
    without it every text box gets one supporting line (a title or section slide).
    """
    root = ET.fromstring(layout_xml)
    title, texts = text_shapes(root)
    shapes, n = [], 2
    for sp in ([title] if title is not None else []) + texts:
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        attrs = "".join(f' {k}="{v}"' for k, v in ph.attrib.items() if k in ("type", "idx", "sz", "orient"))
        if sp is title:
            paras = [(SAMPLE["title"], 0)]
        elif not points or ph.get("type") == "subTitle" or (title is not None and len(texts) > 1 and sp is not texts[0]):
            paras = [(SAMPLE["sub"], 0)]
        else:
            paras = [(item, 0) if isinstance(item, str) else item for item in SAMPLE["body"]]
        body = "".join("<a:p>" + (f'<a:pPr lvl="{lvl}"/>' if lvl else "") + f'<a:r><a:rPr lang="en-US"/><a:t>{text}</a:t></a:r></a:p>'
                       for text, lvl in paras)
        shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{n}" name="Sample {n}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                      f'<p:nvPr><p:ph{attrs}/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{body}</p:txBody></p:sp>')
        n += 1
    return SLIDE_XML.replace("<p:grpSpPr/></p:spTree>", "<p:grpSpPr/>" + "".join(shapes) + "</p:spTree>")


def one_slide_copy(src: Path, layout_part: str, dest: Path, filled: str = "") -> None:
    """Write a copy of the template holding a single slide on one layout: empty, or `filled` with sample
    text ("points" for a content slide, "line" for a title or section slide)."""
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
                data = z.read(name)
                if re.fullmatch(r"ppt/slide(Masters|Layouts)/[^/]+\.xml", name):
                    data = cancel_effects(data)
                out.writestr(name, data)
            out.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + types_xml)
            out.writestr("ppt/presentation.xml", pres)
            out.writestr("ppt/_rels/presentation.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + rels_xml)
            out.writestr("ppt/slides/slide1.xml", sample_slide(z.read(layout_part), filled == "points") if filled else SLIDE_XML)
            out.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)


def render(src: Path, layouts: dict[str, dict], work: Path, timeout: int = 180,
           filled: bool = False, size: tuple[int, int] | None = None) -> tuple[dict[str, Path], str]:
    """Draw each kind's slide: empty for a background, or `filled` with sample text to show how the
    template itself sets a slide of that kind. Returns (kind -> PNG, why nothing came back)."""
    program = soffice()
    if not program:
        return {}, "LibreOffice is not installed"
    work.mkdir(parents=True, exist_ok=True)
    decks = []
    for kind, entry in layouts.items():
        deck = work / f"{kind}.pptx"
        try:
            one_slide_copy(src, entry["part"], deck, ("points" if kind == "content" else "line") if filled else "")
        except Exception as exc:  # noqa: BLE001
            return {}, f"could not prepare the template for rendering ({exc})"
        decks.append(deck)
    size = ('png:impress_png_Export:{"PixelWidth":{"type":"long","value":"%d"},"PixelHeight":{"type":"long","value":"%d"}}'
            % (size or (MAX_W, MAX_H)))
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


INSETS = {"lIns": 91440, "tIns": 45720, "rIns": 91440, "bIns": 45720}      # PowerPoint's own, in EMU


def _placeholders(root, role: str) -> list:
    title, texts = text_shapes(root)
    return ([title] if title is not None else []) if role == "title" else texts


def _text_box(sp, fallback, size: tuple[int, int]) -> tuple | None:
    """Where a placeholder's text can sit, in stage px: its box, less the inset PowerPoint keeps inside it.

    A placeholder with no position, or no inset, of its own takes the master's (`fallback`).
    """
    cx, cy = size
    box = None
    for source in (sp, fallback):
        if source is None:
            continue
        off, ext = source.find("p:spPr/a:xfrm/a:off", NS), source.find("p:spPr/a:xfrm/a:ext", NS)
        if off is not None and ext is not None:
            box = [int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))]
            break
    if box is None:
        return None
    inset = dict(INSETS)
    for source in (fallback, sp):                # the layout's own setting wins
        body = source.find("p:txBody/a:bodyPr", NS) if source is not None else None
        for key in inset:
            if body is not None and body.get(key, "").isdigit():
                inset[key] = int(body.get(key))
    x, y = box[0] + inset["lIns"], box[1] + inset["tIns"]
    w, h = box[2] - inset["lIns"] - inset["rIns"], box[3] - inset["tIns"] - inset["bIns"]
    if w <= 0 or h <= 0:
        return None
    return (x * STAGE_W / cx, y * STAGE_H / cy, w * STAGE_W / cx, h * STAGE_H / cy)


def _union(boxes: list) -> tuple | None:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    left, top = max(0.0, min(b[0] for b in boxes)), max(0.0, min(b[1] for b in boxes))
    right = min(float(STAGE_W), max(b[0] + b[2] for b in boxes))
    bottom = min(float(STAGE_H), max(b[1] + b[3] for b in boxes))
    return (round(left), round(top), round(right - left), round(bottom - top))


def text_boxes(layout, master, size: tuple[int, int]) -> dict:
    """The template's own text boxes on a layout: {"title": box, "body": box, "anchor": start|center|end}.

    `title` is the title box, `body` everything the other text boxes cover,
    either None when the layout has none. `anchor` is where the title sits in
    its box top to bottom. All in stage px, insets taken off.
    """
    m_title, m_body = (_placeholders(master, role)[:1] or [None] for role in ("title", "body"))
    titles = [_text_box(sp, m_title[0], size) for sp in _placeholders(layout, "title")]
    bodies = [_text_box(sp, m_body[0], size) for sp in _placeholders(layout, "body")]
    anchor = None
    for sp in _placeholders(layout, "title")[:1] + [m_title[0]]:
        body = sp.find("p:txBody/a:bodyPr", NS) if sp is not None else None
        if body is not None and body.get("anchor"):
            anchor = body.get("anchor")
            break
    return {"title": _union(titles[:1]), "body": _union(bodies),
            "anchor": {"ctr": "center", "b": "end"}.get(anchor or "t", "start")}


def content_boxes(layout, master, size: tuple[int, int]) -> dict | None:
    """text_boxes for a content layout, or None when it does not have a title above a text box."""
    boxes = text_boxes(layout, master, size)
    if boxes["title"] and boxes["body"] and boxes["title"][1] + boxes["title"][3] <= boxes["body"][1] + 12:
        return boxes
    return None


def text_area(layout, master, size: tuple[int, int]) -> tuple | None:
    """The rectangle the template's own title and text boxes cover on this layout, in stage px."""
    boxes = text_boxes(layout, master, size)
    area = _union([boxes["title"], boxes["body"]])
    if area is None or area[2] < 200 or area[3] < 120:
        return None
    return area


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


def _fit(box: tuple, far: list, w: int, h: int) -> tuple[tuple, dict]:
    """A template text box, checked against the picture. Returns (box, how far each side was pulled in).

    The box is the template's word on where text goes, and it stands: a box
    that lies on artwork (a title on a band, text on a tinted panel) is meant
    to. The one correction is for a box whose edge runs a little way under
    artwork along the slide's side, as when a layout was left with default
    boxes: that edge is pulled in, by at most 15% of the box.
    """
    left, top = max(0, int(box[0]) // 4), max(0, int(box[1]) // 4)
    right, bottom = min(w, int(box[0] + box[2]) // 4), min(h, int(box[1] + box[3]) // 4)

    def share(x0, y0, x1, y1) -> float:
        cells = [far[y * w + x] for y in range(y0, y1) for x in range(x0, x1)]
        return sum(cells) / len(cells) if cells else 0.0
    if right - left < 40 or bottom - top < 20 or share(left, top, right, bottom) > 0.5:
        return box, {}
    step, limit_x, limit_y = 3, (right - left) * 15 // 100, (bottom - top) * 15 // 100
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
        return box, {}                          # nothing along the edges, or what is left is not clear either
    gap = 8                                     # breathing room between the artwork and the text
    left += gap if moved["left"] else 0
    right -= gap if moved["right"] else 0
    top += gap if moved["top"] else 0
    bottom -= gap if moved["bottom"] else 0
    return ((left * 4, top * 4, (right - left) * 4, (bottom - top) * 4),
            {side: (n + gap) * 4 for side, n in moved.items() if n})


def _under(px: list, box: tuple, w: int, h: int) -> dict:
    """The colors under a box: mean, darkest twentieth and lightest twentieth."""
    x0, y0, bw, bh = (int(v) for v in box)
    crop = [px[y * w + x] for y in range(max(0, y0 // 4), min(h, (y0 + bh) // 4)) for x in range(max(0, x0 // 4), min(w, (x0 + bw) // 4))] or px
    crop.sort(key=lambda p: 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2])
    k = max(1, len(crop) // 20)
    return {"mean": _hex(_mean(crop)), "dark": _hex(_mean(crop[:k])), "light": _hex(_mean(crop[-k:])), "pixels": crop}


def _room_below(full, title: tuple, body: tuple) -> int | None:
    """How tall a title may grow, from the top of its box, before it reaches something the template draws.

    Looks down from the bottom of the title box to the top of the text box for
    the first row that is not the title's own background: a rule, the edge of
    a band. Returns that height in stage px, or None when nothing is drawn
    there (a longer title then only pushes the text down). Works on the full
    picture, so a hairline counts. A title box over a photograph or other
    uneven ground gets None: there is no one background to compare with.
    """
    from collections import Counter
    from PIL import Image, ImageChops
    f = full.width / STAGE_W
    x0, x1 = int(title[0] * f), int((title[0] + title[2]) * f)
    y_title, y0, y1 = int(title[1] * f), int((title[1] + title[3]) * f), int(body[1] * f)
    if x1 - x0 < 40 or y1 - y0 < 2:
        return None
    ground = full.crop((x0, y_title, x1, y0)).resize((max(1, (x1 - x0) // 8), max(1, (y0 - y_title) // 8)), Image.BILINEAR)
    counts = Counter((r >> 3, g >> 3, b >> 3) for r, g, b in _pixels(ground)).most_common(1)[0]
    if counts[1] < 0.85 * ground.width * ground.height:
        return None                             # no one background under the title
    base = tuple((c << 3) + 4 for c in counts[0])
    strip = full.crop((x0, y0, x1, y1))
    bands = ImageChops.difference(strip, Image.new("RGB", strip.size, base)).split()
    mask = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2]).point(lambda v: 255 if v > 24 else 0)
    rows = mask.resize((1, strip.height), Image.BOX).tobytes()      # per row: the share of it that is not background
    for i, share in enumerate(rows):
        if share > 5:                           # more than 2% of the row
            return max(0, round((y0 + i) / f - title[1]) - 4)
    return None


def _title_rule(full, dominant: tuple) -> tuple | None:
    """A thin horizontal rule across the upper part of a picture: (left, right, top, bottom) in stage px, or None.

    For a picture that comes with no text boxes. A line that crosses most of
    the slide between 6% and 35% of the way down, with clear space above it,
    is where a template separates the title from the body.
    """
    from PIL import Image, ImageChops
    f = full.width / STAGE_W
    bands = ImageChops.difference(full, Image.new("RGB", full.size, tuple(round(c) for c in dominant))).split()
    mask = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2]).point(lambda v: 255 if v > 24 else 0)
    rows = mask.resize((1, full.height), Image.BOX).tobytes()
    lo, hi = int(0.06 * full.height), int(0.35 * full.height)
    y = lo
    while y < hi:
        if rows[y] > 140:                         # most of this row is not background
            end = y
            while end < full.height and rows[end] > 140:
                end += 1
            thin = (end - y) <= 0.012 * full.height
            above = rows[max(0, y - int(60 * f)):y]
            if thin and above and sum(above) / len(above) < 26:
                cols = mask.crop((0, y, full.width, end)).resize((full.width, 1), Image.BOX).tobytes()
                on = [x for x, v in enumerate(cols) if v > 127]
                if on and (on[-1] - on[0]) >= 0.55 * full.width:
                    return (round(on[0] / f), round((on[-1] + 1) / f), round(y / f), round(end / f))
            y = end + 1
        else:
            y += 1
    return None


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


def measure(im, safe: tuple | None, boxes: dict | None = None, search: bool = True) -> dict:
    """Facts about a background picture: is it flat, where the artwork is, and the colors under the text.

    `boxes` are the template's title and text boxes when it has both (see
    text_boxes); `safe` is the one rectangle they cover when that is all there
    is to go by. With neither, and `search` on, the empty part of the picture
    is looked for: that is for pictures supplied by hand, which come with no
    boxes. A template's layout is never second-guessed that way.
    """
    from collections import Counter
    from PIL import Image, ImageChops
    w, h = STAGE_W // 4, STAGE_H // 4
    full = im.convert("RGB")
    small = full.resize((w, h), Image.BILINEAR)
    px = _pixels(small)
    top = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in px).most_common(1)[0][0]
    dominant = _mean([p for p in px if (p[0] >> 4, p[1] >> 4, p[2] >> 4) == top])
    far = [max(abs(p[i] - dominant[i]) for i in range(3)) > 24 for p in px]
    # the same count on the full picture, where a hairline is still a line and not a faint smear
    bands = ImageChops.difference(full, Image.new("RGB", full.size, tuple(round(c) for c in dominant))).split()
    fine = sum(ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2]).histogram()[25:]) / (full.width * full.height)
    grid = [[0.0] * 3 for _ in range(3)]
    for row in range(3):
        for col in range(3):
            cells = [far[y * w + x] for y in range(row * h // 3, (row + 1) * h // 3) for x in range(col * w // 3, (col + 1) * w // 3)]
            grid[row][col] = sum(cells) / len(cells)
    near = [max(abs(p[i] - dominant[i]) for i in range(3)) for p, is_far in zip(px, far) if not is_far]
    plain = sum(near) / max(1, len(near)) < 4   # one flat color with artwork on it, as opposed to a gradient or a photo

    found, trimmed, zones = None, {}, None
    if boxes and boxes.get("title") and boxes.get("body"):
        zones = {}
        for role in ("title", "body"):
            zones[role], moved = _fit(boxes[role], far, w, h) if plain else (boxes[role], {})
            for side, n in moved.items():
                trimmed[side] = max(trimmed.get(side, 0), n)
        safe = _union([zones["title"], zones["body"]])
    elif safe is not None:
        safe, trimmed = _fit(safe, far, w, h) if plain else (safe, {})
    else:
        rule = _title_rule(full, dominant) if search and plain else None
        if rule:                                  # no boxes, but a rule to go by: title above it, body below
            left, right = max(64, rule[0]), min(STAGE_W - 64, rule[1])
            top = max(40, rule[2] - 162)
            boxes = {"anchor": "end"}
            zones = {"title": (left, top, right - left, rule[2] - 12 - top),
                     "body": (left, rule[3] + 28, right - left, DEFAULT_SAFE[1] + DEFAULT_SAFE[3] - rule[3] - 28)}
            safe, found = _union([zones["title"], zones["body"]]), _union([zones["title"], zones["body"]])
        else:
            if search and plain:
                found = _largest_clear(far, w, h, DEFAULT_SAFE)
            safe = found or DEFAULT_SAFE
    x0, y0, bw, bh = (int(v) for v in safe)
    under = _under(px, zones["body"] if zones else safe, w, h)
    crop = under["pixels"]
    below = y0 + bh                             # how far down the slide stays empty under the text area
    if plain:
        cols = range(max(0, x0 // 4), min(w, (x0 + bw) // 4))
        row = min(h, (y0 + bh) // 4)
        while row < h and cols and sum(far[row * w + x] for x in cols) / len(cols) < 0.01:
            row += 1
        below = row * 4
    out = {
        "safe": tuple(safe),                    # everything the template's text boxes cover
        "found": found is not None and tuple(found) != DEFAULT_SAFE,   # worked out from the picture, not from text boxes
        "trimmed": trimmed,                     # px a side was pulled in from artwork along the slide's edge
        "clear_below": below,
        "overall": _hex(_mean(px)),
        "dominant": _hex(dominant),
        "art": sum(far) / len(far),             # share of the slide that is not the main color
        "fine_art": fine,                       # the same on the full picture: catches hairlines
        "grid": grid,                           # the same, for each ninth of the slide
        "mean": under["mean"],                  # under the text (the body box when the boxes are known)
        "dark": under["dark"],                  # its darkest twentieth
        "light": under["light"],                # its lightest twentieth
        "art_in_text": sum(1 for p in crop if max(abs(p[i] - dominant[i]) for i in range(3)) > 24) / len(crop),
    }
    if zones:
        title = _under(px, zones["title"], w, h)
        out["zones"] = {"title": tuple(zones["title"]), "body": tuple(zones["body"]), "anchor": (boxes or {}).get("anchor", "start"),
                        "from_rule": bool(boxes) and "title" not in boxes,
                        "title_colors": {k: title[k] for k in ("mean", "dark", "light")},
                        "title_room": _room_below(full, zones["title"], zones["body"])}
    return out


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
def _entry(im, safe, dark_text: str, light_text: str, mode: str, boxes: dict | None = None, search: bool = True) -> dict:
    stats = measure(im, safe, boxes, search)
    from _deck import contrast
    if stats["fine_art"] < 0.0003 and stats["art"] < 0.003 and contrast(stats["dark"], stats["light"]) < 1.12:
        return {"flat": stats["dominant"]}       # one color, give or take a speck
    plan = choose_ink(stats, dark_text, light_text)
    known = bool(safe) or bool(boxes) or stats["found"]
    entry = {"image": im, "safe": tuple(stats["safe"]) if known else None, "art": round(max(stats["art"], stats["fine_art"]), 4),
             "clear_below": stats["clear_below"] if (safe or boxes) else None, "trimmed": stats["trimmed"],
             "description": describe(stats, plan), **plan}
    if stats.get("zones"):
        colors = dict(stats["zones"]["title_colors"], overall=stats["overall"])
        over = choose_ink(colors, dark_text, light_text)
        entry["zones"] = {"title": stats["zones"]["title"], "body": stats["zones"]["body"], "anchor": stats["zones"]["anchor"],
                          "from_rule": stats["zones"]["from_rule"],
                          "room": stats["zones"]["title_room"],
                          "title_text": over["text"], "title_bg": over["bg"], "title_ink": over["ink"], "title_calm": over["calm"]}
    return entry


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
                  more: bool = True, layouts: dict | None = None) -> tuple[dict, dict, list[str]]:
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
    layouts = find_layouts(z, master_part) if layouts is None else layouts
    if "content" not in layouts:
        return {}, {}, []                         # the caller reports this: nothing can be measured without it
    others = other_layouts(z, master_part, {entry["part"] for entry in layouts.values()}) if more else []
    if len(others) > MAX_MORE:
        notes.append(f"the template has {len(others)} more layouts with a look of their own; the first {MAX_MORE} were examined")
        others = others[:MAX_MORE]
    work = work or Path(tempfile.mkdtemp(prefix="dynamic-decks-bg-"))
    to_draw = dict(layouts)
    to_draw.update({f"more{i}": entry for i, entry in enumerate(others)})
    pictures, why = render(src, to_draw, work / "render")
    master = ET.fromstring(z.read(master_part))
    state: dict = {"skipped_art": False}

    def examine(key: str, entry: dict, what: str, hero: bool) -> dict | None:
        layout = ET.fromstring(z.read(entry["part"]))
        safe = text_area(layout, master, size)
        boxes = content_boxes(layout, master, size) if key == "content" else None    # None: the one rectangle will have to do
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
                    im = Image.open(io.BytesIO(z.read(target))).convert("RGB")
                    wide = max(STAGE_W, min(MAX_W, im.width))        # as sharp as the file has it, up to twice the stage
                    im = im.resize((wide, wide * STAGE_H // STAGE_W), Image.LANCZOS)
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
        result = _entry(im, safe, dark_text, light_text, mode, boxes, search=False)
        if "flat" not in result:
            if safe is None:
                notes.append(f"{what} has no title or text box with a position in the template, so the built-in margins are used on it")
            for side, n in (result.get("trimmed") or {}).items():
                notes.append(f"on {what} the template's text box runs under artwork along the {side} edge; text starts {n}px further in")
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

    if not pictures:
        notes.append(f"{why}, so backgrounds were read from the file instead of being drawn"
                     + ("; artwork made of shapes was left out" if state["skipped_art"] else "")
                     + ". Install LibreOffice and run this again for an exact copy.")
    elif len(pictures) < len(to_draw):
        notes.append("LibreOffice drew only some of the layouts; the others use a flat color")
    return out, extra, notes


def from_files(files: dict[str, Path], dark_text: str, light_text: str, known: dict | None = None) -> tuple[dict, list[str]]:
    """Backgrounds from pictures the user supplies, one per kind of slide.

    `known` is what a template says about where text goes on each kind of
    slide: kind -> {"safe": area, "boxes": title and text box, "layout": name}.
    With it the picture is only measured for color; the template's boxes
    stand. Without it the picture is all there is: a rule across its top is
    taken as the line under the title, and failing that its empty part is the
    text area.
    """
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
            tall = min(im.height, im.width * 9 // 16)
            wide = tall * 16 // 9
            left, top = (im.width - wide) // 2, (im.height - tall) // 2
            im = im.crop((left, top, left + wide, top + tall))
        if im.width < STAGE_W:
            notes.append(f"the {kind} background is only {im.width}px wide; it will look soft on a {STAGE_W}px stage. Use a picture "
                         f"at least {STAGE_W}px wide, ideally {MAX_W}px")
        wide = max(STAGE_W, min(MAX_W, im.width))    # as sharp as the file has it, up to twice the stage
        im = im.resize((wide, wide * STAGE_H // STAGE_W), Image.LANCZOS)
        told = (known or {}).get(kind) or ((known or {}).get("title") if kind == "closing" else None) or {}
        result = _entry(im, told.get("safe"), dark_text, light_text, "always", told.get("boxes"), search=not told)
        if "flat" not in result:
            result.update(layout=Path(path).name, rendered=False)
            if told:
                notes.append(f"the {kind} picture was supplied by hand; text goes where the template's \"{told.get('layout', kind)}\" layout puts it")
            elif (result.get("zones") or {}).get("from_rule"):
                notes.append(f"a rule runs across the top of the {kind} picture: titles go above it and the body below it")
        out[kind] = result
    return out, notes


PHOTO_BYTES = 700 * 1024                        # an exact copy heavier than this is a photograph, not line artwork
PHOTO_W = 2560


def save(entry: dict, folder: Path, kind: str, saved: dict[str, str]) -> str | None:
    """Write an entry's picture into the theme and return its file name. Identical pictures share a file.

    Line artwork, flat shapes and text are kept exactly, pixel for pixel, at
    full size: any loss shows as blur on a rule or on lettering. Only a
    picture too heavy to keep that way, which means a photograph, is
    compressed, and gently.
    """
    im = entry.get("image")
    if im is None:
        return None
    import io
    from PIL import Image
    key = hashlib.sha1(im.tobytes()).hexdigest()
    if key in saved:
        return saved[key]
    folder.mkdir(parents=True, exist_ok=True)
    name, data = f"{kind}.png", None
    try:
        buf = io.BytesIO()
        im.save(buf, "WEBP", lossless=True, method=4)
        if buf.tell() > PHOTO_BYTES:
            photo = im if im.width <= PHOTO_W else im.resize((PHOTO_W, PHOTO_W * im.height // im.width), Image.LANCZOS)
            buf = io.BytesIO()
            photo.save(buf, "WEBP", quality=92, method=5)
            entry["photo"] = True
        name, data = f"{kind}.webp", buf.getvalue()
    except Exception:  # noqa: BLE001  (Pillow built without WebP)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
    (folder / name).write_bytes(data)
    saved[key] = name
    return name


# --------------------------------------------------------------------------
# Text that is part of the artwork
# --------------------------------------------------------------------------
def artwork_text(roots: list) -> list[tuple[str, str]]:
    """(words, typeface) for text the template draws itself: text boxes on a master or layout that are not placeholders.

    The typeface is "" when a run names none (it then takes the theme's body
    font) and "+mj"/"+mn" when it names the theme's heading or body font.
    """
    found = []
    for root in roots:
        tree = root.find("p:cSld/p:spTree", NS) if root is not None else None
        for sp in (tree.iter(f"{{{NS['p']}}}sp") if tree is not None else []):
            if sp.find("p:nvSpPr/p:nvPr/p:ph", NS) is not None:
                continue
            for run in sp.iter(f"{{{NS['a']}}}r"):
                text = "".join(t.text or "" for t in run.findall("a:t", NS)).strip()
                if not text:
                    continue
                latin = run.find("a:rPr/a:latin", NS)
                face = latin.get("typeface", "") if latin is not None else ""
                found.append((text, "+mj" if face.startswith("+mj") else "+mn" if face.startswith("+mn") else face))
    return found


def installed_fonts() -> set[str] | None:
    """Lower-case family names of the fonts on this machine, or None when that cannot be told."""
    program = shutil.which("fc-list")
    if not program:
        return None
    try:
        out = subprocess.run([program, ":", "family"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {name.strip().lower() for line in out.splitlines() for name in line.split(",") if name.strip()}
