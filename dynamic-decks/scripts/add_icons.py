#!/usr/bin/env python3
"""Import a folder of SVG icons as an icon set for DynamicDecks.

    python scripts/add_icons.py path/to/svgs --name acme
    python scripts/add_icons.py path/to/svgs --name acme --license "Company brand icons, internal use"
    python scripts/add_icons.py path/to/svgs --name acme --tags tags.json --set-default
    python scripts/add_icons.py --catalog lucide -o lucide-catalog.html

Each SVG is cleaned so it can be themed:
  * every color becomes currentColor, so icons take their color from the theme
  * scripts, styles, ids, gradients, embedded images and editor leftovers go
  * the canvas is normalized to a viewBox with no fixed width or height
The set is stored as one pack (icons.json) with a searchable index, a
set.json describing it, and a catalog.html to browse. It is kept apart from
the built-in set and from every other set you import.

By default the set is written to your library folder (~/.dynamic-decks, or
$DYNAMIC_DECKS_HOME), so updating the skill leaves it alone. Use --into to write
somewhere else, for example into a copy of the skill before repackaging it.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402

SHAPES = {"path", "circle", "ellipse", "line", "polyline", "polygon", "rect", "g"}
DROP_SILENT = {"title", "desc", "metadata", "style", "script", "namedview", "sodipodi:namedview"}
DROP_LOUD = {
    "foreignObject", "image", "text", "tspan", "use", "linearGradient", "radialGradient", "pattern",
    "filter", "mask", "clipPath", "defs", "symbol", "switch", "animate", "animateTransform",
    "animateMotion", "set", "a", "marker",
}
KEEP_ATTRS = {
    "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height", "points",
    "transform", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "fill-rule", "clip-rule",
    "opacity", "fill-opacity", "stroke-opacity", "vector-effect",
}
STYLE_PROPS = {
    "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "fill-rule", "clip-rule", "opacity", "fill-opacity", "stroke-opacity",
}
PAINT_KEEP = {"none", "currentcolor", "inherit"}


def local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def slug(name: str, strip_prefix: str = "") -> str:
    s = name
    if strip_prefix and s.lower().startswith(strip_prefix.lower()):
        s = s[len(strip_prefix):]
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "icon"


def num(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return v
    return str(int(f)) if f == int(f) else ("%.3f" % f).rstrip("0").rstrip(".")


class Cleaner:
    def __init__(self, two_tone: bool):
        self.two_tone = two_tone

    def attrs_of(self, el) -> dict[str, str]:
        raw = {local(k): v.strip() for k, v in el.attrib.items()}
        out = {}
        style = raw.pop("style", "")
        for decl in style.split(";"):
            if ":" in decl:
                p, v = decl.split(":", 1)
                p, v = p.strip().lower(), v.strip()
                if p in STYLE_PROPS and "!important" not in v:
                    raw[p] = v
        for k, v in raw.items():
            if k in KEEP_ATTRS and not k.startswith("on") and "javascript:" not in v.lower():
                out[k] = v
        return out

    def clean(self, text: str):
        """Return (body, viewBox, style, notes, stroke_width) or raise ValueError."""
        if "<!ENTITY" in text:
            raise ValueError("contains entity declarations")
        text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.I)
        text = re.sub(r"<\?xml[^>]*\?>", "", text)
        try:
            root = ET.fromstring(text.strip())
        except ET.ParseError as exc:
            raise ValueError(f"not valid SVG ({exc})")
        if local(root.tag) != "svg":
            raise ValueError("root element is not <svg>")

        notes: list[str] = []
        ra = self.attrs_of(root)
        vb = root.attrib.get("viewBox") or root.attrib.get("viewbox") or ""
        if vb:
            parts = re.split(r"[\s,]+", vb.strip())
            vb = " ".join(num(p) for p in parts) if len(parts) == 4 else ""
        if not vb:
            w = re.sub(r"[a-z%]+$", "", root.attrib.get("width", ""))
            h = re.sub(r"[a-z%]+$", "", root.attrib.get("height", ""))
            if w and h:
                vb = f"0 0 {num(w)} {num(h)}"
            else:
                raise ValueError("has no viewBox and no width/height")

        root_fill = ra.get("fill", "").lower()
        root_stroke = ra.get("stroke", "").lower()
        stroke_style = root_fill == "none" and root_stroke not in ("", "none")
        stroke_width = ra.get("stroke-width", "")

        colors: Counter = Counter()

        def collect(el):
            a = self.attrs_of(el)
            for key in ("fill", "stroke"):
                v = a.get(key, "").lower()
                if v and v not in PAINT_KEEP and not v.startswith("url("):
                    colors[v] += 1
            for c in el:
                collect(c)
        for c in root:
            collect(c)
        ordered = [c for c, _ in colors.most_common()]
        secondary = ordered[1] if self.two_tone and len(ordered) == 2 else None

        def paint(value: str):
            v = value.strip().lower()
            if v in ("none", "inherit"):
                return v, None
            if secondary and v == secondary:
                return "currentColor", "var(--icon-secondary, currentColor)"
            return "currentColor", None

        def build(el, depth=0) -> str:
            tag = local(el.tag)
            if tag in DROP_SILENT:
                return ""
            if tag in DROP_LOUD or tag not in SHAPES:
                notes.append(f"dropped <{tag}>")
                return ""
            a = self.attrs_of(el)
            styles = []
            for key in ("fill", "stroke"):
                if key in a:
                    val, extra = paint(a[key])
                    a[key] = val
                    if extra:
                        styles.append(f"{key}:{extra}")
            if (tag != "g" and a.get("fill") == "none" and a.get("stroke", "none") == "none"
                    and not stroke_style and root_stroke in ("", "none")):
                return ""  # an invisible spacer shape, common in exported icon files
            inner = "".join(build(c, depth + 1) for c in el)
            if tag == "g" and not inner:
                return ""
            attr_s = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in sorted(a.items()))
            if styles:
                attr_s += f' style="{";".join(styles)}"'
            if tag == "g" and not attr_s:
                return inner
            return f"<{tag}{attr_s}>{inner}</{tag}>" if inner else f"<{tag}{attr_s}/>"

        body = "".join(build(c) for c in root)
        if not body:
            raise ValueError("nothing left after cleaning")

        # Paint that sat on the root element moves to a wrapper only when the
        # icon does not fit the plain stroke or fill pattern.
        style = "stroke" if stroke_style else "fill"
        extra = {}
        if stroke_style:
            # The symbol wrapper supplies round caps and joins; keep the
            # icon's own when it was drawn differently.
            cap, join = ra.get("stroke-linecap", "butt"), ra.get("stroke-linejoin", "miter")
            if cap != "round":
                extra["stroke-linecap"] = cap
            if join != "round":
                extra["stroke-linejoin"] = join
        else:
            if root_stroke not in ("", "none"):
                extra["stroke"] = "currentColor"
                if stroke_width:
                    extra["stroke-width"] = stroke_width
            if root_fill == "none":
                extra["fill"] = "none"
            for k in ("stroke-linecap", "stroke-linejoin", "fill-rule", "clip-rule"):
                if k in ra:
                    extra[k] = ra[k]
            if extra.get("fill") == "none" and "stroke" not in extra:
                style = "mixed"
        if extra:
            attr_s = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in sorted(extra.items()))
            body = f"<g{attr_s}>{body}</g>"
            if "fill" in extra and "stroke" in extra:
                style = "mixed"
        if secondary:
            notes.append("two-tone")
        return body, vb, style, sorted(set(notes)), stroke_width


CATALOG_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__LABEL__ icons</title>
<style>
:root { color-scheme: light dark; --bg: #f7f8fc; --ink: #10184a; --muted: #5a6290; --line: #d3d8ea; --card: #ffffff; --accent: #2b3bf0; }
@media (prefers-color-scheme: dark) { :root { --bg: #0c1136; --ink: #f1f3ff; --muted: #b3bae6; --line: #2c3680; --card: #161d52; --accent: #8c97ff; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--line); padding: 16px 20px; }
h1 { margin: 0 0 4px; font-size: 20px; }
header p { margin: 0 0 12px; color: var(--muted); }
input { width: min(520px, 100%); padding: 10px 12px; font: inherit; color: inherit; background: var(--card); border: 1px solid var(--line); border-radius: 8px; }
input:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
main { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 10px; padding: 20px; }
button { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 16px 8px 12px; background: var(--card); color: inherit; border: 1px solid var(--line); border-radius: 10px; font: inherit; font-size: 12px; cursor: pointer; overflow-wrap: anywhere; text-align: center; }
button:hover, button:focus-visible { border-color: var(--accent); outline: none; }
button svg { width: 36px; height: 36px; stroke-width: __STROKE__; }
#empty { display: none; padding: 40px 20px; color: var(--muted); }
#said { color: var(--accent); margin-left: 10px; }
</style></head><body>
<header><h1>__LABEL__ icons</h1>
<p>__COUNT__ icons. Search by name or keyword. Click an icon to copy its name.<span id="said" role="status"></span></p>
<input id="q" type="search" placeholder="Search, for example: growth, team, money" autofocus></header>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">__SYMBOLS__</svg>
<main id="grid"></main><p id="empty">No icon matches that search.</p>
<script>
const ICONS = __DATA__;
const grid = document.getElementById('grid'), q = document.getElementById('q'), empty = document.getElementById('empty'), said = document.getElementById('said');
const cells = ICONS.map(([name, keys]) => {
  const b = document.createElement('button');
  b.type = 'button'; b.title = keys;
  b.innerHTML = '<svg aria-hidden="true"><use href="#icon-' + name + '"/></svg><span></span>';
  b.lastChild.textContent = name;
  b.addEventListener('click', () => {
    const done = () => { said.textContent = 'Copied ' + name; };
    if (navigator.clipboard) navigator.clipboard.writeText(name).then(done, () => { said.textContent = name; }); else said.textContent = name;
  });
  grid.appendChild(b);
  return [b, (name + ' ' + keys).toLowerCase()];
});
q.addEventListener('input', () => {
  const terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  let shown = 0;
  for (const [b, hay] of cells) { const ok = terms.every(t => hay.includes(t)); b.hidden = !ok; if (ok) shown++; }
  empty.style.display = shown ? 'none' : 'block';
});
</script></body></html>
"""


