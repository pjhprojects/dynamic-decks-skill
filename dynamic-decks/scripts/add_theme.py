#!/usr/bin/env python3
"""Create, check and list DynamicDecks themes.

    python scripts/add_theme.py from-pptx Template.potx --name acme --preview
    python scripts/add_theme.py from-pptx Template.pptx --name acme --fonts ./brand-fonts --logo logo.svg
    python scripts/add_theme.py new --name acme --bg "#FFFFFF" --text "#1B1B1B" --accent "#E4002B" \\
        --accent2 "#00539B" --font-display "Montserrat" --font-body "Open Sans" --fonts ./fonts
    python scripts/add_theme.py from-spec acme.json
    python scripts/add_theme.py check acme
    python scripts/add_theme.py list
    python scripts/add_theme.py tokens            (every token a theme can set, with the default values)

from-pptx reads a PowerPoint template: theme colors, heading and body fonts,
the title position and size on the slide master, and a logo if the master has
one. A background that is more than a flat color (a photo, a gradient, artwork
made of shapes) is kept as a picture: LibreOffice draws each kind of slide
empty, and that picture becomes the background, with the margins, text color
and any panel behind the text worked out from it once. `new` builds a theme
from a handful of brand values (use it for a brand guide or a description),
and takes background pictures with --background. Both expand those few values
into the full token set, derive the second variant (dark or light) when the
background is a flat color, and report what they could not take from the
source, so you know what to review.

Themes are written to your library folder (~/.dynamic-decks/themes/<name>, or
$DYNAMIC_DECKS_HOME), apart from the built-in theme, so updating the skill never
overwrites them. --into writes somewhere else.

A theme is plain CSS. After generating one, open theme.css and adjust any
value by hand; `check` tells you if something is missing or hard to read.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _backgrounds  # noqa: E402
import _deck  # noqa: E402
import _master  # noqa: E402
from _deck import contrast, ensure_contrast, luminance, mix, oklab, shift_lightness  # noqa: E402

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
DEFAULT_DIR = _deck.SKILL_DIR / "themes" / "default"
BUNDLED = {"bricolage grotesque", "hanken grotesk", "jetbrains mono"}
STATUS = {
    "light": {"positive": "#0B7D43", "negative": "#C62F2F", "warning": "#9A6500"},
    "dark": {"positive": "#4CC98A", "negative": "#FF7A7A", "warning": "#F0B43C"},
}
SHAPES = {
    "sharp": {"--radius-sm": "0px", "--radius-md": "0px", "--radius-lg": "0px"},
    "soft": {"--radius-sm": "6px", "--radius-md": "14px", "--radius-lg": "24px"},
    "round": {"--radius-sm": "12px", "--radius-md": "28px", "--radius-lg": "44px"},
}


def hexc(v: str) -> str:
    v = v.strip()
    if not v.startswith("#"):
        v = "#" + v
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
            v = "#" + "".join(c * 2 for c in v[1:])
        else:
            raise ValueError(f"'{v}' is not a hex color like #1A2B3C")
    return v.upper()


# --------------------------------------------------------------------------
# Reading a PowerPoint template
# --------------------------------------------------------------------------
def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    folder, name = part.rsplit("/", 1)
    rels_path = f"{folder}/_rels/{name}.rels"
    out = {}
    if rels_path not in z.namelist():
        return out
    for rel in ET.fromstring(z.read(rels_path)).findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        if not target.startswith("/"):
            parts = (folder + "/" + target).split("/")
            stack: list[str] = []
            for seg in parts:
                if seg == "..":
                    stack.pop()
                elif seg != ".":
                    stack.append(seg)
            target = "/".join(stack)
        else:
            target = target.lstrip("/")
        out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], target)
    return out


def read_pptx(path: Path, extract_to: Path | None = None, backgrounds: str = "auto",
              master_choice: str | None = None, more_backgrounds: bool = True) -> tuple[dict, list[str]]:
    """Pull brand values out of a .pptx or .potx. Returns (spec, notes)."""
    notes: list[str] = []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        _deck.die(f"{path} is not a PowerPoint file (.pptx or .potx)")
    names = set(z.namelist())
    if "ppt/presentation.xml" not in names:
        _deck.die(f"{path} has no presentation inside; is it a .pptx or .potx?")
    pres = ET.fromstring(z.read("ppt/presentation.xml"))
    sz = pres.find("p:sldSz", NS)
    cx, cy = (int(sz.get("cx")), int(sz.get("cy"))) if sz is not None else (12192000, 6858000)
    if abs(cx / cy - 16 / 9) > 0.02:
        notes.append(f"the template is {cx / cy:.2f}:1, not 16:9. Decks are always 16:9, so positions were scaled to fit.")
    px = 1920 / cx                       # EMU -> stage px
    px_per_pt = 1920 / (cx / 12700)

    # A file may hold several slide masters (a light and a dark one, sub-brands, leftovers from pasted slides)
    masters = _master.list_masters(z)
    chosen, why = _master.pick_master(masters, master_choice)
    if chosen is None:
        if not masters:
            _deck.die("could not find a slide master in the template")
        _deck.die(f"{why}. It has: {_master.describe_masters(masters)}")
    master_part = chosen["part"]
    if len(masters) > 1:
        notes.append(f"the file has {len(masters)} slide masters: {_master.describe_masters(masters)}. The theme was made from "
                     f"\"{chosen['name']}\" because {why}. Pass --master with a number or a name to use another.")
    master = ET.fromstring(z.read(master_part))
    mrels = _rels(z, master_part)
    theme_part = next((t for typ, t in mrels.values() if typ == "theme"), None)
    if not theme_part or theme_part not in names:
        _deck.die("could not find the theme in the template")
    theme = ET.fromstring(z.read(theme_part))

    scheme: dict[str, str] = {}
    cs = theme.find("a:themeElements/a:clrScheme", NS)
    if cs is not None:
        for child in cs:
            key = child.tag.split("}")[1]
            srgb, sysc = child.find("a:srgbClr", NS), child.find("a:sysClr", NS)
            if srgb is not None:
                scheme[key] = "#" + srgb.get("val", "000000").upper()
            elif sysc is not None:
                scheme[key] = "#" + (sysc.get("lastClr") or ("FFFFFF" if "window" == sysc.get("val") else "000000")).upper()
    cmap = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    cm = master.find("p:clrMap", NS)
    if cm is not None:
        cmap.update({k: v for k, v in cm.attrib.items()})

    def resolve(node) -> str | None:
        if node is None:
            return None
        srgb = node.find("a:srgbClr", NS)
        if srgb is not None:
            return "#" + srgb.get("val", "").upper()
        sc = node.find("a:schemeClr", NS)
        if sc is not None:
            key = sc.get("val", "")
            key = cmap.get(key, key)
            if len(list(sc)):
                notes.append(f"a color in the template is a tint or shade of '{key}'; the plain color was used")
            return scheme.get(key)
        return None

    bg = None
    bg_el = master.find("p:cSld/p:bg", NS)
    not_flat = False
    if bg_el is not None:
        bg = resolve(bg_el.find("p:bgPr/a:solidFill", NS)) or resolve(bg_el.find("p:bgRef", NS))
        not_flat = bg is None and bg_el.find("p:bgPr", NS) is not None and bg_el.find("p:bgPr/a:solidFill", NS) is None
    bg = bg or scheme.get(cmap.get("bg1", "lt1"), "#FFFFFF")
    text = scheme.get(cmap.get("tx1", "dk1"), "#000000")

    # Backgrounds: each kind of slide drawn empty, then measured (see _backgrounds.py)
    light = scheme.get(cmap.get("bg1", "lt1"), "#FFFFFF")
    kinds, more_kinds, bg_notes = _backgrounds.from_template(
        path, z, master_part, (cx, cy), resolve,
        dark_text=text if luminance(text) < 0.2 else "#111111",
        light_text=light if luminance(light) > 0.8 else "#FFFFFF",
        mode=backgrounds, work=(extract_to / "backgrounds") if extract_to else None, more=more_backgrounds)
    notes += bg_notes
    content = kinds.get("content", {})
    picture = "flat" not in content and bool(content)
    if picture:
        bg, text = content["bg"], content["text"]
    elif content.get("flat"):
        bg = content["flat"]
    elif not_flat:
        notes.append("the master background is a picture or gradient; a flat background color was used instead")
    if contrast(bg, text) < 4.5:
        notes.append(f"the template's text {text} on its background {bg} has low contrast; check the result")
    drawn_text = []
    if any(entry.get("rendered") for entry in list(kinds.values()) + list(more_kinds.values())):
        used = [ET.fromstring(z.read(entry["part"])) for entry in _backgrounds.find_layouts(z, master_part).values()]
        drawn_text = _backgrounds.artwork_text([master] + used)

    fonts = {}
    fs = theme.find("a:themeElements/a:fontScheme", NS)
    if fs is not None:
        for role, tag in (("display", "a:majorFont"), ("body", "a:minorFont")):
            latin = fs.find(f"{tag}/a:latin", NS)
            if latin is not None and latin.get("typeface"):
                fonts[role] = latin.get("typeface")

    if drawn_text:                               # words in the pictures were set by LibreOffice, with the fonts it had
        have = _backgrounds.installed_fonts()
        named = {"+mj": fonts.get("display", ""), "+mn": fonts.get("body", ""), "": fonts.get("body", "")}
        faces = sorted({(named.get(face, face) or "").strip() for _, face in drawn_text} - {""})
        absent = [f for f in faces if have is not None and f.lower() not in have]
        sample = "; ".join(dict.fromkeys(f'"{words[:40]}"' for words, _ in drawn_text[:3]))
        if absent:
            notes.append(f"the backgrounds include text that is part of the template ({sample}). It is set in {', '.join(absent)}, "
                         "which is not installed on this machine, so LibreOffice drew it in a stand-in font. Install the font here and "
                         "make the theme again, or compare preview/backgrounds.png with the template")
        else:
            notes.append(f"the backgrounds include text that is part of the template ({sample}); it is now part of the picture, "
                         "as sharp as the rest, and cannot be edited in a deck")

    frame: dict = {}
    title_color = None
    ts = master.find("p:txStyles/p:titleStyle/a:lvl1pPr", NS)
    if ts is not None:
        rpr = ts.find("a:defRPr", NS)
        if rpr is not None:
            if rpr.get("sz"):
                frame["title_size"] = round(int(rpr.get("sz")) / 100 * px_per_pt)
            if rpr.get("b") in ("1", "true"):
                frame["title_weight"] = 700
            title_color = resolve(rpr.find("a:solidFill", NS))
            latin = rpr.find("a:latin", NS)
            if latin is not None and latin.get("typeface", "").startswith("+mn"):
                fonts["display"] = fonts.get("body", fonts.get("display"))
    tree = master.find("p:cSld/p:spTree", NS)
    if tree is not None:
        for sp in tree.findall("p:sp", NS):
            ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
            off = sp.find("p:spPr/a:xfrm/a:off", NS)
            if ph is None or off is None:
                continue
            if ph.get("type") in ("title", "ctrTitle"):
                frame["x"] = round(int(off.get("x")) * px)
                frame["top"] = round(int(off.get("y")) * px * (1080 / (cy * px)))
    # Logo candidates: small pictures on the master
    logo = None
    if picture and content.get("rendered"):
        notes.append("anything on the slide master, such as a logo, is part of the background picture, so no separate logo was added")
    elif tree is not None and extract_to is not None:
        cands = []
        for pic in tree.findall(".//p:pic", NS):
            blip = pic.find("p:blipFill/a:blip", NS)
            ext = pic.find("p:spPr/a:xfrm/a:ext", NS)
            if blip is None:
                continue
            rid = blip.get(f"{{{NS['r']}}}embed")
            target = mrels.get(rid, ("", ""))[1]
            if not target or target not in names:
                continue
            width = int(ext.get("cx")) / cx if ext is not None else 1
            cands.append((width, target))
        cands = [c for c in cands if c[0] <= 0.4 and Path(c[1]).suffix.lower() in (".png", ".svg", ".jpg", ".jpeg", ".webp")]
        if len(cands) == 1:
            target = cands[0][1]
            extract_to.mkdir(parents=True, exist_ok=True)
            dest = extract_to / ("logo" + Path(target).suffix.lower())
            dest.write_bytes(z.read(target))
            logo = dest
            notes.append(f"took the picture on the slide master as the logo ({Path(target).name}); pass --logo to use a different file")
        elif len(cands) > 1:
            notes.append(f"the slide master has {len(cands)} small pictures; none was taken as the logo. Pass --logo with the right file.")
        else:
            notes.append("no logo found on the slide master; pass --logo to add one")

    accents = [scheme[k] for k in ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6") if k in scheme]
    spec = {
        "colors": {
            "bg": bg, "text": text,
            "accent": accents[0] if accents else "#2B3BF0",
            "accent2": accents[1] if len(accents) > 1 else None,
            "chart": accents,
        },
        "fonts": fonts,
        "frame": frame,
        "source": str(path.name),
    }
    if title_color and title_color.upper() != text.upper() and contrast(title_color, bg) >= 4.5:
        spec["colors"]["title"] = title_color
    if logo:
        spec["logo"] = {"base": str(logo)}
    if len(masters) > 1:
        spec["master"] = chosen["name"]

    # What the master and its layouts say about each kind of slide (see _master.py)
    layout_parts = _backgrounds.find_layouts(z, master_part)
    layout_xml = {kind: ET.fromstring(z.read(entry["part"])) for kind, entry in layout_parts.items()}
    per_kind: dict[str, dict] = {}
    for kind in ("content", "title", "section", "closing"):
        if kind != "content" and kind not in layout_xml:
            continue
        per_kind[kind] = {"title_align": _master.title_align(master, layout_xml.get(kind))}
        if kind in ("title", "section"):
            place = _master.hero_place(master, layout_xml[kind], (cx, cy))
            if place:
                per_kind[kind]["place"] = place
    spec["layouts"] = per_kind

    # Footer label and slide number: where they sit, and whether the template shows them at all
    on_master = [ET.fromstring(z.read(part)) for part in _master.slides_on(z, master_part)]
    gap = _master.column_gap(z, master_part, (cx, cy))
    if gap is not None:
        frame["column_gap"] = gap
    spec["body"] = _master.body_text(master, layout_xml.get("content"))
    spec["bullets"] = _master.bullets(master, layout_xml.get("content"), (cx, cy), resolve)
    spec["footer"] = _master.footer(master, layout_xml.get("content"), (cx, cy), px_per_pt, resolve, on_master)
    aligns = {kind: v["title_align"] for kind, v in per_kind.items()}
    if set(aligns.values()) != {"start"}:
        words = {"start": "left", "center": "centered", "end": "right"}
        notes.append("title alignment follows the template: " + ", ".join(f"{kind} slides {words[a]}" for kind, a in aligns.items()))
    if more_kinds:
        spec["more_backgrounds"] = more_kinds
    if kinds:
        spec["backgrounds"] = kinds
        hero = kinds.get("title", {})
        if hero.get("flat") and contrast(hero["flat"], bg) > 1.3:      # a title slide in a flat brand color
            spec["colors"]["inverse_bg"] = hero["flat"]
    notes.append("a PowerPoint template has no motion, spacing scale or corner style; the built-in theme's values were used for those")
    return spec, notes


# --------------------------------------------------------------------------
# Expanding a few brand values into the full token set
# --------------------------------------------------------------------------
def color_tokens(bg: str, text: str, accent: str, accent2: str | None, chart: list[str], mode: str,
                 notes: list[str], inverse_bg: str | None = None, title: str | None = None) -> dict[str, str]:
    t: dict[str, str] = {}
    t["--color-bg"] = bg
    t["--color-surface"] = mix(bg, text, 0.06)
    t["--color-surface-2"] = mix(bg, text, 0.11)
    t["--color-text"] = text
    t["--color-text-muted"] = ensure_contrast(mix(text, bg, 0.30), bg, 4.5)
    t["--color-text-subtle"] = ensure_contrast(mix(text, bg, 0.44), bg, 4.5)
    t["--color-border"] = mix(bg, text, 0.17)

    acc = ensure_contrast(accent, bg, 3.0)
    if acc.upper() != accent.upper():
        notes.append(f"{mode}: accent {accent} was too close to the background; adjusted to {acc}")
    t["--color-accent"] = acc
    t["--color-accent-contrast"] = "#FFFFFF" if contrast("#FFFFFF", acc) >= contrast("#111111", acc) else "#111111"
    t["--color-accent-soft"] = mix(bg, acc, 0.15)
    a2 = accent2 or acc
    a2 = ensure_contrast(a2, bg, 3.0)
    t["--color-accent-2"] = a2
    t["--color-accent-2-soft"] = mix(bg, a2, 0.15)
    for k, v in STATUS[mode].items():
        t[f"--color-{k}"] = ensure_contrast(v, bg, 4.5)

    inv = inverse_bg or accent
    if contrast("#FFFFFF", inv) >= 2.2:
        inv = ensure_contrast(inv, "#FFFFFF", 5.2, prefer="darker")     # room for the muted text to clear 4.5 too
        inv_text = "#FFFFFF"
    else:
        inv_text = text if luminance(text) < 0.2 else "#111111"
        inv = ensure_contrast(inv, inv_text, 4.5, prefer="lighter")
    t.update(inverse_tokens(inv, inv_text, accent2))
    darkest = bg if luminance(bg) < luminance(text) else text
    t["--color-letterbox"] = mix(darkest, "#000000", 0.6)

    default_chart = [v for k, v in _default_tokens(mode).items() if re.fullmatch(r"--chart-\d", k)]
    palette: list[str] = []
    for c in chart[:8]:
        fixed = ensure_contrast(c, bg, 2.2)
        if fixed.upper() != c.upper():
            notes.append(f"{mode}: chart color {c} nearly disappears on the background; adjusted to {fixed}")
        if all(_deck.delta_e(fixed, p) >= 8 for p in palette):
            palette.append(fixed)
    for c in default_chart:
        if len(palette) >= 8:
            break
        if all(_deck.delta_e(c, p) >= 15 for p in palette):
            palette.append(c)
    for c in default_chart:
        if len(palette) >= 8:
            break
        if c not in palette:
            palette.append(c)
    for i, c in enumerate(palette[:8], 1):
        t[f"--chart-{i}"] = c
    t["--chart-neutral"] = mix(bg, text, 0.24)
    t["--chart-grid"] = mix(bg, text, 0.10)
    t["--chart-axis"] = mix(bg, text, 0.30)
    t["--chart-label"] = t["--color-text-muted"]
    if mode == "dark":
        t["--shadow-sm"] = "0 2px 6px rgba(0, 0, 0, 0.3)"
        t["--shadow-md"] = "0 14px 40px rgba(0, 0, 0, 0.45)"
    else:
        t["--shadow-sm"] = "0 2px 6px rgba(0, 0, 0, 0.08)"
        t["--shadow-md"] = "0 14px 40px rgba(0, 0, 0, 0.14)"
    if title:
        t["--title-color"] = title if contrast(title, bg) >= 4.5 else "var(--color-text)"
    for n in _deck.palette_report(palette[:8], bg):
        notes.append(f"{mode}: {n}")
    for key, ratio in (("--color-text", 7), ("--color-accent", 3)):
        cr = contrast(t[key], bg)
        if cr < ratio:
            notes.append(f"{mode}: {key} {t[key]} has only {cr:.1f}:1 contrast on the background")
    return t


def inverse_tokens(inv: str, inv_text: str, accent2: str | None) -> dict[str, str]:
    """The colors of a title, section or closing slide, from its background and text color."""
    lighter = luminance(inv_text) > luminance(inv)
    prefer = "lighter" if lighter else "darker"
    t = {"--color-inverse-bg": inv, "--color-inverse-text": inv_text}
    t["--color-inverse-muted"] = ensure_contrast(mix(inv_text, inv, 0.22), inv, 4.5, prefer=prefer)
    t["--color-inverse-border"] = mix(inv, inv_text, 0.28)
    t["--color-inverse-surface"] = mix(inv, inv_text, 0.12)
    ia = ensure_contrast(accent2 or mix(inv_text, inv, 0.3), inv, 4.5, prefer=prefer)
    if contrast(ia, inv) < 4.5 or _deck.delta_e(ia, inv_text) < 6:
        ia = t["--color-inverse-muted"]
    t["--color-inverse-accent"] = ia
    return t


_DEFAULTS: dict | None = None


def _default_tokens(variant: str = "light") -> dict[str, str]:
    global _DEFAULTS
    if _DEFAULTS is None:
        _DEFAULTS = _deck.theme_tokens((DEFAULT_DIR / "theme.css").read_text(encoding="utf-8"))
    base = dict(_DEFAULTS.get("", {}))
    if variant == "dark":
        base.update(_DEFAULTS.get("dark", {}))
    return base


def other_variant_seeds(bg: str, text: str, accent: str, accent2: str | None, chart: list[str], to: str):
    if to == "dark":
        L = oklab(text)[0]
        nbg = shift_lightness(text, min(L, 0.20)) if luminance(text) < 0.25 else "#101216"
        ntext = mix(bg, "#FFFFFF", 0.5) if luminance(bg) > 0.7 else "#F2F3F5"
        prefer = "lighter"
    else:
        nbg = mix(text, "#FFFFFF", 0.6) if luminance(text) > 0.7 else "#FAFAFA"
        L = oklab(bg)[0]
        ntext = shift_lightness(bg, min(L, 0.22))
        prefer = "darker"
    nacc = ensure_contrast(accent, nbg, 4.5, prefer=prefer)
    nacc2 = ensure_contrast(accent2, nbg, 3.0, prefer=prefer) if accent2 else None
    nchart = [ensure_contrast(c, nbg, 3.0, prefer=prefer) for c in chart]
    return nbg, ntext, nacc, nacc2, nchart


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
def inspect_font(path: Path) -> dict | None:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        f = TTFont(str(path), lazy=True)
    except Exception:  # noqa: BLE001
        return None
    name = f["name"]
    family = name.getDebugName(16) or name.getDebugName(1) or path.stem
    weight = getattr(f["OS/2"], "usWeightClass", 400) if "OS/2" in f else 400
    italic = bool("post" in f and f["post"].italicAngle) or bool("OS/2" in f and f["OS/2"].fsSelection & 1)
    wrange = None
    if "fvar" in f:
        for axis in f["fvar"].axes:
            if axis.axisTag == "wght":
                wrange = (int(axis.minValue), int(axis.maxValue))
    restricted = False
    if "OS/2" in f:
        fs_type = getattr(f["OS/2"], "fsType", 0)
        restricted = bool(fs_type & 0x0002)      # "Restricted License embedding"
    f.close()
    return {"family": family, "weight": weight, "italic": italic, "range": wrange, "restricted": restricted}


def add_fonts(font_dir: Path, out_fonts: Path, notes: list[str]) -> tuple[list[str], set[str]]:
    """Copy (and where possible compress) font files; return @font-face rules and family names."""
    rules, families = [], set()
    files = sorted(p for p in font_dir.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2"))
    if not files:
        notes.append(f"no font files (.ttf, .otf, .woff, .woff2) found in {font_dir}")
        return rules, families
    out_fonts.mkdir(parents=True, exist_ok=True)
    for src in files:
        info = inspect_font(src)
        if info is None:
            notes.append(f"could not read font {src.name}; skipped (fontTools is needed to read font files)")
            continue
        if info["restricted"]:
            notes.append(f"{src.name} is marked by its maker as not licensed for embedding; it was left out")
            continue
        dest_name, fmt = src.name, src.suffix.lower().lstrip(".")
        if fmt in ("ttf", "otf"):
            try:
                from fontTools.ttLib import TTFont
                import brotli  # noqa: F401
                f = TTFont(str(src))
                f.flavor = "woff2"
                dest_name = src.stem + ".woff2"
                f.save(str(out_fonts / dest_name))
                fmt = "woff2"
            except Exception:  # noqa: BLE001
                try:
                    from fontTools.ttLib import TTFont
                    f = TTFont(str(src))
                    f.flavor = "woff"
                    dest_name = src.stem + ".woff"
                    f.save(str(out_fonts / dest_name))
                    fmt = "woff"
                except Exception:  # noqa: BLE001
                    shutil.copyfile(src, out_fonts / dest_name)
                    fmt = "truetype" if fmt == "ttf" else "opentype"
        else:
            shutil.copyfile(src, out_fonts / dest_name)
        weight = f"{info['range'][0]} {info['range'][1]}" if info["range"] else str(info["weight"])
        rules.append(
            "@font-face {\n"
            f"  font-family: \"{info['family']}\";\n"
            f"  font-style: {'italic' if info['italic'] else 'normal'};\n"
            f"  font-weight: {weight};\n"
            "  font-display: block;\n"
            f"  src: url(\"fonts/{dest_name}\") format(\"{fmt}\");\n"
            "}")
        families.add(info["family"])
    return rules, families


def bundled_faces(family: str, out_fonts: Path) -> list[str]:
    """Reuse one of the built-in theme's open fonts in a new theme."""
    css = (DEFAULT_DIR / "theme.css").read_text(encoding="utf-8")
    rules = []
    for face in _deck.font_faces(css):
        if face["family"].lower() != family.lower():
            continue
        src = DEFAULT_DIR / face["url"]
        if src.is_file():
            out_fonts.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out_fonts / src.name)
            lic = DEFAULT_DIR / "fonts" / "OFL.txt"
            if lic.is_file():
                shutil.copyfile(lic, out_fonts / "OFL.txt")
            rules.append(face["raw"])
    return rules


