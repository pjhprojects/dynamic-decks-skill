#!/usr/bin/env python3
"""Assemble a deck source into one self-contained HTML file.

    python scripts/build.py talk.src.html                 -> talk.html
    python scripts/build.py talk.src.html -o out/talk.html
    python scripts/build.py talk.src.html --theme acme --variant dark
    python scripts/build.py talk.html --theme acme -o talk-acme.html   (re-theme a built deck)

The output inlines the engine, the theme (with only the fonts the deck needs),
the layouts, the icons the deck uses and every image. It makes no network
requests. The input may be a deck source or a deck that was built earlier.

The delivery checks (scripts/check.py) run after the build; a failed check
makes this script exit with status 1 even though the file was written.
"""
from __future__ import annotations

import argparse
import difflib
import html
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402
from _deck import MARK  # noqa: E402

REMOTE = re.compile(r"^(?:https?:)?//", re.I)
MONO_USE = re.compile(r"<(?:code|pre|kbd|samp)\b|font-mono|--font-mono", re.I)
ITALIC_USE = re.compile(r"<(?:em|i|cite|dfn|var)\b|font-style\s*:\s*italic|\bitalic\b", re.I)


class Builder:
    def __init__(self, args):
        self.args = args
        self.settings = _deck.load_settings()
        self.notes: list[str] = []
        self.errors: list[str] = []
        self._image_cache: dict[str, str] = {}
        self.image_bytes = 0
        self.image_count = 0

    # ---- assets ---------------------------------------------------------
    def embed_file(self, ref: str, base: Path, what: str) -> str:
        """Turn a local file reference into a data URI."""
        ref = ref.strip()
        if not ref or ref.startswith(("data:", "#", "blob:", "about:")) or ref.startswith("var("):
            return ref
        if REMOTE.match(ref):
            if not self.args.allow_remote:
                self.errors.append(
                    f"{what} loads {ref} from the internet. Download it and reference the local file, "
                    "so the deck works offline.")
            return ref
        clean = ref.split("#", 1)[0].split("?", 1)[0]
        path = (base / html.unescape(clean)).resolve()
        key = str(path)
        if key in self._image_cache:
            return self._image_cache[key]
        if not path.is_file():
            self.errors.append(f"{what} points to a file that does not exist: {ref}")
            return ref
        uri = self._encode(path)
        self._image_cache[key] = uri
        return uri

    def _encode(self, path: Path) -> str:
        ext = path.suffix.lower()
        raw = path.read_bytes()
        data, mime = raw, _deck.guess_mime(path)
        compress = self.settings.get("compress_images", True) and not self.args.no_compress
        if compress and ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(raw))
                if getattr(im, "is_animated", False):
                    raise ValueError("animated")
                cap = int(self.settings.get("max_image_px", 2400))
                if max(im.size) > cap:
                    im.thumbnail((cap, cap), Image.LANCZOS)
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
                buf = io.BytesIO()
                im.save(buf, "WEBP", quality=int(self.settings.get("image_quality", 82)), method=4)
                if buf.tell() < len(raw):
                    data, mime = buf.getvalue(), "image/webp"
            except Exception:  # Pillow missing or unreadable image: embed as is
                data, mime = raw, _deck.guess_mime(path)
        if mime.startswith(("image/", "video/", "audio/")):
            self.image_count += 1
            self.image_bytes += len(data)
        return _deck.bytes_data_uri(data, mime)

    def embed_css_urls(self, css: str, base: Path, what: str) -> str:
        def repl(m):
            new = self.embed_file(m.group(2), base, what)
            # leave untouched anything that was not embedded, such as url(#marker);
            # base64 data URIs need no quotes, which keeps them safe inside attributes
            return m.group(0) if new == m.group(2).strip() else "url(" + new + ")"
        return re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)", repl, css)

    def prune_backgrounds(self, css: str, body: str, theme_name: str) -> str:
        """Leave out the background pictures this deck never shows, and check the ones it asks for.

        A theme declares each picture once (--bg-title: url(...)) and its rules
        use it by name, so a picture is dropped by setting its declaration to
        none. Which kinds of slide a picture serves is read from the selectors
        of the rules that use it.
        """
        asked = set(re.findall(r'<section\b[^>]*\bdata-bg="([^"]+)"', body))
        layouts = set(re.findall(r'<section\b[^>]*\bdata-layout="([^"]+)"', body))
        offered: set[str] = set()                # every name a slide may put in data-bg in this theme
        serves: dict[str, set[str]] = {}         # picture token -> kinds of slide it is behind
        root_uses: set[str] = set()
        declared = set(re.findall(r"(--bg-(?!image\b|panel\b)[\w-]+)\s*:\s*url\(", css))
        gone = set(re.findall(r"(--bg-(?!image\b|panel\b)[\w-]+)\s*:\s*none\b", css))
        for selector, block in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            names = set(re.findall(r'data-bg="([^"]+)"', selector))
            offered |= names
            refs = set(re.findall(r"var\((--bg-[\w-]+)\)", block)) & (declared | gone)
            if not refs:
                continue
            if not names and "data-layout" not in selector:
                root_uses |= refs                 # the content background, on :root
            kinds = names | set(re.findall(r'data-layout="([^"]+)"', selector))
            for ref in refs:
                serves.setdefault(ref, set()).update(kinds)
        used = asked | (layouts & {"title", "section", "closing"})
        dropped = sorted(t for t in declared if t not in root_uses and not (serves.get(t, set()) & used))
        for token in dropped:
            css = re.sub(re.escape(token) + r"\s*:\s*url\([^)]*\)", token + ": none", css)
        if dropped:
            self.notes.append(f"{len(dropped)} background picture(s) of the theme are not used by this deck and were left out: "
                              + ", ".join(t[5:] for t in dropped))
        known = offered | {"none", "title", "section", "closing"}
        for name in sorted(asked - known):
            self.notes.append(f'data-bg="{name}" is not a background in the theme \'{theme_name}\''
                              + (f" (it has: {', '.join(sorted(offered | {'none'}))})" if offered else " (it has no picture backgrounds)")
                              + "; that slide gets the ordinary background")
        missing = sorted(n for n in asked if any(n in kinds for t, kinds in serves.items() if t in gone))
        for name in missing:
            self.notes.append(f'data-bg="{name}": the picture for it was left out of the theme inside this deck when it was built. '
                              "Rebuild with the theme installed (build.py --theme) to bring it back.")
        return css

    # ---- theme ----------------------------------------------------------
    def theme_css(self, theme_dir: Path, default_dir: Path, text_chars: set[int], body: str) -> tuple[str, dict]:
        css = (theme_dir / "theme.css").read_text(encoding="utf-8")
        meta = _deck.read_json(theme_dir / "theme.json", {}) or {}
        tokens = _deck.theme_tokens(css)
        base_tokens = dict(tokens.get("", {}))

        # T8: any token the theme leaves out falls back to the default theme
        fallback_css, missing = "", []
        default_css = ""
        if theme_dir != default_dir and (default_dir / "theme.css").is_file():
            default_css = (default_dir / "theme.css").read_text(encoding="utf-8")
            default_base = _deck.theme_tokens(default_css).get("", {})
            missing = [k for k in default_base if k not in base_tokens]
            if missing:
                fallback_css = ":root{" + "".join(f"{k}:{default_base[k]};" for k in missing) + "}\n"
                for k in missing:
                    base_tokens[k] = default_base[k]
                self.notes.append(
                    f"theme '{theme_dir.name}' does not define {len(missing)} token(s); the default theme's "
                    f"values are used: {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}")

        # Fonts: embed only the faces this deck needs
        used: set[str] = set()
        font_values = [(k, v) for k, v in base_tokens.items() if k.startswith("--font-")]
        for variant in tokens.values():
            font_values += [(k, v) for k, v in variant.items() if k.startswith("--font-")]
        for k, v in font_values:
            if k == "--font-mono" and not MONO_USE.search(body):
                continue
            for fam in v.split(","):
                used.add(fam.strip().strip("\"'").lower())
        italic = bool(ITALIC_USE.search(body))
        faces = [(f, theme_dir) for f in _deck.font_faces(css)]
        if default_css:
            # a theme may name one of the built-in fonts without carrying its files
            own = {f["family"].lower() for f, _ in faces}
            faces += [(f, default_dir) for f in _deck.font_faces(default_css) if f["family"].lower() not in own]
        face_css, embedded = [], []
        for face, folder in faces:
            if face["family"].lower() not in used:
                continue
            if face["style"].startswith("italic") and not italic:
                continue
            if face["ranges"] and not any(a <= c <= b for c in text_chars for a, b in face["ranges"]):
                continue
            raw = face["raw"]
            if face["url"] and not face["url"].startswith("data:"):
                fpath = (folder / face["url"]).resolve()
                if not fpath.is_file():
                    self.errors.append(f"theme font file is missing: {fpath}")
                    continue
                raw = raw.replace(face["url"], _deck.data_uri(fpath))
                embedded.append((face["family"], fpath.stat().st_size))
            else:
                embedded.append((face["family"], len(raw) * 3 // 4))
            face_css.append(re.sub(r"\s+", " ", raw))
        body_css = re.sub(r"@font-face\s*\{.*?\}", "", css, flags=re.S)
        body_css = _deck.strip_css_comments(body_css)
        body_css = self.prune_backgrounds(body_css, body, theme_dir.name)
        body_css = self.embed_css_urls(body_css, theme_dir, "The theme")
        body_css = re.sub(r"\n\s*\n+", "\n", body_css).strip()

        # Logo
        logo_css, has_logo = "", False
        logo = meta.get("logo") or {}
        if isinstance(logo, str):
            logo = {"light": logo}
        if not logo:
            for cand in ("logo.svg", "logo.png", "logo.webp"):
                if (theme_dir / cand).is_file():
                    logo = {"light": cand}
                    for dark in ("logo-dark.svg", "logo-dark.png", "logo-dark.webp"):
                        if (theme_dir / dark).is_file():
                            logo["dark"] = dark
                    break
        base_variant = meta.get("default_variant") or "light"
        entries = [(k, v) for k, v in logo.items() if isinstance(v, str)]
        entries.sort(key=lambda kv: kv[0] != base_variant)
        for key, fname in entries:
            lp = theme_dir / fname
            if not lp.is_file():
                self.notes.append(f"theme logo file not found: {lp}")
                continue
            ratio = logo_ratio(lp)
            decl = f"--logo-url:url({_deck.data_uri(lp)});"
            if ratio:
                decl += f"--logo-width:calc(var(--logo-height) * {ratio:.4f});"
            sel = ":root" if key == base_variant or len(entries) == 1 else f':root[data-variant="{key}"]'
            logo_css += f"{sel}{{{decl}}}\n"
            has_logo = True

        out = "\n".join(face_css) + ("\n" if face_css else "") + fallback_css + body_css + ("\n" + logo_css if logo_css else "")
        info = {
            "meta": meta,
            "variants": meta.get("variants") or ([base_variant] + [v for v in tokens if v]),
            "base_variant": base_variant,
            "has_logo": has_logo,
            "fonts": embedded,
            "missing": missing,
        }
        return out, info

    # ---- build ----------------------------------------------------------
    def build(self) -> int:
        args = self.args
        src_path = Path(args.source).expanduser().resolve()
        if not src_path.is_file():
            _deck.die(f"{src_path} does not exist")
        src = _deck.Source(src_path.read_text(encoding="utf-8"), src_path)
        if not src.main:
            _deck.die("no slides found. A deck source needs <main class=\"deck\"> with <section class=\"slide\"> children.")

        if args.output:
            out_path = Path(args.output).expanduser().resolve()
        elif src_path.name.endswith(".src.html"):
            out_path = src_path.with_name(src_path.name[:-len(".src.html")] + ".html")
        elif src.is_built:
            _deck.die("the input is an already-built deck; pass -o to say where the rebuilt file goes")
        else:
            out_path = src_path.with_name(src_path.stem + ".deck.html")
        if out_path == src_path:
            _deck.die("the output would overwrite the source; pass a different -o")

        # Theme, variant, icon set: flag > deck meta > settings
        theme_name = args.theme or src.meta("theme") or self.settings.get("theme") or "default"
        theme_dir = _deck.find_theme(theme_name)
        embedded_theme = None
        if not theme_dir:
            if src.is_built and not args.theme:
                # the deck was built with a theme that is not installed here: keep the one it carries
                m = re.search(r"<style[^>]*>(.*)</style>", _deck.between(src.raw, "theme") or "", flags=re.S)
                embedded_theme = m.group(1).strip() if m else None
            if embedded_theme is None:
                names = ", ".join(n for n, _, _ in _deck.list_themes())
                _deck.die(f"no theme named '{theme_name}'. Installed: {names}")
            self.notes.append(f"theme '{theme_name}' is not installed here, so the theme already inside the deck was kept. "
                              "It carries only the font subsets the earlier text needed.")
        default_dir = _deck.SKILL_DIR / "themes" / "default"

        base_dir = src_path.parent
        main = src.main
        deck_styles = [self.embed_css_urls(s, base_dir, "Deck-wide CSS") for s in src.deck_styles]
        deck_scripts = list(src.deck_scripts)

        # Slide and deck scripts are run by the engine, not by the browser
        def typed(m):
            attrs = m.group(1)
            if re.search(r"\btype\s*=", attrs, flags=re.I):
                return m.group(0)
            return f'<script{attrs} type="text/x-deck">'
        main = re.sub(r"<script\b([^>]*\bdata-(?:slide-scope|deck)\b[^>]*)>", typed, main, flags=re.I)

        # Images and other local files
        def attr_repl(m):
            return m.group(1) + m.group(2) + self.embed_file(m.group(3), base_dir, "A slide") + m.group(2)
        main = re.sub(
            r"(<(?:img|source|video|audio|image|track|embed|object|iframe|input)\b[^>]*?\s(?:src|poster|href|xlink:href|data)\s*=\s*)([\"'])(.*?)\2",
            attr_repl, main, flags=re.I | re.S)
        # an element can carry both src and poster: run once more for the second attribute
        main = re.sub(
            r"(<(?:video)\b[^>]*?\sposter\s*=\s*)([\"'])(.*?)\2", attr_repl, main, flags=re.I | re.S)
        main = self.embed_css_urls(main, base_dir, "A slide")
        if embedded_theme is not None:           # same check and same trimming as for an installed theme
            embedded_theme = self.prune_backgrounds(embedded_theme, main, theme_name)

        body_for_fonts = main + "\n".join(deck_styles)
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", main, flags=re.I | re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text)) + src.title + src.meta("footer")
        chars = {ord(c) for c in text} | {0x201C, 0x2014}

        if embedded_theme is not None:
            old_variants = (src.html_attrs.get("data-variants") or "light").split()
            theme_css = embedded_theme
            tinfo = {"meta": {}, "variants": old_variants, "base_variant": old_variants[0],
                     "has_logo": "data-logo" in src.html_attrs, "fonts": [], "missing": []}
        else:
            theme_css, tinfo = self.theme_css(theme_dir, default_dir, chars, body_for_fonts)
        variants = tinfo["variants"]
        variant = args.variant or src.meta("variant") or self.settings.get("variant") or tinfo["base_variant"]
        if variant not in variants:
            _deck.die(f"theme '{theme_dir.name}' has no '{variant}' variant (it has: {', '.join(variants)})")

        icons_name = (args.icons or src.meta("icons") or self.settings.get("icons")
                      or tinfo["meta"].get("icons") or "lucide")
        icon_set = _deck.load_icon_set(icons_name)
        if not icon_set:
            names = ", ".join(n for n, _, _ in _deck.list_icon_sets())
            _deck.die(f"no icon set named '{icons_name}'. Installed: {names}")
        fallback_set = None
        if self.settings.get("icon_fallback") == "default" and icon_set.name != "lucide":
            fallback_set = _deck.load_icon_set("lucide")

        used_icons = sorted(set(re.findall(r'(?:xlink:)?href\s*=\s*["\']#icon-([\w.-]+)["\']', main)))
        symbols = []
        # the engine and layouts are copied into every deck, so each deck carries their notice
        credits = [f"Built with DynamicDecks {_deck.VERSION}. Engine and layouts: {_deck.LICENSE_NAME}, {_deck.COPYRIGHT}. "
                   "The slides are the work of the deck's author."]
        borrowed = []
        for name in used_icons:
            sym = icon_set.symbol(name)
            if not sym and fallback_set:
                sym = fallback_set.symbol(name)
                if sym:
                    borrowed.append(name)
            if not sym:
                close = difflib.get_close_matches(name, icon_set.names(), n=4, cutoff=0.6)
                hint = f" Close names: {', '.join(close)}." if close else ""
                self.errors.append(
                    f"icon '{name}' is not in the '{icon_set.name}' set.{hint} "
                    f"Search with: python scripts/find_icon.py \"<idea>\"")
                continue
            symbols.append(sym)
        if borrowed:
            self.notes.append(f"{len(borrowed)} icon(s) came from the built-in set because '{icon_set.name}' lacks them: {', '.join(borrowed)}")
        if used_icons and icon_set.meta.get("attribution"):
            credits.append(icon_set.meta["attribution"])
        if borrowed and fallback_set and fallback_set.meta.get("attribution"):
            credits.append(fallback_set.meta["attribution"])
        font_lic = (tinfo["meta"].get("fonts") or {}).get("license")
        fams = sorted({f for f, _ in tinfo["fonts"]})
        if fams:
            credits.append("Fonts: " + ", ".join(fams) + (f". {font_lic}" if font_lic else ""))

        engine_dir = _deck.SKILL_DIR / "engine"
        engine_css = tidy_css((engine_dir / "engine.css").read_text(encoding="utf-8"))
        layouts_css = tidy_css((engine_dir / "layouts.css").read_text(encoding="utf-8"))
        engine_js = (engine_dir / "engine.js").read_text(encoding="utf-8")

        # Head
        esc = lambda s: html.escape(s, quote=True)  # noqa: E731
        metas = dict(src.metas)
        for k in ("viewport", "generator"):
            metas.pop(k, None)
        metas["deck:theme"] = theme_dir.name if theme_dir else str(theme_name)
        metas["deck:variant"] = variant
        metas["deck:icons"] = icon_set.name
        meta_html = "\n".join(f'<meta name="{esc(k)}" content="{esc(v)}">' for k, v in metas.items())
        html_attrs = [f'lang="{esc(src.lang)}"', f'data-theme="{esc(metas["deck:theme"])}"',
                      f'data-variant="{esc(variant)}"', f'data-variants="{esc(" ".join(variants))}"',
                      f'data-icons="{esc(icon_set.name)}"']
        if tinfo["has_logo"]:
            html_attrs.append('data-logo="yes"')

        custom = "\n".join(f"<style data-deck>{s}</style>" for s in deck_styles)
        if deck_scripts:
            custom += "\n" + "\n".join(f'<script data-deck type="text/x-deck">{s}</script>' for s in deck_scripts)
        sprite = ('<svg id="deck-icons" xmlns="http://www.w3.org/2000/svg" width="0" height="0" '
                  'style="position:absolute" aria-hidden="true" focusable="false">' + "".join(symbols) + "</svg>")
        credit_html = "".join(f"\n<!-- {c.replace('--', '-')} -->" for c in credits)

        out = f"""<!doctype html>
<html {' '.join(html_attrs)}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(src.title or 'Deck')}</title>
<meta name="generator" content="DynamicDecks {_deck.VERSION}">
{meta_html}
<link rel="icon" href="data:,">{credit_html}
{MARK['engine_css'][0]}<style id="deck-engine-css">
{engine_css}
</style>{MARK['engine_css'][1]}
{MARK['theme'][0]}<style id="deck-theme">
{theme_css}
</style>{MARK['theme'][1]}
{MARK['layouts'][0]}<style id="deck-layouts">
{layouts_css}
</style>{MARK['layouts'][1]}
{MARK['custom'][0]}
{custom}
{MARK['custom'][1]}
</head>
<body>
{MARK['icons'][0]}{sprite}{MARK['icons'][1]}
{MARK['content'][0]}
{main}
{MARK['content'][1]}
<noscript><p style="font:16px system-ui;padding:24px;color:#fff">This presentation needs JavaScript. Open it in a current browser with scripts allowed.</p></noscript>
{MARK['engine_js'][0]}<script id="deck-engine">
{engine_js}
</script>{MARK['engine_js'][1]}
</body>
</html>
"""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")

        # Report
        n_slides = len(re.findall(r"<section\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bslide\b", main, flags=re.I))
        size = out_path.stat().st_size
        if not args.quiet:
            print(f"Built {out_path}")
            print(f"  {n_slides} slides, theme '{metas['deck:theme']}' ({variant}), icons '{icon_set.name}' ({len(symbols)} used)")
            font_total = sum(s for _, s in tinfo["fonts"])
            print(f"  size {_deck.human_size(size)}: fonts {_deck.human_size(font_total)} ({', '.join(fams) or 'none'}), "
                  f"{self.image_count} image(s) {_deck.human_size(self.image_bytes)}")
            if size > 2 * 1024 * 1024 and self.image_bytes < size / 2:
                print("  note: over 2 MB without much imagery; look for oversized inline SVG or data")
            elif size > 25 * 1024 * 1024:
                print("  note: large file. Fewer or smaller photos will make it easier to share.")
            for n in self.notes:
                print(f"  note: {n}")
        for e in self.errors:
            print(f"error: {e}", file=sys.stderr)

        status = 1 if self.errors else 0
        if not args.no_check:
            try:
                import check
                problems = check.check_file(out_path, icon_set_name=icon_set.name, strict=args.strict, quiet=args.quiet)
                if problems:
                    status = 1
            except ImportError:
                _deck.warn("check.py not found; skipped the delivery checks")
        return status


def tidy_css(css: str) -> str:
    css = _deck.strip_css_comments(css)
    return re.sub(r"\n\s*\n+", "\n", css).strip()


def logo_ratio(path: Path) -> float | None:
    """Width / height of a logo file."""
    if path.suffix.lower() == ".svg":
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'viewBox\s*=\s*["\']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', text)
        if m and float(m.group(2)):
            return float(m.group(1)) / float(m.group(2))
        w = re.search(r'\bwidth\s*=\s*["\']([\d.]+)', text)
        h = re.search(r'\bheight\s*=\s*["\']([\d.]+)', text)
        if w and h and float(h.group(1)):
            return float(w.group(1)) / float(h.group(1))
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size[0] / im.size[1] if im.size[1] else None
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a deck source into one self-contained HTML file.")
    ap.add_argument("source", help="deck source (.src.html) or a previously built deck")
    ap.add_argument("-o", "--output", help="output file (default: next to the source)")
    ap.add_argument("--theme", help="theme name or path to a theme folder (default: deck meta, then settings)")
    ap.add_argument("--variant", help="theme variant, for example light or dark")
    ap.add_argument("--icons", help="icon set name (default: deck meta, then settings, then the theme's choice)")
    ap.add_argument("--no-compress", action="store_true", help="embed images exactly as they are")
    ap.add_argument("--allow-remote", action="store_true", help="tolerate references to internet files (the deck will need a connection)")
    ap.add_argument("--no-check", action="store_true", help="skip the delivery checks")
    ap.add_argument("--strict", action="store_true", help="treat check warnings as failures")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    sys.exit(Builder(args).build())


if __name__ == "__main__":
    main()
