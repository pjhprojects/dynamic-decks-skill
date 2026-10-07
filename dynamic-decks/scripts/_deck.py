"""Shared helpers for the DynamicDecks scripts.

Locations
---------
Built-in themes and icon sets ship inside the skill folder. Anything a user
adds lives in a separate "library" folder so that updating the skill never
touches it:

    $DYNAMIC_DECKS_HOME            if set
    ~/.dynamic-decks               otherwise

The project was first called html-deck. $HTML_DECK_HOME, and an existing
~/.html-deck when ~/.dynamic-decks does not exist yet, are still honored.

Both places use the same layout (themes/<name>/, icons/<name>/, settings.json)
and the library wins when a name exists in both.
"""
from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

VERSION = "1.2.0"
COPYRIGHT = "Copyright (c) 2026 The DynamicDecks authors"
LICENSE_NAME = "MIT License"
SKILL_DIR = Path(__file__).resolve().parent.parent
STAGE_W, STAGE_H = 1920, 1080

LAYOUTS = [
    "title", "section", "bullets", "two-column", "big-number", "stats", "cards",
    "chart", "image", "quote", "diagram", "table", "timeline", "closing", "full-bleed",
]

DEFAULT_SETTINGS = {
    "theme": "default",
    "variant": "",
    "icons": "",
    "icon_fallback": "none",
    "notes": "required",
    "compress_images": True,
    "max_image_px": 2400,
    "image_quality": 82,
}


# --------------------------------------------------------------------------
# Locations and settings
# --------------------------------------------------------------------------
def library_dir() -> Path:
    env = os.environ.get("DYNAMIC_DECKS_HOME") or os.environ.get("HTML_DECK_HOME")
    if env:
        return Path(env).expanduser()
    new, old = Path.home() / ".dynamic-decks", Path.home() / ".html-deck"
    # the project was first called html-deck; keep using a library made under that name
    return old if old.is_dir() and not new.is_dir() else new


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    for p in (SKILL_DIR / "settings.json", library_dir() / "settings.json"):
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                warn(f"could not read {p}: {exc}")
                continue
            settings.update({k: v for k, v in data.items() if not k.startswith("_")})
    return settings


def save_user_settings(changes: dict) -> Path:
    p = library_dir() / "settings.json"
    data = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data.update(changes)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def _find(kind: str, name: str, marker: str) -> Path | None:
    """Resolve a theme or icon set by name, or by a path to its folder."""
    if not name:
        return None
    direct = Path(name).expanduser()
    if direct.is_dir() and (direct / marker).is_file():
        return direct.resolve()
    for base in (library_dir(), SKILL_DIR):
        p = base / kind / name
        if (p / marker).is_file():
            return p
    return None


def find_theme(name: str) -> Path | None:
    return _find("themes", name, "theme.css")


def find_icon_set(name: str) -> Path | None:
    return _find("icons", name, "icons.json")


def _list(kind: str, marker: str) -> list[tuple[str, Path, str]]:
    out, seen = [], set()
    for base, origin in ((library_dir(), "yours"), (SKILL_DIR, "built-in")):
        d = base / kind
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.name in seen or not (p / marker).is_file():
                continue
            seen.add(p.name)
            out.append((p.name, p, origin))
    return out


def list_themes():
    return _list("themes", "theme.css")