def write_catalog(icon_set: _deck.IconSet, out: Path) -> None:
    names = [n for n in icon_set.names()]
    symbols = "".join(icon_set.symbol(n) or "" for n in names)
    data = [[n, " ".join(icon_set.icons[n].get("k", []))] for n in names]
    page = (CATALOG_TEMPLATE
            .replace("__LABEL__", html.escape(icon_set.meta.get("label") or icon_set.name))
            .replace("__COUNT__", str(len(names)))
            .replace("__STROKE__", str(icon_set.meta.get("stroke_width") or 2))
            .replace("__SYMBOLS__", symbols)
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    out.write_text(page, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a folder of SVG icons as a DynamicDecks icon set.")
    ap.add_argument("source", nargs="?", help="folder of .svg files (searched recursively)")
    ap.add_argument("--name", help="short name for the set, for example acme")
    ap.add_argument("--label", help="display name (defaults to the name)")
    ap.add_argument("--license", default="", help="license or usage terms for these icons")
    ap.add_argument("--license-file", help="file holding the license text; copied next to the set")
    ap.add_argument("--attribution", default="", help="credit line embedded in decks that use the set")
    ap.add_argument("--source-url", default="", help="where the icons came from")
    ap.add_argument("--tags", help="JSON file mapping icon name to a list of keywords")
    ap.add_argument("--strip-prefix", default="", help="filename prefix to drop, for example ic_")
    ap.add_argument("--two-tone", action="store_true", help="keep a second color as --icon-secondary where an icon uses exactly two")
    ap.add_argument("--into", help="folder to write icons/<name>/ into (default: your library folder)")
    ap.add_argument("--set-default", action="store_true", help="make this the active icon set for new decks")
    ap.add_argument("--no-catalog", action="store_true", help="skip writing catalog.html")
    ap.add_argument("--catalog", metavar="SET", help="only write a catalog page for an installed set")
    ap.add_argument("-o", "--output", help="with --catalog: where to write the page")
    args = ap.parse_args()

    if args.catalog:
        s = _deck.load_icon_set(args.catalog)
        if not s:
            _deck.die(f"no icon set named '{args.catalog}'")
        out = Path(args.output or f"{s.name}-catalog.html")
        write_catalog(s, out)
        print(f"Catalog for '{s.name}' ({len(s.icons)} icons) written to {out}")
        return

    if not args.source or not args.name:
        ap.error("give a source folder and --name")
    src = Path(args.source).expanduser()
    if not src.is_dir():
        _deck.die(f"{src} is not a folder")
    name = slug(args.name)
    files = sorted(src.rglob("*.svg"))
    if not files:
        _deck.die(f"no .svg files under {src}")

    tags = {}
    if args.tags:
        tags = _deck.read_json(Path(args.tags), {}) or {}

    cleaner = Cleaner(args.two_tone)
    icons: dict[str, dict] = {}
    by_hash: dict[str, str] = {}
    styles: Counter = Counter()
    viewboxes: Counter = Counter()
    widths: Counter = Counter()
    skipped: list[str] = []
    noted: dict[str, list[str]] = {}
    pending = []

    for f in files:
        try:
            body, vb, style, notes, sw = cleaner.clean(f.read_text(encoding="utf-8", errors="replace"))
        except ValueError as exc:
            skipped.append(f"{f.name}: {exc}")
            continue
        n = slug(f.stem, args.strip_prefix)
        base, k = n, 2
        while n in icons or any(p[0] == n for p in pending):
            n = f"{base}-{k}"
            k += 1
        styles[style] += 1
        viewboxes[vb] += 1
        if sw:
            widths[sw] += 1
        if notes:
            noted[n] = notes
        pending.append((n, body, vb, style, f.stem))

    if not pending:
        _deck.die("no usable icons found:\n  " + "\n  ".join(skipped[:20]))

    set_style = styles.most_common(1)[0][0]
    set_vb = viewboxes.most_common(1)[0][0]
    for n, body, vb, style, stem in pending:
        keys = []
        for key in (n, stem):
            for t in tags.get(key, []) or []:
                t = str(t).strip().lower()
                if t and t not in keys:
                    keys.append(t)
        digest = hashlib.sha1(f"{style}|{vb}|{body}".encode()).hexdigest()
        if digest in by_hash:
            entry = {"a": by_hash[digest]}
        else:
            by_hash[digest] = n
            entry = {"b": body}
            if vb != set_vb:
                entry["v"] = vb
            if style != set_style:
                entry["s"] = style
        if keys:
            entry["k"] = keys
        icons[n] = entry

    base = Path(args.into).expanduser() if args.into else _deck.library_dir()
    out = base / "icons" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "icons.json").write_text(json.dumps(icons, separators=(",", ":"), sort_keys=True), encoding="utf-8")

    license_text = args.license
    if args.license_file:
        lf = Path(args.license_file)
        (out / "LICENSE").write_text(lf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        license_text = license_text or f"See LICENSE in {out}"
    aliases = sum(1 for e in icons.values() if "a" in e)
    nonsquare = sorted({vb for vb in viewboxes if len(vb.split()) == 4 and vb.split()[2] != vb.split()[3]})
    meta = {
        "name": name,
        "label": args.label or args.name,
        "style": set_style,
        "viewBox": set_vb,
        "count": len(icons),
        "aliases": aliases,
        "stroke_width": widths.most_common(1)[0][0] if widths else "",
        "license": license_text,
        "attribution": args.attribution,
        "source": args.source_url,
        "imported": datetime.date.today().isoformat(),
    }
    (out / "set.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    icon_set = _deck.IconSet(out)
    if not args.no_catalog:
        write_catalog(icon_set, out / "catalog.html")

    print(f"Imported {len(icons)} icons as set '{name}' into {out}")
    print(f"  style: {set_style}   canvas: {set_vb}" + (f"   native stroke width: {meta['stroke_width']}" if meta["stroke_width"] else ""))
    if aliases:
        print(f"  {aliases} files were identical to another icon and are stored as aliases")
    mixed = {s: c for s, c in styles.items() if s != set_style}
    if mixed:
        print("  mixed styles: " + ", ".join(f"{c} {s}" for s, c in mixed.items()) + f" (most are {set_style}); browse the catalog for mismatches")
    if len(viewboxes) > 1:
        print(f"  {len(viewboxes)} different canvas sizes; each icon keeps its own")
    if nonsquare:
        print(f"  non-square canvases: {', '.join(nonsquare[:4])}")
    if noted:
        dropped = Counter(x for v in noted.values() for x in v if x.startswith("dropped"))
        if dropped:
            print("  removed while cleaning: " + ", ".join(f"{k.replace('dropped ', '')} x{v}" for k, v in dropped.most_common()))
            sample = [n for n, v in noted.items() if any(x.startswith("dropped") for x in v)][:8]
            print("    check these in the catalog, they may look different: " + ", ".join(sample))
    if skipped:
        print(f"  skipped {len(skipped)} files:")
        for s in skipped[:10]:
            print(f"    {s}")
    if not args.no_catalog:
        print(f"  catalog: {out / 'catalog.html'}")
    if not license_text:
        print("  no license recorded. Icons get embedded in every deck you share, so confirm you may redistribute them.")
    if args.set_default:
        p = _deck.save_user_settings({"icons": name})
        print(f"  '{name}' is now the active icon set ({p})")
    else:
        print(f"  use it for one deck with:  <meta name=\"deck:icons\" content=\"{name}\">  or  build.py --icons {name}")


if __name__ == "__main__":
    main()