def font_stack(family: str | None, role: str, embedded: set[str], notes: list[str], out_fonts: Path, rules: list[str]) -> str:
    default = _default_tokens()[f"--font-{role}"]
    if not family:
        for fam in [f.strip().strip("\"'") for f in default.split(",")]:
            if fam.lower() in BUNDLED and not any(f'"{fam}"' in r for r in rules):
                rules.extend(bundled_faces(fam, out_fonts))
        return default
    low = family.lower()
    if low in {e.lower() for e in embedded}:
        return f'"{family}", ' + ("ui-monospace, Menlo, Consolas, monospace" if role == "mono" else "system-ui, -apple-system, \"Segoe UI\", sans-serif")
    if low in BUNDLED:
        if not any(f'"{family}"' in r for r in rules):
            rules.extend(bundled_faces(family, out_fonts))
        generic = "monospace" if role == "mono" else "system-ui, sans-serif"
        return f'"{family}", {generic}'
    notes.append(
        f"font \"{family}\" ({role}) is not embedded: decks will use it only on computers that have it installed, and fall "
        f"back to the built-in {role} font elsewhere. To embed it, pass --fonts with the font files, if its license allows "
        "embedding in shared files.")
    for fam in [f.strip().strip("\"'") for f in default.split(",")]:
        if fam.lower() in BUNDLED and not any(f'"{fam}"' in r for r in rules):
            rules.extend(bundled_faces(fam, out_fonts))
    return f'"{family}", {default}'