def list_icon_sets():
    return _list("icons", "icons.json")


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------
# Icon sets
# --------------------------------------------------------------------------
class IconSet:
    def __init__(self, path: Path):
        self.path = path
        self.meta = read_json(path / "set.json", {}) or {}
        self.icons = read_json(path / "icons.json", {}) or {}
        self.name = self.meta.get("name") or path.name
        self.style = self.meta.get("style", "stroke")
        self.viewbox = self.meta.get("viewBox", "0 0 24 24")

    def resolve(self, name: str):
        entry = self.icons.get(name)
        hops = 0
        while entry and "a" in entry and hops < 5:
            entry = self.icons.get(entry["a"])
            hops += 1
        return entry

    def has(self, name: str) -> bool:
        return self.resolve(name) is not None

    def symbol(self, name: str) -> str | None:
        entry = self.resolve(name)
        if not entry:
            return None
        style = entry.get("s", self.style)
        vb = entry.get("v", self.viewbox)
        if style == "stroke":
            wrap = '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">'
        elif style == "fill":
            wrap = '<g fill="currentColor" stroke="none">'
        else:
            wrap = "<g>"
        return f'<symbol id="icon-{name}" viewBox="{vb}">{wrap}{entry["b"]}</g></symbol>'

    def names(self) -> list[str]:
        return sorted(self.icons)


def load_icon_set(name: str) -> IconSet | None:
    p = find_icon_set(name)
    return IconSet(p) if p else None


# --------------------------------------------------------------------------
# CSS helpers
# --------------------------------------------------------------------------
def strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def css_blocks(css: str):
    """Yield (prelude, body) for each top-level rule in a stylesheet."""
    css = strip_css_comments(css)
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        semi = css.find(";", i, j)
        if semi >= 0 and "{" not in css[i:semi]:
            # a statement at-rule such as @import ...; skip it
            i = semi + 1
            continue
        depth, k = 1, j + 1
        while k < n and depth:
            c = css[k]
            if c in "\"'":
                q = c
                k += 1
                while k < n and css[k] != q:
                    k += 2 if css[k] == "\\" else 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            k += 1
        yield css[i:j].strip(), css[j + 1:k - 1]
        i = k


def split_declarations(body: str) -> list[tuple[str, str]]:
    """Split a rule body into (property, value) pairs, ignoring nested rules."""
    out, depth, paren, cur = [], 0, 0, []
    quote = ""
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == "(":
            paren += 1
            cur.append(ch)
        elif ch == ")":
            paren = max(0, paren - 1)
            cur.append(ch)
        elif ch == "{":
            depth += 1
            cur = []
        elif ch == "}":
            depth = max(0, depth - 1)
            cur = []
        elif ch == ";" and depth == 0 and paren == 0:
            decl = "".join(cur).strip()
            cur = []
            if ":" in decl:
                prop, val = decl.split(":", 1)
                out.append((prop.strip(), val.strip()))
        else:
            cur.append(ch)
    decl = "".join(cur).strip()
    if depth == 0 and ":" in decl:
        prop, val = decl.split(":", 1)
        out.append((prop.strip(), val.strip()))
    return out


def theme_tokens(css: str) -> dict[str, dict[str, str]]:
    """Tokens per variant. '' is the base block (:root)."""
    out: dict[str, dict[str, str]] = {}
    for prelude, body in css_blocks(css):
        if prelude.startswith("@") or ":root" not in prelude:
            continue
        m = re.search(r'data-variant\s*=\s*["\']?([\w-]+)', prelude)
        variant = m.group(1) if m else ""
        tokens = out.setdefault(variant, {})
        for prop, val in split_declarations(body):
            if prop.startswith("--"):
                tokens[prop] = val
    return out


