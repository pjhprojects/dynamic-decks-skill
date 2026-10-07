#!/usr/bin/env python3
"""Make the PowerPoint templates the background tests use.

    python tests/fixtures/make_templates.py              all of them
    python tests/fixtures/make_templates.py brand masters   only these

Writes .pptx files next to this script. They are checked in, so this only
needs running when the fixtures should change; name the ones to rewrite, since
a rewritten file differs byte for byte even when its content is the same.
Needs python-pptx and Pillow. Every picture is drawn from a fixed seed.

  template-photo.pptx    content slides: a picture background, calm on the left
                         and a busy "photo" on the right third.
                         title slide: a different, dark picture.
                         section header: a flat color.
  template-shapes.pptx   content slides: a white background with artwork built
                         from shapes on the master (a band, a strip, a logo).
                         title slide: a two-color gradient with circles, and
                         the master's shapes switched off.
  template-busy.pptx     every slide: a busy picture edge to edge, so text
                         needs a panel behind it.
  template-brand.pptx    what a slide master holds besides its background:
                         titles left on content slides and centered on the
                         title slide; the slide number on the left, the footer
                         label centered, the date switched off; square bullets
                         in the brand color; 24pt body text at 90% line spacing;
                         a two-content layout with its own gap; and three extra
                         layouts with a look of their own (Quote, Dark Content,
                         Sidebar) among others that look like the content one.
  template-masters.pptx  two slide masters, Corporate Light and Corporate Dark.
                         One slide uses the light one and three the dark one.
"""
from __future__ import annotations

import io
import random
from pathlib import Path

from lxml import etree
from PIL import Image, ImageDraw, ImageFilter
from pptx import Presentation

HERE = Path(__file__).resolve().parent
W, H = 12192000, 6858000                       # 16:9 in EMU
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NSMAP = f'xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}"'


# ---- pictures ----------------------------------------------------------------
def jpeg(im: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=84)
    buf.seek(0)
    return buf


def png(im: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


def photo_right() -> Image.Image:
    """Off-white, with a busy block of overlapping shapes over the right 36%."""
    rnd = random.Random(7)
    im = Image.new("RGB", (1920, 1080), "#F4F1EA")
    art = Image.new("RGB", (700, 1080), "#0E3B43")
    d = ImageDraw.Draw(art, "RGBA")
    for _ in range(160):
        x, y, r = rnd.randrange(700), rnd.randrange(1080), rnd.randrange(30, 190)
        color = rnd.choice(["#0E7C86", "#F2A541", "#F4F1EA", "#12333A", "#D95D39"])
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        d.ellipse((x - r, y - r, x + r, y + r), fill=rgb + (rnd.randrange(70, 200),))
    im.paste(art, (1220, 0))
    return im


def title_dark() -> Image.Image:
    """Dark navy, calm on the left, with a cluster of rings lower right."""
    rnd = random.Random(11)
    im = Image.new("RGB", (1920, 1080))
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(1080):
        t = y / 1079
        d.line((0, y, 1920, y), fill=(int(11 + 9 * t), int(31 + 30 * t), int(58 + 40 * t)))
    for _ in range(46):
        x, y, r = rnd.randrange(1150, 1920), rnd.randrange(380, 1080), rnd.randrange(40, 260)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(242, 165, 65, rnd.randrange(90, 230)), width=rnd.randrange(3, 9))
    return im.filter(ImageFilter.GaussianBlur(0.6))


def busy_full() -> Image.Image:
    """High-contrast tiles edge to edge: nothing is calm enough to read over."""
    rnd = random.Random(3)
    im = Image.new("RGB", (1920, 1080))
    d = ImageDraw.Draw(im)
    colors = ["#101820", "#F2AA4C", "#FFFFFF", "#2D5D7B", "#D7263D", "#1B998B", "#F4F1EA"]
    for gy in range(0, 1080, 90):
        for gx in range(0, 1920, 96):
            d.rectangle((gx, gy, gx + 96, gy + 90), fill=rnd.choice(colors))
            if rnd.random() < 0.5:
                d.polygon(((gx, gy), (gx + 96, gy), (gx, gy + 90)), fill=rnd.choice(colors))
    return im