# --------------------------------------------------------------------------
# Writing the theme
# --------------------------------------------------------------------------
GROUPS = [
    ("Color: surfaces and ink", r"--color-(bg|surface|surface-2|text|text-muted|text-subtle|border)$"),
    ("Color: accents", r"--color-accent"),
    ("Color: meaning", r"--color-(positive|negative|warning)$"),
    ("Color: inverse slides (title, section, closing)", r"--color-(inverse|letterbox)"),
    ("Chart palette: categorical order is fixed, never cycled", r"--chart-"),
    ("Type: families", r"--font-"),
    ("Type: weights", r"--weight-"),
    ("Type: scale", r"--text-"),
    ("Type: rhythm", r"--(leading|tracking)-"),
    ("Spacing scale", r"--space-"),
    ("Frame: where the title sits, the margins, the footer", r"--(frame|title|eyebrow|footer|hero|section|column)-"),
    ("Bullets: a drawn shape for each of two levels", r"--bullet-"),
    ("Background picture, and a panel behind the text when the picture is busy", r"--bg-"),
    ("Shape", r"--(radius|stroke|shadow)-"),
    ("Icons", r"--icon-"),
    ("Logo (set by the build when the theme folder has a logo file)", r"--logo-"),
    ("Motion", r"--(dur|stagger|ease)"),
    ("Engine chrome", r"--progress-"),
]


# Written into a theme's Decor only when one of its pictures needs it, so
# flat themes and calm pictures carry no rule for a panel at all.
PANEL_CSS = """/* The panel behind the text on a picture too busy to read over. Its color is --bg-panel, and it covers the
   text area. It is this theme's use of .slide::before: decoration on a custom slide needs an element of its own. */
.slide { isolation: isolate; }
:where(.slide)::before {
  content: "";
  position: absolute;
  z-index: -1;
  top: calc(var(--frame-top) - var(--space-4));
  right: calc(var(--frame-right, var(--frame-x)) - var(--space-4));
  bottom: calc(var(--footer-offset) - var(--space-3));
  left: calc(var(--frame-left, var(--frame-x)) - var(--space-4));
  border-radius: var(--radius-lg);
  background: var(--bg-panel, none);
  pointer-events: none;
}
:where(.slide[data-layout="title"], .slide[data-layout="section"])::before { bottom: calc(var(--hero-bottom, var(--space-7)) - var(--space-5)); }
:where(.slide[data-layout="full-bleed"])::before { content: none; }
"""