def font_faces(css: str) -> list[dict]:
    """Parse @font-face rules: family, style, url, unicode ranges, raw text."""
    faces = []
    for m in re.finditer(r"@font-face\s*\{(.*?)\}", strip_css_comments(css), flags=re.S):
        body = m.group(1)
        decl = dict((p.lower(), v) for p, v in split_declarations(body))
        family = decl.get("font-family", "").strip().strip("\"'")
        url = re.search(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', decl.get("src", ""))
        faces.append({
            "family": family,
            "style": decl.get("font-style", "normal").strip(),
            "url": url.group(1) if url else "",
            "ranges": parse_unicode_range(decl.get("unicode-range", "")),
            "raw": m.group(0),
        })
    return faces


def parse_unicode_range(value: str) -> list[tuple[int, int]]:
    ranges = []
    for part in value.split(","):
        part = part.strip().upper()
        if not part.startswith("U+"):
            continue
        part = part[2:]
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                ranges.append((int(a, 16), int(b, 16)))
            elif "?" in part:
                ranges.append((int(part.replace("?", "0"), 16), int(part.replace("?", "F"), 16)))
            else:
                ranges.append((int(part, 16), int(part, 16)))
        except ValueError:
            continue
    return ranges


def data_uri(path: Path, mime: str | None = None) -> str:
    mime = mime or guess_mime(path)
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def bytes_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    table = {
        ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
        ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg",
    }
    return table.get(ext) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


# --------------------------------------------------------------------------
# Deck source parsing
# --------------------------------------------------------------------------
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

MARK = {
    "engine_css": ("<!-- deck:engine-css -->", "<!-- /deck:engine-css -->"),
    "theme": ("<!-- deck:theme -->", "<!-- /deck:theme -->"),
    "layouts": ("<!-- deck:layouts -->", "<!-- /deck:layouts -->"),
    "custom": ("<!-- deck:custom -->", "<!-- /deck:custom -->"),
    "icons": ("<!-- deck:icons -->", "<!-- /deck:icons -->"),
    "content": ("<!-- deck:content -->", "<!-- /deck:content -->"),
    "engine_js": ("<!-- deck:engine-js -->", "<!-- /deck:engine-js -->"),
}


def between(text: str, key: str) -> str | None:
    a, b = MARK[key]
    i = text.find(a)
    if i < 0:
        return None
    j = text.find(b, i)
    if j < 0:
        return None
    return text[i + len(a):j]


class Source:
    """The parts of a deck source (or of a built deck) that belong to the deck
    itself: title, deck:* metas, deck-wide styles and scripts, and the slides."""

    def __init__(self, text: str, path: Path | None = None):
        self.text = text
        self.path = path
        self.is_built = MARK["content"][0] in text
        # commented-out markup (examples in the starter) must not count
        clean = re.sub(r"<!--(?!\s*/?deck:).*?-->", "", text, flags=re.S)
        self.raw = text
        text = clean
        m = re.search(r"<html\b([^>]*)>", text, flags=re.I)
        self.html_attrs = _attrs(m.group(1)) if m else {}
        self.lang = self.html_attrs.get("lang", "en")
        m = re.search(r"<title\b[^>]*>(.*?)</title>", text, flags=re.I | re.S)
        self.title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        self.metas: dict[str, str] = {}
        for m in re.finditer(r"<meta\b([^>]*)>", text, flags=re.I):
            a = _attrs(m.group(1))
            if a.get("name"):
                self.metas[a["name"]] = a.get("content", "")

        head_region = text
        custom = between(text, "custom") if self.is_built else None
        if custom is not None:
            head_region = custom
        else:
            main_at = re.search(r"<main\b", text, flags=re.I)
            head_region = text[:main_at.start()] if main_at else text
        self.deck_styles = [m.group(2) for m in re.finditer(
            r"<style\b([^>]*\bdata-deck\b[^>]*)>(.*?)</style>", head_region, flags=re.I | re.S)]
        self.deck_scripts = [m.group(2) for m in re.finditer(
            r"<script\b([^>]*\bdata-deck\b[^>]*)>(.*?)</script>", head_region, flags=re.I | re.S)]

        content = between(text, "content") if self.is_built else None
        if content is not None:
            self.main = content.strip()
        else:
            m = re.search(r"<main\b[^>]*>.*</main>", text, flags=re.I | re.S)
            if m:
                self.main = m.group(0)
            elif re.search(r"<section\b[^>]*class=[\"'][^\"']*\bslide\b", text, flags=re.I):
                body = re.search(r"<body\b[^>]*>(.*)</body>", text, flags=re.I | re.S)
                inner = body.group(1) if body else text
                first = re.search(r"<section\b", inner, flags=re.I)
                self.main = '<main class="deck">\n' + inner[first.start():].strip() + "\n</main>"
            else:
                self.main = ""

    def meta(self, key: str, default: str = "") -> str:
        return self.metas.get("deck:" + key, default)


def _attrs(s: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+)))?', s):
        out[m.group(1).lower()] = next((g for g in m.groups()[1:] if g is not None), "")
    return out


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "line")

    def __init__(self, tag, attrs, parent, line):
        self.tag, self.attrs, self.parent, self.line = tag, attrs, parent, line
        self.children: list[Node] = []
        self.text: list[str] = []

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def closest(self, pred):
        n = self
        while n is not None:
            if pred(n):
                return n
            n = n.parent
        return None

    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def all_text(self) -> str:
        parts = list(self.text)
        for c in self.children:
            if c.tag not in ("style", "script"):
                parts.append(c.all_text())
        return " ".join(parts)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None, 0)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur, self.getpos()[0])
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur, self.getpos()[0])
        self.cur.children.append(node)

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.text.append(data)