def logo() -> Image.Image:
    im = Image.new("RGBA", (360, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, 119, 119), 26, fill="#C8102E")
    d.rectangle((150, 30, 350, 52), fill="#1B1B1B")
    d.rectangle((150, 68, 300, 90), fill="#1B1B1B")
    return im


# ---- template XML --------------------------------------------------------------
def fragment(xml: str):
    return etree.fromstring(f"<root {NSMAP}>{xml}</root>")[0]


def set_bg(obj, inner: str) -> None:
    """Replace the background of a master or layout with <p:bgPr> content."""
    csld = obj._element.find(f"{{{P}}}cSld")
    for old in csld.findall(f"{{{P}}}bg"):
        csld.remove(old)
    csld.insert(0, fragment(f"<p:bg><p:bgPr>{inner}<a:effectLst/></p:bgPr></p:bg>"))


def bg_picture(obj, image: io.BytesIO) -> None:
    _, rid = obj.part.get_or_add_image_part(image)
    set_bg(obj, f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{rid}"/><a:srcRect/><a:stretch><a:fillRect/></a:stretch></a:blipFill>')


def bg_solid(obj, color: str) -> None:
    set_bg(obj, f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>')


def bg_gradient(obj, first: str, last: str, angle: int) -> None:
    set_bg(obj, '<a:gradFill rotWithShape="1"><a:gsLst>'
                f'<a:gs pos="0"><a:srgbClr val="{first}"/></a:gs><a:gs pos="100000"><a:srgbClr val="{last}"/></a:gs>'
                f'</a:gsLst><a:lin ang="{angle * 60000}" scaled="0"/></a:gradFill>')


def tree(obj):
    return obj._element.find(f"{{{P}}}cSld/{{{P}}}spTree")


def next_id(obj) -> int:
    ids = [int(e.get("id")) for e in obj._element.iter(f"{{{P}}}cNvPr") if e.get("id", "").isdigit()]
    return max(ids + [1]) + 1


def add_shape(obj, kind: str, x: float, y: float, w: float, h: float, color: str, alpha: int = 100) -> None:
    """A decorative shape, behind the placeholders. Positions are fractions of the slide."""
    fill = f'<a:srgbClr val="{color}">' + (f'<a:alpha val="{alpha * 1000}"/>' if alpha < 100 else "") + "</a:srgbClr>"
    sp = fragment(
        f'<p:sp><p:nvSpPr><p:cNvPr id="{next_id(obj)}" name="Art"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{int(x * W)}" y="{int(y * H)}"/><a:ext cx="{int(w * W)}" cy="{int(h * H)}"/></a:xfrm>'
        f'<a:prstGeom prst="{kind}"><a:avLst/></a:prstGeom><a:solidFill>{fill}</a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>')
    tree(obj).insert(2, sp)                    # after nvGrpSpPr and grpSpPr: behind everything else


def add_picture(obj, image: io.BytesIO, x: float, y: float, w: float, h: float) -> None:
    _, rid = obj.part.get_or_add_image_part(image)
    pic = fragment(
        f'<p:pic><p:nvPicPr><p:cNvPr id="{next_id(obj)}" name="Logo"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{int(x * W)}" y="{int(y * H)}"/><a:ext cx="{int(w * W)}" cy="{int(h * H)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
    tree(obj).append(pic)


def place(obj, kinds: tuple, x: float, y: float, w: float, h: float) -> None:
    """Move the placeholder of one of these types (None means the body/content one)."""
    for sp in tree(obj).findall(f"{{{P}}}sp"):
        ph = sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if ph is None or ph.get("type") not in kinds:
            continue
        sppr = sp.find(f"{{{P}}}spPr")
        for old in sppr.findall(f"{{{A}}}xfrm"):
            sppr.remove(old)
        sppr.insert(0, fragment(f'<a:xfrm><a:off x="{int(x * W)}" y="{int(y * H)}"/><a:ext cx="{int(w * W)}" cy="{int(h * H)}"/></a:xfrm>'))
        return
    raise ValueError(f"no placeholder of type {kinds}")


def blank() -> tuple:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    layouts = {layout._element.get("type"): layout for layout in prs.slide_layouts}
    return prs, prs.slide_master, layouts


def content_boxes(master, layouts, x: float, w: float) -> None:
    for obj in (master, layouts["obj"]):
        place(obj, ("title",), x, 0.09, w, 0.14)
        place(obj, ("body", None), x, 0.27, w, 0.57)


def title_boxes(layout, x: float, y: float, w: float) -> None:
    place(layout, ("ctrTitle",), x, y, w, 0.22)
    place(layout, ("subTitle",), x, y + 0.24, w, 0.13)


def named(prs) -> dict:
    return {layout.name: layout for layout in prs.slide_layouts}


def paragraph_style(master, style: str, level: int):
    """<a:lvlNpPr> of the master's title or body style."""
    return master._element.find(f"{{{P}}}txStyles/{{{P}}}{style}/{{{A}}}lvl{level}pPr")


def set_bullet(ppr, char: str | None, color: str | None = None) -> None:
    """Replace a paragraph level's bullet. A:pPr children have a fixed order: color, font, then the bullet itself."""
    for tag in ("buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts", "buFontTx", "buFont", "buNone", "buAutoNum", "buChar", "buBlip"):
        for old in ppr.findall(f"{{{A}}}{tag}"):
            ppr.remove(old)
    at = list(ppr).index(ppr.find(f"{{{A}}}defRPr")) if ppr.find(f"{{{A}}}defRPr") is not None else len(ppr)
    parts = []
    if color:
        parts.append(f'<a:buClr><a:srgbClr val="{color}"/></a:buClr>')
    parts.append('<a:buFont typeface="Arial"/>' if char else "")
    parts.append(f'<a:buChar char="{char}"/>' if char else "<a:buNone/>")
    for xml in parts:
        if xml:
            ppr.insert(at, fragment(xml))
            at += 1


def placeholder(obj, kind: str):
    for sp in tree(obj).findall(f"{{{P}}}sp"):
        ph = sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if ph is not None and ph.get("type") == kind:
            return sp
    return None


def footer_box(master, kind: str, x: float, w: float, align: str, size: int | None = None, color: str | None = None) -> None:
    """Move one of the master's footer boxes (dt, ftr, sldNum) and restyle its text."""
    place(master, (kind,), x, 0.925, w, 0.05)
    lst = placeholder(master, kind).find(f"{{{P}}}txBody/{{{A}}}lstStyle")
    for old in list(lst):
        lst.remove(old)
    fill = f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>' if color else ""
    sz = f' sz="{size}"' if size else ""
    lst.append(fragment(f'<a:lvl1pPr algn="{align}"><a:defRPr{sz}>{fill}</a:defRPr></a:lvl1pPr>'))


def brand() -> None:
    prs, master, layouts = blank()
    by_name = named(prs)
    bg_solid(master, "FFFFFF")
    add_picture(master, png(logo()), 0.86, 0.05, 0.1, 0.059)
    content_boxes(master, layouts, 0.07, 0.8)

    # titles: left on the master, centered on the title slide
    paragraph_style(master, "titleStyle", 1).set("algn", "l")
    title = layouts["title"]
    title_boxes(title, 0.15, 0.3, 0.7)
    for kind in ("ctrTitle", "subTitle"):
        lst = placeholder(title, kind).find(f"{{{P}}}txBody/{{{A}}}lstStyle")
        first = lst.find(f"{{{A}}}lvl1pPr")
        if first is None:
            first = fragment("<a:lvl1pPr/>")
            lst.insert(0, first)
        first.set("algn", "ctr")

    # body text: 24pt at 90% line spacing, square bullets in the brand color, dashes below
    one, two = paragraph_style(master, "bodyStyle", 1), paragraph_style(master, "bodyStyle", 2)
    one.find(f"{{{A}}}defRPr").set("sz", "2400")
    one.insert(0, fragment('<a:lnSpc><a:spcPct val="90000"/></a:lnSpc>'))
    one.set("marL", "285750")
    one.set("indent", "-285750")
    set_bullet(one, "\u25AA", "C8102E")
    set_bullet(two, "\u2013")

    # footer: number on the left, label in the middle, no date
    footer_box(master, "sldNum", 0.07, 0.08, "l", 1000, "6B6B6B")
    footer_box(master, "ftr", 0.3, 0.4, "ctr", 1000, "6B6B6B")
    footer_box(master, "dt", 0.8, 0.13, "r", 1000, "6B6B6B")
    master._element.insert(list(master._element).index(master._element.find(f"{{{P}}}txStyles")), fragment('<p:hf dt="0"/>'))

    # two content: columns with a 4% gap
    two_content = layouts["twoObj"]
    bodies = [sp for sp in tree(two_content).findall(f"{{{P}}}sp")
              if sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph").get("type") is None]
    for sp, x in zip(bodies, (0.07, 0.49)):
        sppr = sp.find(f"{{{P}}}spPr")
        for old in sppr.findall(f"{{{A}}}xfrm"):
            sppr.remove(old)
        sppr.insert(0, fragment(f'<a:xfrm><a:off x="{int(x * W)}" y="{int(0.27 * H)}"/><a:ext cx="{int(0.38 * W)}" cy="{int(0.57 * H)}"/></a:xfrm>'))

    # three layouts with a look of their own; the rest look like the content layout
    quote = by_name["Blank"]
    quote._element.find(f"{{{P}}}cSld").set("name", "Quote")
    quote._element.set("showMasterSp", "0")
    bg_gradient(quote, "0B2545", "13626B", 30)
    dark = by_name["Title Only"]
    dark._element.find(f"{{{P}}}cSld").set("name", "Dark Content")
    bg_solid(dark, "1B1B1B")
    side = by_name["Content with Caption"]
    side._element.find(f"{{{P}}}cSld").set("name", "Sidebar")
    add_shape(side, "rect", 0.72, 0, 0.28, 1, "C8102E")
    place(side, ("title",), 0.07, 0.09, 0.58, 0.14)
    place(side, (None,), 0.07, 0.27, 0.58, 0.57)
    prs.save(HERE / "template-brand.pptx")


def clone_master(path: Path, name: str, accent: str, dark: str, light: str) -> None:
    """Give a saved template a second slide master: a copy of the first with its own theme and a dark background."""
    import re
    import shutil
    import zipfile
    src = path.with_suffix(".tmp")
    shutil.move(path, src)
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        names = z.namelist()
        count = len([n for n in names if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)])
        types = z.read("[Content_Types].xml").decode()
        added = ""
        for n in names:
            data = z.read(n)
            if n == "[Content_Types].xml":
                continue
            if n == "ppt/presentation.xml":
                data = data.decode().replace("</p:sldMasterIdLst>", '<p:sldMasterId id="2147483700" r:id="rId900"/></p:sldMasterIdLst>').encode()
            elif n == "ppt/_rels/presentation.xml.rels":
                data = data.decode().replace("</Relationships>", '<Relationship Id="rId900" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster2.xml"/></Relationships>').encode()
            out.writestr(n, data)
            text = None
            m = re.fullmatch(r"ppt/slideLayouts/(_rels/)?slideLayout(\d+)\.xml(\.rels)?", n)
            if m:
                new = f"ppt/slideLayouts/{m.group(1) or ''}slideLayout{int(m.group(2)) + count}.xml{m.group(3) or ''}"
                text = data.decode().replace("slideMaster1.xml", "slideMaster2.xml")
            elif n == "ppt/slideMasters/slideMaster1.xml":
                new, text = "ppt/slideMasters/slideMaster2.xml", data.decode()
                text = re.sub(r'<p:sldLayoutId id="(\d+)"', lambda k: f'<p:sldLayoutId id="{int(k.group(1)) + 100}"', text)
                text = text.replace('bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2"', 'bg1="dk1" tx1="lt1" bg2="dk2" tx2="lt2"')
                text = re.sub(r"<p:bg>.*?</p:bg>", '<p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>', text, flags=re.S)
            elif n == "ppt/slideMasters/_rels/slideMaster1.xml.rels":
                new, text = "ppt/slideMasters/_rels/slideMaster2.xml.rels", data.decode().replace("theme1.xml", "theme2.xml")
                text = re.sub(r"slideLayout(\d+)\.xml", lambda k: f"slideLayout{int(k.group(1)) + count}.xml", text)
            elif n == "ppt/theme/theme1.xml":
                new, text = "ppt/theme/theme2.xml", data.decode()
                text = re.sub(r'<a:theme([^>]*) name="[^"]*"', rf'<a:theme\1 name="{name}"', text, count=1)
                text = re.sub(r"<a:dk1>.*?</a:dk1>", f'<a:dk1><a:srgbClr val="{dark}"/></a:dk1>', text, flags=re.S)
                text = re.sub(r"<a:lt1>.*?</a:lt1>", f'<a:lt1><a:srgbClr val="{light}"/></a:lt1>', text, flags=re.S)
                text = re.sub(r"<a:accent1>.*?</a:accent1>", f'<a:accent1><a:srgbClr val="{accent}"/></a:accent1>', text, flags=re.S)
            if text is not None:
                out.writestr(new, text)
                if "_rels" not in new:
                    kind = re.search(rf'<Override PartName="/{re.escape(n)}" ContentType="([^"]+)"', types).group(1)
                    added += f'<Override PartName="/{new}" ContentType="{kind}"/>'
        out.writestr("[Content_Types].xml", types.replace("</Types>", added + "</Types>"))
    src.unlink()


def masters() -> None:
    prs, master, layouts = blank()
    bg_solid(master, "FFFFFF")
    content_boxes(master, layouts, 0.07, 0.8)
    theme_part = master.part.part_related_by("http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme")
    xml = theme_part.blob.decode().replace('name="Office Theme"', 'name="Corporate Light"', 1)
    xml = xml.replace('<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>', '<a:accent1><a:srgbClr val="0F7B4F"/></a:accent1>')
    theme_part._blob = xml.encode()
    path = HERE / "template-masters.pptx"
    prs.save(path)
    clone_master(path, "Corporate Dark", accent="F2A541", dark="101820", light="F4F1EA")
    prs = Presentation(path)
    light, dark = prs.slide_masters
    for layout, text in ((light.slide_layouts[1], "On the light master"), (dark.slide_layouts[0], "On the dark master"),
                         (dark.slide_layouts[1], "Also dark"), (dark.slide_layouts[1], "And dark again")):
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = text
    prs.save(path)


def main() -> None:
    import sys
    wanted = set(sys.argv[1:])
    made = {"photo": photo, "shapes": shapes, "busy": busy, "brand": brand, "masters": masters}
    unknown = wanted - set(made)
    if unknown:
        sys.exit(f"no such template: {', '.join(sorted(unknown))} (there are: {', '.join(made)})")
    for name, make in made.items():
        if not wanted or name in wanted:
            make()
            f = HERE / f"template-{name}.pptx"
            print(f"  {f.name}  {f.stat().st_size / 1024:.0f} KB")


def photo() -> None:
    # picture backgrounds
    prs, master, layouts = blank()
    bg_picture(master, jpeg(photo_right()))
    content_boxes(master, layouts, 0.06, 0.52)
    bg_picture(layouts["title"], jpeg(title_dark()))
    title_boxes(layouts["title"], 0.07, 0.28, 0.5)
    bg_solid(layouts["secHead"], "0E7C86")
    prs.save(HERE / "template-photo.pptx")


def shapes() -> None:
    # artwork made of shapes
    prs, master, layouts = blank()
    bg_solid(master, "FFFFFF")
    add_shape(master, "rect", 0, 0, 0.085, 1, "C8102E")
    add_shape(master, "rect", 0.085, 0.965, 0.915, 0.035, "1B1B1B")
    add_picture(master, png(logo()), 0.86, 0.05, 0.1, 0.059)
    content_boxes(master, layouts, 0.13, 0.7)
    title = layouts["title"]
    title._element.set("showMasterSp", "0")
    bg_gradient(title, "C8102E", "5A0613", 45)
    add_shape(title, "ellipse", 0.62, 0.1, 0.5, 0.89, "FFFFFF", alpha=14)
    add_shape(title, "ellipse", 0.72, 0.35, 0.34, 0.6, "FFFFFF", alpha=18)
    title_boxes(title, 0.08, 0.32, 0.5)
    prs.save(HERE / "template-shapes.pptx")


def busy() -> None:
    # busy everywhere
    prs, master, layouts = blank()
    bg_picture(master, jpeg(busy_full()))
    content_boxes(master, layouts, 0.08, 0.84)
    title_boxes(layouts["title"], 0.1, 0.3, 0.8)
    prs.save(HERE / "template-busy.pptx")


if __name__ == "__main__":
    main()