def bullet_tokens(level: int, bullet: dict, bg: str, mode: str) -> dict[str, str]:
    """Tokens that draw one level's bullet. {} leaves the built-in dash as it is."""
    prefix = "--bullet-" if level == 1 else "--bullet-2-"
    shape = bullet.get("shape") or "dot"
    scale = max(0.5, min(2.0, float(bullet.get("scale") or 1)))
    t: dict[str, str] = {}
    if shape in ("dot", "square", "picture"):
        side = f"{round(0.3 * scale, 2):g}em"
        t.update({"char": '""', "width": side, "height": side, "radius": "var(--radius-pill)" if shape != "square" else "0px",
                  "top": f"calc((1lh - {side}) / 2)"})
    elif shape == "dash":
        t.update({"char": '""', "width": f"{round(0.5 * scale, 2):g}em", "height": "var(--stroke-thin)", "radius": "var(--radius-pill)",
                  "top": "calc((1lh - var(--stroke-thin)) / 2)"})
    elif shape == "char" and bullet.get("char"):
        t.update({"char": json.dumps(str(bullet["char"])[:2], ensure_ascii=False), "width": "0px", "height": "0px", "radius": "0px", "top": "0px"})
    elif shape == "none":
        t.update({"char": '""', "width": "0px", "height": "0px", "radius": "0px", "top": "0px"})
    else:                                         # numbering, or something not understood: the built-in bullet stays
        return {}
    if bullet.get("color"):
        try:
            t["color"] = ensure_contrast(hexc(bullet["color"]), bg, 3.0, prefer="darker" if mode == "light" else "lighter")
        except ValueError:
            pass
    elif bullet.get("text_color"):
        t["color"] = "var(--color-text)" if level == 1 else "var(--color-text-muted)"
    out = {prefix + key: value for key, value in t.items()}
    if level == 1:
        if shape == "none":
            out["--bullet-indent"] = "0px"
        elif bullet.get("indent"):
            out["--bullet-indent"] = f"{max(44 if shape == 'char' else 28, min(80, int(bullet['indent'])))}px"
    return out


def footer_css(label_side: str | None, number_side: str | None, number_first: bool = False) -> str:
    """Decor rules that put the footer label and the slide number where a template has them.

    The built-in footer is a row: logo, label on the left, number on the right.
    A side of None means that part is hidden. Returns "" when nothing has to move.
    """
    if label_side == number_side == "center":
        number_side = "right"                     # two things cannot share the middle
    if (label_side or "left", number_side or "right") == ("left", "right"):
        return ""
    items = [(".slide-footer > .slide-footer-text", label_side), (".slide-footer > .slide-number", number_side)]
    if number_first:
        items.reverse()
    rules, order = [], 1
    for side in ("left", "right"):
        first = True
        for selector, where in items:
            if where != side:
                continue
            margin = "auto" if side == "right" and first else "0"
            rules.append(f"{selector} {{ order: {order}; margin-left: {margin}; }}")
            order, first = order + 1, False
    for selector, where in items:
        if where == "center":
            rules.append(f"{selector} {{ position: absolute; left: 50%; transform: translateX(-50%); margin: 0; }}")
    return "\n".join(rules) + "\n"


def format_block(selector: str, tokens: dict[str, str]) -> str:
    lines, used = [f"{selector} {{"], set()
    for title, pat in GROUPS:
        keys = [k for k in tokens if k not in used and re.match(pat, k)]
        if not keys:
            continue
        lines.append(f"  /* {title} */")
        for k in keys:
            lines.append(f"  {k}: {tokens[k]};")
            used.add(k)
        lines.append("")
    rest = [k for k in tokens if k not in used]
    if rest:
        lines.append("  /* Other */")
        lines += [f"  {k}: {tokens[k]};" for k in rest]
        lines.append("")
    while lines[-1] == "":
        lines.pop()
    lines.append("}")
    return "\n".join(lines)