def parse_tree(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    t.close()
    return t.root


def slides_of(tree: Node) -> list[Node]:
    main = next((n for n in tree.walk() if n.tag == "main"), tree)
    return [c for c in main.children if c.tag == "section" and "slide" in c.classes()]


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------
def parse_hex(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def luminance(h: str) -> float:
    r, g, b = (_lin(c) for c in parse_hex(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """Blend b into a by t (0..1) in sRGB."""
    ra, rb = parse_hex(a), parse_hex(b)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _lin_rgb(h: str):
    return [_lin(c) for c in parse_hex(h)]


def oklab(h: str, lin=None):
    r, g, b = lin if lin is not None else _lin_rgb(h)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def from_oklab(L, a, b) -> str:
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return to_hex((_gam(r), _gam(g), _gam(bl)))


def shift_lightness(h: str, target_l: float) -> str:
    L, a, b = oklab(h)
    return from_oklab(max(0.0, min(1.0, target_l)), a, b)


def ensure_contrast(color: str, against: str, ratio: float, prefer: str = "auto") -> str:
    """Move a color's lightness (keeping its hue) until it clears `ratio`."""
    if contrast(color, against) >= ratio:
        return color.upper() if color.startswith("#") else color
    L = oklab(color)[0]
    darker = luminance(against) > 0.4 if prefer == "auto" else prefer == "darker"
    step = -0.01 if darker else 0.01
    best = color
    for _ in range(100):
        L += step
        if L <= 0 or L >= 1:
            break
        best = shift_lightness(color, L)
        if contrast(best, against) >= ratio:
            return best
    return best


_MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
}


def delta_e(a: str, b: str, cvd: str | None = None) -> float:
    """OKLab distance x100, optionally under simulated color-vision deficiency."""
    def lab(h):
        lin = _lin_rgb(h)
        if cvd:
            mtx = _MACHADO[cvd]
            lin = [max(0.0, min(1.0, sum(mtx[r][c] * lin[c] for c in range(3)))) for r in range(3)]
        return oklab(h, lin)
    x, y = lab(a), lab(b)
    return 100 * math.sqrt(sum((p - q) ** 2 for p, q in zip(x, y)))


def palette_report(colors: list[str], surface: str) -> list[str]:
    """Plain-language problems with a categorical chart palette."""
    notes = []
    for i, c in enumerate(colors, 1):
        cr = contrast(c, surface)
        if cr < 3:
            notes.append(f"chart-{i} {c} has {cr:.1f}:1 contrast on the background (3:1 wanted): label those marks directly")
    for i in range(len(colors) - 1):
        a, b = colors[i], colors[i + 1]
        if delta_e(a, b) < 15:
            notes.append(f"chart-{i + 1} {a} and chart-{i + 2} {b} look too alike side by side")
        elif min(delta_e(a, b, "protan"), delta_e(a, b, "deutan")) < 6:
            notes.append(f"chart-{i + 1} {a} and chart-{i + 2} {b} are hard to tell apart with color-blindness")
    return notes


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.2f} MB"
