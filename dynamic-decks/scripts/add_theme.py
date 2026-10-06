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
one. `new` builds a theme from a handful of brand values (use it for a brand
guide or a description). Both expand those few values into the full token set,
derive the second variant (dark or light), and report what they could not
take from the source, so you know what to review.

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
import _deck  # noqa: E402
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


def read_pptx(path: Path, extract_to: Path | None = None) -> tuple[dict, list[str]]:
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

    master_part = next((t for typ, t in _rels(z, "ppt/presentation.xml").values() if typ == "slideMaster"), None)
    if not master_part or master_part not in names:
        _deck.die("could not find a slide master in the template")
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
    if bg_el is not None:
        bg = resolve(bg_el.find("p:bgPr/a:solidFill", NS)) or resolve(bg_el.find("p:bgRef", NS))
        if bg is None and bg_el.find("p:bgPr", NS) is not None and bg_el.find("p:bgPr/a:solidFill", NS) is None:
            notes.append("the master background is a picture or gradient; a flat background color was used instead")
    bg = bg or scheme.get(cmap.get("bg1", "lt1"), "#FFFFFF")
    text = scheme.get(cmap.get("tx1", "dk1"), "#000000")
    if contrast(bg, text) < 4.5:
        notes.append(f"the template's text {text} on its background {bg} has low contrast; check the result")

    fonts = {}
    fs = theme.find("a:themeElements/a:fontScheme", NS)
    if fs is not None:
        for role, tag in (("display", "a:majorFont"), ("body", "a:minorFont")):
            latin = fs.find(f"{tag}/a:latin", NS)
            if latin is not None and latin.get("typeface"):
                fonts[role] = latin.get("typeface")

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
    if tree is not None and extract_to is not None:
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
        inv = ensure_contrast(inv, "#FFFFFF", 4.5, prefer="darker")
        inv_text = "#FFFFFF"
    else:
        inv_text = text if luminance(text) < 0.2 else "#111111"
        inv = ensure_contrast(inv, inv_text, 4.5, prefer="lighter")
    t["--color-inverse-bg"] = inv
    t["--color-inverse-text"] = inv_text
    t["--color-inverse-muted"] = ensure_contrast(mix(inv_text, inv, 0.22), inv, 4.5,
                                                prefer="lighter" if inv_text == "#FFFFFF" else "darker")
    t["--color-inverse-border"] = mix(inv, inv_text, 0.28)
    t["--color-inverse-surface"] = mix(inv, inv_text, 0.12)
    ia = ensure_contrast(accent2 or mix(inv_text, inv, 0.3), inv, 4.5, prefer="lighter" if inv_text == "#FFFFFF" else "darker")
    if contrast(ia, inv) < 4.5 or _deck.delta_e(ia, inv_text) < 6:
        ia = t["--color-inverse-muted"]
    t["--color-inverse-accent"] = ia
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
    ("Frame: where the title sits, the margins, the footer", r"--(frame|title|eyebrow|footer)-"),
    ("Shape", r"--(radius|stroke|shadow)-"),
    ("Icons", r"--icon-"),
    ("Logo (set by the build when the theme folder has a logo file)", r"--logo-"),
    ("Motion", r"--(dur|stagger|ease)"),
    ("Engine chrome", r"--progress-"),
]


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

    c = spec.get("colors", {})
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
    if frame.get("title_weight"):
        tokens["--title-weight"] = str(frame["title_weight"])
        tokens["--weight-display"] = str(frame["title_weight"])
    tokens.update(SHAPES.get(spec.get("shape") or "soft", SHAPES["soft"]))

    blocks = [format_block(":root", tokens)]
    variants = [base_mode]
    if spec.get("dark", True) and not getattr(args, "single_variant", False):
        nbg, ntext, nacc, nacc2, nchart = other_variant_seeds(bg, text, accent, accent2, chart, other)
        vt = color_tokens(nbg, ntext, nacc, nacc2, nchart, other, notes, inverse_bg, None)
        if title is not None:
            vt["--title-color"] = "var(--color-text)"
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
    unknown = [k for k in base if k not in defaults]
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


def preview(out: Path, name: str) -> None:
    starter = _deck.SKILL_DIR / "template" / "starter.src.html"
    target = out / "preview" / f"{name}-sample.html"
    target.parent.mkdir(parents=True, exist_ok=True)
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
        p.add_argument("--icons", help="icon set this theme should use")
        p.add_argument("--single-variant", action="store_true", help="do not derive the second (dark or light) variant")
        p.add_argument("--into", help="folder to write themes/<name>/ into (default: your library folder)")
        p.add_argument("--force", action="store_true", help="replace an existing theme of the same name")
        p.add_argument("--set-default", action="store_true", help="use this theme for new decks from now on")
        p.add_argument("--preview", action="store_true", help="build the sample deck in this theme and take screenshots")

    p1 = sub.add_parser("from-pptx", help="create a theme from a PowerPoint template")
    p1.add_argument("template", help=".pptx or .potx file")
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
        spec, notes = read_pptx(src, Path(tempfile.mkdtemp(prefix="dynamic-decks-")))
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