def write_theme(spec: dict, args, notes: list[str]) -> Path:
    name = re.sub(r"[^a-z0-9-]+", "-", (spec.get("name") or args.name or "").lower()).strip("-")
    if not name:
        _deck.die("the theme needs a name (--name)")
    if name == "default" and not args.into:
        _deck.die("'default' is the built-in theme's name; pick another")
    base = Path(args.into).expanduser() if args.into else _deck.library_dir()
    out = base / "themes" / name
    if out.exists() and not args.force:
        _deck.die(f"{out} already exists. Pass --force to replace it, or pick another name.")
    out.mkdir(parents=True, exist_ok=True)
    out_fonts = out / "fonts"

    c = dict(spec.get("colors", {}))

    # Backgrounds: measured from the template already, or pictures named in the spec or with --background
    kinds = dict(spec.get("backgrounds") or {})
    files = {k: Path(v).expanduser() for k, v in kinds.items() if isinstance(v, str)}
    for item in getattr(args, "background", None) or []:
        kind, _, fname = item.partition("=")
        if not fname:
            _deck.die(f"--background takes KIND=FILE, for example content=bg.png (got '{item}')")
        files[kind.strip()] = Path(fname).expanduser()
    if files:
        try:
            seed = hexc(c.get("text", "#111111"))
        except ValueError as exc:
            _deck.die(str(exc))
        made, bnotes = _backgrounds.from_files(files, seed if luminance(seed) < 0.2 else "#111111", "#FFFFFF")
        kinds = {k: v for k, v in kinds.items() if not isinstance(v, str)}
        kinds.update(made)
        notes += bnotes
    if (out / "backgrounds").is_dir():          # pictures from an earlier run of this theme
        shutil.rmtree(out / "backgrounds")
    content = kinds.get("content") or {}
    picture = bool(content) and "flat" not in content
    if picture:
        c["bg"], c["text"] = content["bg"], content["text"]
    elif content.get("flat") and "content" in files:
        c["bg"] = content["flat"]
    try:
        bg, text, accent = hexc(c.get("bg", "#FFFFFF")), hexc(c.get("text", "#111111")), hexc(c.get("accent", "#2B3BF0"))
        accent2 = hexc(c["accent2"]) if c.get("accent2") else None
        chart = [hexc(x) for x in (c.get("chart") or [accent] + ([accent2] if accent2 else []))]
        inverse_bg = hexc(c["inverse_bg"]) if c.get("inverse_bg") else None
        title = hexc(c["title"]) if c.get("title") else None
    except ValueError as exc:
        _deck.die(str(exc))
    base_mode = "dark" if luminance(bg) < 0.18 else "light"
    other = "light" if base_mode == "dark" else "dark"

    tokens = dict(_default_tokens())
    tokens.update(color_tokens(bg, text, accent, accent2, chart, base_mode, notes, inverse_bg, title))
    if title is None:
        tokens["--title-color"] = "var(--color-text)"

    # Fonts
    rules: list[str] = []
    embedded: set[str] = set()
    fspec = spec.get("fonts", {}) or {}
    font_dir = getattr(args, "fonts", None) or fspec.get("dir")
    if font_dir:
        r, fams = add_fonts(Path(font_dir).expanduser(), out_fonts, notes)
        rules += r
        embedded |= fams
    for role in ("display", "body", "mono"):
        fam = fspec.get(role)
        if role == "display" and not fam:
            fam = fspec.get("body")
        tokens[f"--font-{role}"] = font_stack(fam, role, embedded, notes, out_fonts, rules)

    # Frame and shape
    frame = spec.get("frame", {}) or {}
    if frame.get("x"):
        tokens["--frame-x"] = f"{max(72, min(200, int(frame['x'])))}px"
    if frame.get("top"):
        tokens["--frame-top"] = f"{max(56, min(140, int(frame['top'])))}px"
    if frame.get("title_size"):
        size = max(52, min(96, int(frame["title_size"])))
        tokens["--title-size"] = f"{size}px"
        if size != int(frame["title_size"]):
            notes.append(f"the template's title size ({frame['title_size']}px on this stage) was limited to {size}px to suit the layouts")
    if frame.get("column_gap"):
        tokens["--column-gap"] = f"{max(40, min(128, int(frame['column_gap'])))}px"
    if frame.get("title_weight"):
        tokens["--title-weight"] = str(frame["title_weight"])
        tokens["--weight-display"] = str(frame["title_weight"])
    tokens.update(SHAPES.get(spec.get("shape") or "soft", SHAPES["soft"]))

    # What each kind of slide takes from its layout in the template: the content kind sets tokens on :root,
    # the others get a rule each in Decor.
    aligned = {"left": "start", "centre": "center", "right": "end", "start": "start", "center": "center", "end": "end"}
    per_kind = {k: dict(v) for k, v in (spec.get("layouts") or {}).items() if isinstance(v, dict)}
    asked = getattr(args, "title_align", None) or frame.get("title_align")
    if asked:                                     # one alignment for every kind of slide
        for kind in ("content", "title", "section", "closing"):
            per_kind.setdefault(kind, {})["title_align"] = asked
    layout_rules: dict[str, dict[str, str]] = {}
    for kind, values in per_kind.items():
        decl: dict[str, str] = {}
        align = aligned.get(str(values.get("title_align") or "").lower())
        if values.get("title_align") and not align:
            notes.append(f"title alignment '{values['title_align']}' is not left, center or right; it was left as it is")
        if align:
            decl["--title-align"] = align
        if values.get("place") in ("flex-start", "center", "flex-end") and kind in ("title", "section"):
            decl["--hero-justify"] = values["place"]
            if kind == "section" and values["place"] != "flex-end":
                decl["--section-number-gap"] = "var(--space-4)"   # nothing to pin the number against
        if kind == "content":
            tokens.update(decl)
        elif decl:
            layout_rules[kind] = decl
    content_align = tokens.get("--title-align", "start")
    for kind in list(layout_rules):
        if layout_rules[kind].get("--title-align") == content_align:
            del layout_rules[kind]["--title-align"]
        if layout_rules[kind].get("--hero-justify") == "flex-end":
            del layout_rules[kind]["--hero-justify"]
        if not layout_rules[kind]:
            del layout_rules[kind]

    def px_of(name: str, default: int) -> int:
        m = re.fullmatch(r"(-?\d+)px", tokens.get(name, ""))
        return int(m.group(1)) if m else default

    # Body text. PowerPoint sets one big text box per slide, usually at 24 to 32pt. The layouts here hold
    # more than one block, so they keep their own sizes and only lean toward a template that is clearly
    # smaller or larger than that: at most 10% either way.
    body = spec.get("body") or {}
    try:
        size_pt = float(body.get("size_pt") or 0)
    except (TypeError, ValueError):
        size_pt = 0
    if size_pt:
        lean = max(0.9, size_pt / 24) if size_pt < 24 else (min(1.1, size_pt / 32) if size_pt > 32 else 1.0)
        lean = round(lean, 2)
        if lean != 1.0:
            for name in ("--text-sm", "--text-base", "--text-md", "--text-lg"):
                tokens[name] = f"{round(px_of(name, 0) * lean)}px"
        if lean == 1.0:
            notes.append(f"body text in the template is {size_pt:g}pt; the theme keeps its own text sizes, which fit more on a slide")
        else:
            most = ", the most the layouts allow" if lean in (0.9, 1.1) else ""
            notes.append(f"body text in the template is {size_pt:g}pt, {'smaller' if lean < 1 else 'larger'} than usual; text sizes were "
                         f"{'reduced' if lean < 1 else 'increased'} by {abs(round((lean - 1) * 100))}% (--text-sm to --text-lg){most}")
    try:
        line = float(body.get("line") or 0)
    except (TypeError, ValueError):
        line = 0
    if line:
        tokens["--leading-snug"] = f"{max(1.05, min(1.5, 1.22 * line)):.2f}"
        tokens["--leading-normal"] = f"{max(1.2, min(1.7, 1.42 * line)):.2f}"
        notes.append(f"line spacing follows the template ({round(line * 100)}% of single): --leading-snug {tokens['--leading-snug']}, "
                     f"--leading-normal {tokens['--leading-normal']}")

    # Bullets: the shape, color and indent of the first two levels
    levels = [dict(b) for b in (spec.get("bullets") or []) if isinstance(b, dict)][:2]
    if getattr(args, "bullet", None):
        levels = [dict(levels[0] if levels else {}, shape=args.bullet, char=None)] + levels[1:]
    drawn = []
    for n, bullet in enumerate(levels, 1):
        made = bullet_tokens(n, bullet, bg, base_mode)
        tokens.update(made)
        if bullet.get("note"):
            notes.append(f"level {n} bullets in the template are {bullet['note']}")
        if made:
            what = {"char": f"\"{bullet.get('char')}\"", "none": "none", "picture": "a dot"}.get(bullet["shape"], f"a {bullet['shape']}")
            drawn.append(f"level {n} {what}" + (f" in {made[('--bullet-' if n == 1 else '--bullet-2-') + 'color']}"
                                                if bullet.get("color") and ("--bullet-" if n == 1 else "--bullet-2-") + "color" in made else ""))
    if drawn and spec.get("source"):
        notes.append("bullets follow the template: " + ", ".join(drawn))

    # Footer: which of the label and the slide number show, where, how big and in what color
    foot = {key: dict((spec.get("footer") or {}).get(key) or {}) for key in ("label", "number")}
    for key, asked in (("number", getattr(args, "slide_number", None)), ("label", getattr(args, "footer_label", None))):
        if asked == "off":
            foot[key].update(shown=False, why="")
        elif asked:
            foot[key].update(shown=True, side=asked)
    footer_rules = ""
    said = []
    words = {"label": "footer label", "number": "slide number"}
    for key, token_name in (("label", "--footer-label"), ("number", "--footer-number")):
        if foot[key].get("shown") is False:
            tokens[token_name] = "none"
            flag = "--slide-number right" if key == "number" else "--footer-label left"
            if foot[key].get("why", "the template does not show it"):      # hidden by the template, not by a flag
                notes.append(f"the {words[key]} is hidden because {foot[key].get('why', 'the template does not show it')}; pass {flag} to show it")
    shown = [key for key in ("number", "label") if foot[key].get("shown", True)]
    if shown:
        lead = foot[shown[0]]                      # the slide number sets the line, the label follows it
        label_side = foot["label"].get("side") or "left"
        number_side = foot["number"].get("side") or "right"
        both = len(shown) == 2
        number_first = both and (foot["number"].get("x") or 0) < (foot["label"].get("x") or 0)
        footer_rules = footer_css(label_side if "label" in shown else None, number_side if "number" in shown else None, number_first)
        if footer_rules:
            said.append(" and ".join(([f"slide number {number_side}"] if "number" in shown else [])
                                     + ([f"label {label_side}"] if "label" in shown else [])))
        if lead.get("size") and abs(lead["size"] - 24) > 1:
            size = max(18, min(30, int(lead["size"])))
            tokens["--footer-size"] = f"{size}px"
            said.append(f"{size}px text")
        if lead.get("offset") is not None and abs(lead["offset"] - 44) > 3:
            tokens["--footer-offset"] = f"{max(20, min(140, int(lead['offset'])))}px"
            said.append(f"{tokens['--footer-offset']} from the bottom")
        if lead.get("color"):
            try:
                tokens["--footer-color"] = ensure_contrast(hexc(lead["color"]), bg, 3.0, prefer="darker" if base_mode == "light" else "lighter")
                said.append("the template's footer color")
            except ValueError:
                pass
    if said:
        notes.append("the footer follows the template: " + ", ".join(said))

    # Background pictures: the content one goes on :root, the others get a rule each in Decor
    saved: dict[str, str] = {}
    bg_meta: dict[str, dict] = {}

    def remember(kind: str, entry: dict | None, value: str) -> None:
        if entry is None:
            return
        if "flat" in entry:
            bg_meta[kind] = {"flat": entry["flat"]}
            return
        bg_meta[kind] = {
            "picture": value,
            "from": entry.get("layout", ""), "drawn_by_libreoffice": bool(entry.get("rendered")),
            "safe": list(entry["safe"]) if entry.get("safe") else None,
            "ink": entry["ink"], "text": entry["text"], "bg": entry["bg"], "worst": entry["worst"],
            "calm": entry["calm"], "panel": entry["panel"], "art": entry.get("art"),
            "description": entry["description"],
        }
        if entry.get("zones"):
            z = entry["zones"]
            bg_meta[kind]["title_area"] = {"box": [round(v) for v in z["title"]], "anchor": z.get("anchor"), "text": z.get("title_text")}
            bg_meta[kind]["body_area"] = [round(v) for v in z["body"]]

    def picture_value(kind: str, entry: dict) -> tuple[str, str]:
        """(the value for --bg-image, what theme.json records) for one entry.

        A picture file is declared once on :root as --bg-<name> and used by
        name, so a deck carries one copy however many kinds of slide share it,
        and the build can leave out pictures a deck never shows.
        """
        if entry.get("css"):
            return entry["css"], entry["css"]
        fname = _backgrounds.save(entry, out / "backgrounds", kind, saved)
        token = "--bg-" + Path(fname).stem
        tokens[token] = f'url("backgrounds/{fname}")'
        return f"var({token})", f"backgrounds/{fname}"

    def panel_value(entry: dict) -> str:
        panel = entry.get("panel")
        if not panel:
            return "none"
        r, g, b = (round(v * 255) for v in _deck.parse_hex(panel["color"]))
        return f"rgb({r} {g} {b} / {panel['alpha']})"

    def side_margins(safe, what: str) -> tuple[int, int]:
        left = max(64, min(800, round(safe[0])))
        right = max(64, min(800, round(_backgrounds.STAGE_W - safe[0] - safe[2])))
        if _backgrounds.STAGE_W - left - right < 900:
            scale = (_backgrounds.STAGE_W - 900) / (left + right)
            left, right = round(left * scale), round(right * scale)
            notes.append(f"the template leaves a narrow text area on {what} slides; the side margins were eased to keep 900px for content")
        return left, right

    title_rule = ""
    if picture:
        tokens["--bg-image"], recorded = picture_value("content", content)
        tokens["--bg-panel"] = panel_value(content)
        remember("content", content, recorded)
        safe = content.get("safe")
        if safe:
            left, right = side_margins(safe, "content")
            bottom = max(110, min(380, round(_backgrounds.STAGE_H - safe[1] - safe[3])))
            if content["calm"] and content.get("clear_below"):
                # templates leave a deep bottom margin for their own footer; where the picture is empty
                # there, content may run down to the built-in theme's margin instead
                bottom = max(120, min(bottom, _backgrounds.STAGE_H - int(content["clear_below"]) + 32))
            elif not content["calm"]:
                bottom = 120                        # the panel runs down to the footer, so the text may too
            tokens["--frame-x"] = tokens["--frame-left"] = f"{left}px"
            tokens["--frame-right"] = f"{right}px"
            tokens["--frame-top"] = f"{max(24, min(300, round(safe[1])))}px"
            tokens["--frame-bottom"] = f"{bottom}px"
            zones = content.get("zones")
            if zones:
                # The template's title box and text box, kept apart: the title gets an area as tall as its box and
                # sits in it as the template has it, and the body starts where the text box starts. Whatever the
                # template draws between the two (a rule, the edge of a band) then falls between title and body.
                tbox, bbox = zones["title"], zones["body"]
                area = max(40, min(420, round(tbox[3])))
                tokens["--title-min"] = f"{area}px"
                tokens["--title-anchor"] = zones.get("anchor") or "start"
                tokens["--title-gap"] = f"{max(12, min(240, round(bbox[1] - (tbox[1] + tbox[3]))))}px"
                tokens["--title-measure"] = f"{max(400, round(tbox[0] + tbox[2] - left))}px"
                # When the template draws something under the title (a rule, the edge of a band), the title has that
                # much room and no more. When it draws nothing there, a longer title just pushes the body down.
                room = zones.get("room")
                size = px_of("--title-size", 72)
                if room:
                    if size * 1.04 > room:         # one line has to fit
                        size = max(40, int(room / 1.04))
                        tokens["--title-size"] = f"{size}px"
                        notes.append(f"the title size was reduced to {size}px so one line fits above what the template draws under it")
                    tokens["--title-max"] = f"{room}px"
                    fits = max(1, int(room // (size * 1.04)))
                    chars = int(px_of("--title-measure", 1000) / (size * 0.5))
                    bg_meta["content"]["title_area"].update(lines=fits, room=room)
                    notes.append(f"the template draws something under the title, so a title has room for {fits} line{'s' if fits > 1 else ''} "
                                 f"of about {chars} characters ({room}px); the render check reports a title that runs into it")
                # The title may sit on something the body does not: a band, a tint. Its colors then go in a rule
                # for the slides that show this background, so a flat slide (a tone, data-bg="none") keeps its own.
                if zones.get("title_text") and (contrast(text, zones["title_bg"]) < 4.5 or contrast(zones["title_bg"], bg) > 1.25):
                    eyebrow = ensure_contrast(accent, zones["title_bg"], 4.5, prefer="lighter" if zones.get("title_ink") == "light" else "darker")
                    title_rule = ("/* Titles sit on " + zones["title_bg"] + " in the content background. */\n"
                                  '.slide:where(:not([data-tone], [data-bg], [data-layout="title"], [data-layout="section"], '
                                  '[data-layout="closing"], [data-layout="full-bleed"])) { '
                                  f"--title-color: {zones['title_text']}; --eyebrow-color: {eyebrow}; }}\n")
                    notes.append(f"the title sits on {zones['title_bg']} in the template, so titles on that background are {zones['title_text']}")
            if content.get("image") is not None and content["calm"]:
                base_offset = px_of("--footer-offset", 44)
                lift = _backgrounds.footer_offset(content["image"], left, right, offset=base_offset)
                if lift > base_offset:
                    tokens["--footer-offset"] = f"{lift}px"
                    tokens["--frame-bottom"] = f"{max(bottom, lift + 76)}px"
                    notes.append(f"the footer was raised to {lift}px from the bottom so it sits clear of the artwork there")
            if _backgrounds.STAGE_W - left - right < 1300:
                notes.append(f"content slides have {_backgrounds.STAGE_W - left - right}px of width for text (the built-in theme has 1680px): "
                             "plan fewer columns and shorter lines, and check the rendered slides for overflow")
        notes.append("the content background is a picture, so this theme has one look: there is no automatic dark version")
    elif content:
        remember("content", content, "")

    # content must end clear of the footer line, wherever the template put it
    foot_top = px_of("--footer-offset", 44) + px_of("--footer-size", 24) + 40
    if px_of("--frame-bottom", 120) < foot_top:
        tokens["--frame-bottom"] = f"{foot_top}px"

    hero_css = []
    title_entry = kinds.get("title")
    heroes = {kind: (kinds.get(kind) if kind in kinds else title_entry) for kind in ("title", "section", "closing")}
    if picture or any(e and "flat" not in e for e in heroes.values()):
        groups: list[tuple[dict | None, list[str]]] = []
        for kind, entry in heroes.items():
            match = next((g for g in groups if g[0] is entry), None)
            if match:
                match[1].append(kind)
            else:
                groups.append((entry, [kind]))
        for entry, names in groups:
            decl: dict[str, str] = {"--bg-image": "none", "--bg-panel": "none"}
            if "--title-min" in tokens:
                decl.update({"--title-min": "auto", "--title-anchor": "normal", "--title-gap": "52px", "--title-measure": "30ch", "--title-max": "none"})
            recorded = ""
            if entry and "flat" in entry:
                flat = entry["flat"]
                ink = "#FFFFFF" if contrast("#FFFFFF", flat) >= 4.5 else (text if luminance(text) < 0.2 else "#111111")
                decl.update(inverse_tokens(flat, ink, accent2))
            elif entry:
                decl["--bg-image"], recorded = picture_value(names[0], entry)
                decl["--bg-panel"] = panel_value(entry)
                decl.update(inverse_tokens(entry["bg"], entry["text"], accent2))
                safe = entry.get("safe")
                if safe:
                    left, right = side_margins(safe, names[0])
                    decl["--frame-left"], decl["--frame-right"] = f"{left}px", f"{right}px"
                    decl["--frame-top"] = f"{max(48, min(520, round(safe[1])))}px"
                    decl["--hero-bottom"] = f"{max(72, min(560, round(_backgrounds.STAGE_H - safe[1] - safe[3])))}px"
                    width = _backgrounds.STAGE_W - left - right
                    if width < 1300:               # big type sized for a full-width slide would not fit the text area
                        decl["--text-display"] = f"{max(80, min(164, round(width / 8.5)))}px"
                        decl["--text-3xl"] = f"{max(72, min(120, round(width / 10)))}px"
                    # the section number sits on its title instead of at the top of the slide, where the artwork may be
                    decl["--section-number-gap"] = "var(--space-4)"
                    decl["--text-mega"] = "200px"
            for kind in names:
                remember(kind, entry if kind in kinds else None, recorded)
            selector = ",\n".join(f'.slide[data-layout="{n}"]:where(:not([data-tone], [data-bg])),\n.slide[data-bg="{n}"]' for n in names)
            source = f' ("{entry["layout"]}" in the template)' if entry and entry.get("layout") else ""
            hero_css.append(f"/* {', '.join(names).capitalize()} slides{source} */\n{selector} {{\n"
                            + "".join(f"  {k}: {v};\n" for k, v in decl.items()) + "}")

    # More backgrounds, from the template's other layouts: a slide asks for one with data-bg="name".
    # Each is a content slide on another background, so it gets the full set of colors for that
    # background, and the tokens that point at colors are stated again (they were worked out on :root).
    more_css, more_names = [], []
    for bg_name, entry in (spec.get("more_backgrounds") or {}).items():
        if not isinstance(entry, dict):
            continue
        decl = {"--bg-image": "none", "--bg-panel": "none"}
        if "--title-min" in tokens and "flat" not in entry:
            decl.update({"--title-min": "auto", "--title-anchor": "normal", "--title-gap": "52px", "--title-measure": "30ch", "--title-max": "none"})
        recorded = ""
        if "flat" in entry:
            ebg = entry["flat"]
            etext = "#FFFFFF" if contrast("#FFFFFF", ebg) > contrast(text if luminance(text) < 0.2 else "#111111", ebg) else (
                text if luminance(text) < 0.2 else "#111111")
        else:
            decl["--bg-image"], recorded = picture_value(bg_name, entry)
            decl["--bg-panel"] = panel_value(entry)
            ebg, etext = entry["bg"], entry["text"]
        emode = "dark" if luminance(ebg) < 0.18 else "light"
        colors = color_tokens(ebg, etext, accent, accent2, chart, emode, [], inverse_bg, None)
        decl.update({k: v for k, v in colors.items()
                     if (k.startswith("--color-") and not k.startswith(("--color-inverse", "--color-letterbox"))) or k.startswith("--chart-")})
        decl.update({"--title-color": "var(--color-text)", "--eyebrow-color": "var(--color-accent)", "--footer-color": "var(--color-text-subtle)"})
        for key, fallback in (("--bullet-color", "var(--color-accent)"), ("--bullet-2-color", "var(--color-text-subtle)")):
            value = tokens.get(key, fallback)
            decl[key] = ensure_contrast(value, ebg, 3.0, prefer="darker" if emode == "light" else "lighter") if value.startswith("#") else value
        safe = entry.get("safe")
        if safe and "flat" not in entry:
            left, right = side_margins(safe, f'"{bg_name}"')
            decl["--frame-left"], decl["--frame-right"] = f"{left}px", f"{right}px"
            decl["--frame-top"] = f"{max(48, min(300, round(safe[1])))}px"
            decl["--frame-bottom"] = f"{max(foot_top, 120, min(380, round(_backgrounds.STAGE_H - safe[1] - safe[3])))}px"
        remember(bg_name, entry, recorded)
        bg_meta[bg_name]["from"] = entry.get("layout", "")
        bg_meta[bg_name]["extra"] = True
        more_names.append(bg_name)
        more_css.append(f'/* "{entry.get("layout", bg_name)}" in the template */\n.slide[data-bg="{bg_name}"]:where(:not([data-tone])) {{\n'
                        + "".join(f"  {k}: {v};\n" for k, v in decl.items()) + "}")
    if more_names:
        notes.append("more backgrounds from the template's other layouts, for a slide to ask for by name: "
                     + ", ".join(f'data-bg="{n}"' for n in more_names))

    blocks = [format_block(":root", tokens)]
    variants = [base_mode]
    if spec.get("dark", True) and not getattr(args, "single_variant", False) and not picture:
        nbg, ntext, nacc, nacc2, nchart = other_variant_seeds(bg, text, accent, accent2, chart, other)
        vt = color_tokens(nbg, ntext, nacc, nacc2, nchart, other, notes, inverse_bg, None)
        if title is not None:
            vt["--title-color"] = "var(--color-text)"
        for fixed in ("--footer-color", "--bullet-color", "--bullet-2-color"):    # a fixed color has to read on the other background too
            if tokens.get(fixed, "").startswith("#"):
                vt[fixed] = ensure_contrast(tokens[fixed], nbg, 3.0, prefer="darker" if other == "light" else "lighter")
        blocks.append(format_block(f':root[data-variant="{other}"]', vt))
        variants.append(other)
        notes.append(f"the {other} variant was derived automatically from the {base_mode} one; review it")

    # Logo
    logo_meta = {}
    logos = {}
    for key, src in (spec.get("logo") or {}).items():
        logos[base_mode if key == "base" else key] = src
    if getattr(args, "logo", None):
        logos[base_mode] = args.logo
    if getattr(args, "logo_dark", None):
        logos["dark"] = args.logo_dark
    for key, src in logos.items():
        sp = Path(src).expanduser()
        if not sp.is_file():
            notes.append(f"logo file not found: {src}")
            continue
        dest = out / (("logo" if key == base_mode else f"logo-{key}") + sp.suffix.lower())
        if sp.resolve() != dest.resolve():
            shutil.copyfile(sp, dest)
        logo_meta[key] = dest.name
    if logo_meta and other in variants and other not in logo_meta:
        notes.append(f"the logo has no {other} version; the same file is used on {other} slides. Pass --logo-dark if it does not read well there.")

    label = spec.get("label") or name.replace("-", " ").title()
    header = (
        "/* ==========================================================================\n"
        f"   THEME: {name} ({label})\n"
        + (f"   Generated from {spec['source']} by add_theme.py. Edit any value by hand.\n" if spec.get("source") else
           "   Generated by add_theme.py. Edit any value by hand.\n")
        + "   Structure: 1 fonts, 2 tokens (base), 3 variants, 4 decor.\n"
        "   Sizes are in px on a 1920 x 1080 stage.\n"
        "   ========================================================================== */\n")
    css = header + "\n/* ---- 1. Fonts ----------------------------------------------------------- */\n"
    css += ("\n".join(rules) + "\n" if rules else "/* No fonts are embedded; the families below come from the viewer's computer. */\n")
    css += f"\n/* ---- 2. Tokens: base ({base_mode}) {'-' * 46} */\n" + blocks[0] + "\n"
    if len(blocks) > 1:
        css += f"\n/* ---- 3. Variant: {other} {'-' * 52} */\n" + blocks[1] + "\n"
    css += "\n/* ---- 4. Decor ----------------------------------------------------------- */\n/* Optional extra CSS for the frame: rules, marks, logo placement. */\n"
    css += title_rule
    if footer_rules:
        css += "/* The footer, arranged as in the template: where the label and the slide number sit. */\n" + footer_rules
    if layout_rules:
        css += ("/* What the template's layouts set for each kind of slide. */\n"
                + "".join(f'.slide[data-layout="{kind}"] {{ ' + " ".join(f"{k}: {v};" for k, v in decl.items()) + " }\n"
                          for kind, decl in layout_rules.items()))
    if any(entry.get("panel") for entry in list(kinds.values()) + [e for e in heroes.values() if e] if "flat" not in entry):
        css += PANEL_CSS
    if hero_css:
        css += ("/* Backgrounds for title, section and closing slides. Each rule carries the picture, the margins that keep\n"
                "   text clear of its artwork, and the colors that read on it. A slide opts in with data-bg=\"title\" (or\n"
                "   section, closing) and out with data-bg=\"none\". */\n" + "\n".join(hero_css) + "\n")
    if more_css:
        css += ("/* More backgrounds, from the template's other layouts. A slide asks for one with data-bg=\"name\"; each rule\n"
                "   carries the picture or color, the margins that keep text clear of its artwork, and the colors that read on it. */\n"
                + "\n".join(more_css) + "\n")
    (out / "theme.css").write_text(css, encoding="utf-8")

    fam_list = sorted({m.group(1) for r in rules for m in [re.search(r'font-family:\s*"([^"]+)"', r)] if m})
    meta = {
        "name": name,
        "label": label,
        "description": spec.get("description") or (f"Generated from {spec['source']}" if spec.get("source") else "Custom theme"),
        "variants": variants,
        "default_variant": base_mode,
        "icons": spec.get("icons") or "",
        "fonts": {"license": spec.get("font_license") or "", "families": fam_list},
        "logo": logo_meta or None,
    }
    if spec.get("master"):
        meta["master"] = spec["master"]            # which of the template's slide masters this came from
    if any("picture" in entry or entry.get("extra") for entry in bg_meta.values()):
        meta["backgrounds"] = bg_meta
    (out / "theme.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Checking a theme
# --------------------------------------------------------------------------
def resolve_tokens(tokens: dict[str, str]) -> dict[str, str]:
    out = dict(tokens)
    for _ in range(4):
        for k, v in out.items():
            m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", v)
            if m:
                out[k] = out.get(m.group(1), m.group(2) or v)
    return out


def check_theme(path: Path) -> tuple[list[str], list[str]]:
    """Returns (problems, notes) for a theme folder."""
    problems, notes = [], []
    css = (path / "theme.css").read_text(encoding="utf-8")
    tokens = _deck.theme_tokens(css)
    base = tokens.get("", {})
    defaults = _default_tokens()
    missing = [k for k in defaults if k not in base]
    if missing:
        notes.append(f"{len(missing)} token(s) not defined; the built-in theme's values are used for: {', '.join(missing)}")
    unknown = [k for k in base if k not in defaults and not k.startswith("--bg-")]   # --bg-<name> holds a background picture
    if unknown:
        notes.append(f"extra tokens the layouts do not use: {', '.join(unknown[:10])}")
    meta = _deck.read_json(path / "theme.json", {}) or {}
    base_name = meta.get("default_variant") or "light"
    for variant, vt in [(base_name, {})] + [(k, v) for k, v in tokens.items() if k]:
        merged = dict(defaults)
        merged.update(base)
        merged.update(vt)
        t = resolve_tokens(merged)

        def is_hex(v):
            return bool(re.fullmatch(r"#[0-9a-fA-F]{3,8}", v or ""))
        bg = t.get("--color-bg", "")
        if not is_hex(bg):
            continue
        for key, ratio, why in (("--color-text", 7, "body text"), ("--color-text-muted", 4.5, "secondary text"),
                                ("--color-text-subtle", 4.5, "captions and footers"), ("--color-accent", 3, "accent marks and eyebrows"),
                                ("--color-positive", 3, "positive figures"), ("--color-negative", 3, "negative figures")):
            v = t.get(key, "")
            if is_hex(v) and contrast(v, bg) < ratio:
                problems.append(f"{variant}: {key} {v} on the background {bg} is {contrast(v, bg):.1f}:1 ({ratio}:1 wanted for {why})")
        inv = t.get("--color-inverse-bg", "")
        if is_hex(inv):
            for key, ratio in (("--color-inverse-text", 4.5), ("--color-inverse-muted", 4.5), ("--color-inverse-accent", 3)):
                v = t.get(key, "")
                if is_hex(v) and contrast(v, inv) < ratio:
                    problems.append(f"{variant}: {key} {v} on title and section slides ({inv}) is {contrast(v, inv):.1f}:1 ({ratio}:1 wanted)")
        ac, acc = t.get("--color-accent", ""), t.get("--color-accent-contrast", "")
        if is_hex(ac) and is_hex(acc) and contrast(ac, acc) < 4.5:
            problems.append(f"{variant}: text on accent fills ({acc} on {ac}) is {contrast(ac, acc):.1f}:1")
        palette = [t.get(f"--chart-{i}", "") for i in range(1, 9)]
        palette = [p for p in palette if is_hex(p)]
        for n in _deck.palette_report(palette, bg):
            notes.append(f"{variant}: {n}")
    for kind, entry in (meta.get("backgrounds") or {}).items():
        if "picture" not in entry:
            continue
        pic = entry["picture"]
        if not pic.startswith(("linear-gradient", "data:")) and not (path / pic).is_file():
            problems.append(f"background picture missing for {kind} slides: {pic}")
        if entry.get("text") and entry.get("worst") and contrast(entry["text"], entry["worst"]) < 4.5:
            problems.append(f"{kind} slides: text {entry['text']} on the hardest part of the background ({entry['worst']}) is "
                            f"{contrast(entry['text'], entry['worst']):.1f}:1 (4.5:1 wanted)")
        if not entry.get("calm"):
            notes.append(f"{kind} slides: the background is busy, so a panel sits behind the text")
    faces = _deck.font_faces(css)
    have = {f["family"].lower() for f in faces}
    for f in faces:
        if f["url"] and not f["url"].startswith("data:") and not (path / f["url"]).is_file():
            problems.append(f"font file missing: {f['url']}")
    generic = {"serif", "sans-serif", "monospace", "system-ui", "ui-monospace", "ui-sans-serif", "ui-serif", "-apple-system", "cursive", "fantasy"}
    for role in ("display", "body", "mono"):
        stack = [x.strip().strip("\"'") for x in base.get(f"--font-{role}", defaults[f"--font-{role}"]).split(",")]
        first = stack[0]
        if first.lower() not in have and first.lower() not in generic and first.lower() not in BUNDLED:
            notes.append(f"--font-{role} starts with \"{first}\", which is not embedded: it shows only where installed")
    return problems, notes


def report(out: Path, notes: list[str]) -> int:
    problems, check_notes = check_theme(out)
    print(f"Theme written to {out}")
    meta = _deck.read_json(out / "theme.json", {}) or {}
    print(f"  variants: {', '.join(meta.get('variants', []))}   font files in the theme: {', '.join((meta.get('fonts') or {}).get('families', [])) or 'none'}"
          f"   logo: {'yes' if meta.get('logo') else 'no'}")
    all_bgs = meta.get("backgrounds") or {}
    pictures = {k: e for k, e in all_bgs.items() if "picture" in e}
    if pictures:
        print("  Backgrounds kept as pictures:")
        for kind, e in pictures.items():
            how = "a gradient, kept as code" if e["picture"].startswith("linear-gradient") else (
                "drawn by LibreOffice" if e.get("drawn_by_libreoffice") else "taken from the file")
            label = f'data-bg="{kind}"' if e.get("extra") else kind
            source = f' (the layout "{e["from"]}")' if e.get("extra") and e.get("from") else ""
            print(f"    {label:<8} {how}{source}; {e['ink']} text" + ("" if e["calm"] else "; panel behind the text"))
            print(f"             {e['description']}")
        size = sum(f.stat().st_size for f in (out / "backgrounds").glob("*")) if (out / "backgrounds").is_dir() else 0
        if size:
            print(f"    the pictures add {_deck.human_size(size)} to each deck built with this theme")
        print("    Look at each picture, then rewrite its \"description\" in theme.json in your own words:\n"
              "    say what must not be covered (a face, a product, a logo). It is what you read when composing a slide by hand.")
    flat_more = {k: e for k, e in all_bgs.items() if e.get("extra") and "flat" in e}
    if flat_more:
        print("  Flat backgrounds from other layouts: "
              + ", ".join(f'data-bg="{k}" ({e["flat"]}, the layout "{e.get("from", "")}")' for k, e in flat_more.items()))
    font_bytes = sum(f.stat().st_size for f in (out / "fonts").glob("*") if f.suffix.lower() in (".woff2", ".woff", ".ttf", ".otf")) if (out / "fonts").is_dir() else 0
    if font_bytes > 600 * 1024:
        notes = notes + [f"the font files total {_deck.human_size(font_bytes)}. A deck embeds the faces it uses, so decks in this theme will be "
                         "large. Variable fonts or .woff2 files with only the weights you need keep them small."]
    seen = set()
    already = any("is not embedded" in n for n in notes)
    check_notes = [n for n in check_notes if not (already and n.startswith("--font-"))]
    all_notes = [n for n in notes + check_notes if not (n in seen or seen.add(n))]
    if all_notes:
        print("  What to review (gaps and adjustments):")
        for n in all_notes:
            print(f"    - {n}")
    if problems:
        print("  Readability problems to fix in theme.css:")
        for p in problems:
            print(f"    ! {p}")
    return len(problems)


def background_sheet(out: Path, target: Path) -> bool:
    """One picture of every background with its text area outlined, for checking against the template."""
    meta = _deck.read_json(out / "theme.json", {}) or {}
    entries = [(k, e) for k, e in (meta.get("backgrounds") or {}).items() if "picture" in e]
    if not entries:
        return False
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    tw, th, pad, label = 640, 360, 18, 30
    cols = min(3, len(entries))
    rows = -(-len(entries) // cols)
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label + pad) + pad), (24, 26, 32))
    draw = ImageDraw.Draw(sheet)
    for i, (kind, e) in enumerate(entries):
        if e["picture"].startswith("linear-gradient"):
            im = _backgrounds.paint_gradient(e["picture"])
        else:
            im = Image.open(out / e["picture"]).convert("RGB")
        im = im.resize((tw, th))
        x, y = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + label + pad) + label
        sheet.paste(im, (x, y))
        body_line = (255, 255, 255) if e["ink"] == "light" else (20, 20, 20)
        areas = [(e.get("safe"), body_line)]
        if e.get("title_area") and e.get("body_area"):
            title_line = (255, 255, 255) if contrast(e["title_area"].get("text") or "#000000", "#FFFFFF") < 3 else (20, 20, 20)
            areas = [(e["title_area"]["box"], title_line), (e["body_area"], body_line)]
        for box, line in areas:
            if not box:
                continue
            sx, sy, sw, sh = (v / 3 for v in box)
            for grow in range(3):
                draw.rectangle((x + sx - grow, y + sy - grow, x + sx + sw + grow, y + sy + sh + grow), outline=line)
        name = f'data-bg="{kind}"' if e.get("extra") else kind
        boxes = "boxes = title area and text area" if len(areas) == 2 else "box = text area"
        draw.text((x, y - label + 8), f"{name}: {e['ink']} text" + ("" if e["calm"] else ", panel") + f"  ({boxes})", fill=(230, 232, 240))
    sheet.save(target)
    return True


def preview(out: Path, name: str) -> None:
    starter = _deck.SKILL_DIR / "template" / "starter.src.html"
    target = out / "preview" / f"{name}-sample.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    if background_sheet(out, target.parent / "backgrounds.png"):
        print(f"  backgrounds with their text areas: {target.parent / 'backgrounds.png'}  (compare with the template)")
    scripts = Path(__file__).resolve().parent
    r = subprocess.run([sys.executable, str(scripts / "build.py"), str(starter), "--theme", str(out), "-o", str(target), "--quiet"],
                       capture_output=True, text=True)
    if not target.is_file():
        print("  could not build the preview:\n" + r.stdout + r.stderr)
        return
    print(f"  sample deck in this theme: {target}")
    r = subprocess.run([sys.executable, str(scripts / "render.py"), str(target), "--out", str(target.parent / "light")],
                       capture_output=True, text=True)
    if r.returncode in (0, 1) and (target.parent / "light" / "contact.png").is_file():
        print(f"  contact sheet: {target.parent / 'light' / 'contact.png'}")
        for line in r.stdout.splitlines():
            if "LOOK" in line or "FAIL" in line:
                print("  " + line.strip())
        meta = _deck.read_json(out / "theme.json", {}) or {}
        for v in meta.get("variants", [])[1:]:
            subprocess.run([sys.executable, str(scripts / "render.py"), str(target), "--variant", v, "--out", str(target.parent / v)],
                           capture_output=True, text=True)
            if (target.parent / v / "contact.png").is_file():
                print(f"  contact sheet ({v}): {target.parent / v / 'contact.png'}")
    else:
        print("  (no browser available for screenshots; open the sample deck to review it)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create, check and list DynamicDecks themes.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--name", help="short name for the theme, for example acme")
        p.add_argument("--label", help="display name")
        p.add_argument("--fonts", help="folder of font files to embed (.ttf, .otf, .woff, .woff2)")
        p.add_argument("--font-license", help="license note for the embedded fonts")
        p.add_argument("--logo", help="logo file (.svg or .png)")
        p.add_argument("--logo-dark", help="logo file for dark slides")
        p.add_argument("--shape", choices=sorted(SHAPES), help="corner style (default soft)")
        p.add_argument("--title-align", choices=("left", "center", "right"),
                       help="align titles on every kind of slide (from-pptx: overrides what the template says)")
        p.add_argument("--bullet", choices=("dash", "dot", "square", "none"),
                       help="shape of first-level bullets (from-pptx: overrides the template; default elsewhere: dash)")
        p.add_argument("--slide-number", choices=("left", "center", "right", "off"),
                       help="where the slide number sits in the footer, or off to hide it (from-pptx: overrides the template)")
        p.add_argument("--footer-label", choices=("left", "center", "right", "off"),
                       help="where the deck's footer label sits, or off to hide it (from-pptx: overrides the template)")
        p.add_argument("--icons", help="icon set this theme should use")
        p.add_argument("--single-variant", action="store_true", help="do not derive the second (dark or light) variant")
        p.add_argument("--background", action="append", metavar="KIND=FILE",
                       help="a picture to use behind one kind of slide: content, title, section or closing (repeatable)")
        p.add_argument("--into", help="folder to write themes/<name>/ into (default: your library folder)")
        p.add_argument("--force", action="store_true", help="replace an existing theme of the same name")
        p.add_argument("--set-default", action="store_true", help="use this theme for new decks from now on")
        p.add_argument("--preview", action="store_true", help="build the sample deck in this theme and take screenshots")

    p1 = sub.add_parser("from-pptx", help="create a theme from a PowerPoint template")
    p1.add_argument("template", help=".pptx or .potx file")
    p1.add_argument("--backgrounds", choices=("auto", "always", "never"), default="auto",
                    help="auto keeps whatever the template draws behind a slide as a picture (the default; always means the "
                         "same); never gives a flat theme with a dark variant and the logo in the footer")
    p1.add_argument("--no-extra-backgrounds", action="store_true",
                    help="keep backgrounds for content, title, section and closing slides only, not for the template's other layouts")
    p1.add_argument("--master", metavar="NUMBER_OR_NAME",
                    help="which slide master to use when the file has several (default: the one most slides use)")
    common(p1)
    p2 = sub.add_parser("new", help="create a theme from a few brand values")
    common(p2)
    p2.add_argument("--bg", default="#FFFFFF", help="slide background")
    p2.add_argument("--text", default="#111111", help="main text color")
    p2.add_argument("--accent", required=True, help="primary brand color")
    p2.add_argument("--accent2", help="secondary brand color")
    p2.add_argument("--chart", help="comma-separated chart colors, in order")
    p2.add_argument("--inverse-bg", help="background of title and section slides (default: the accent)")
    p2.add_argument("--font-display", help="heading font family")
    p2.add_argument("--font-body", help="body font family")
    p2.add_argument("--font-mono", help="monospace font family")
    p3 = sub.add_parser("from-spec", help="create a theme from a JSON spec")
    p3.add_argument("spec", help="JSON file with name, colors, fonts, frame, shape, logo")
    common(p3)
    p4 = sub.add_parser("check", help="check a theme for missing tokens and hard-to-read colors")
    p4.add_argument("theme", help="theme name or folder")
    sub.add_parser("list", help="list installed themes")
    sub.add_parser("tokens", help="print every token with the built-in values")
    args = ap.parse_args()

    if args.cmd == "list":
        settings = _deck.load_settings()
        for name, path, origin in _deck.list_themes():
            meta = _deck.read_json(path / "theme.json", {}) or {}
            flag = "  (default for new decks)" if name == settings.get("theme") else ""
            print(f"{name:<16} {', '.join(meta.get('variants', [])):<14} {origin}{flag}")
            if meta.get("description"):
                print(f"{'':<16} {meta['description']}")
        return
    if args.cmd == "tokens":
        print(format_block(":root", _default_tokens()))
        return
    if args.cmd == "check":
        path = _deck.find_theme(args.theme)
        if not path:
            _deck.die(f"no theme named '{args.theme}'")
        problems, notes = check_theme(path)
        print(f"Theme '{path.name}' at {path}")
        for n in notes:
            print(f"  - {n}")
        for p in problems:
            print(f"  ! {p}")
        print("Result: " + (f"{len(problems)} readability problem(s) to fix." if problems else "complete and readable."))
        sys.exit(1 if problems else 0)

    notes: list[str] = []
    if args.cmd == "from-pptx":
        src = Path(args.template).expanduser()
        if not src.is_file():
            _deck.die(f"{src} does not exist")
        name = args.name or re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")
        args.name = name
        spec, notes = read_pptx(src, Path(tempfile.mkdtemp(prefix="dynamic-decks-")), args.backgrounds, args.master,
                                not args.no_extra_backgrounds)
    elif args.cmd == "from-spec":
        spec = _deck.read_json(Path(args.spec))
        if not isinstance(spec, dict):
            _deck.die(f"could not read a JSON object from {args.spec}")
    else:
        spec = {"colors": {"bg": args.bg, "text": args.text, "accent": args.accent, "accent2": args.accent2,
                           "chart": [c for c in (args.chart or "").split(",") if c.strip()] or None,
                           "inverse_bg": args.inverse_bg},
                "fonts": {"display": args.font_display, "body": args.font_body, "mono": args.font_mono}}
    spec.setdefault("name", args.name)
    for key in ("label", "shape", "icons", "font_license"):
        if getattr(args, key, None):
            spec[key] = getattr(args, key)
    out = write_theme(spec, args, notes)
    problems = report(out, notes)
    if args.preview:
        preview(out, out.name)
    if args.set_default:
        p = _deck.save_user_settings({"theme": out.name})
        print(f"  '{out.name}' is now the theme for new decks ({p})")
    else:
        print(f"  use it for one deck with:  <meta name=\"deck:theme\" content=\"{out.name}\">  or  build.py --theme {out.name}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
