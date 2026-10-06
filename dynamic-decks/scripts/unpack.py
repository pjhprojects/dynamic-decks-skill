#!/usr/bin/env python3
"""Recover an editable source (and the theme) from a built deck.

    python scripts/unpack.py talk.html                 -> talk.src.html
    python scripts/unpack.py talk.html -o work/talk.src.html
    python scripts/unpack.py talk.html --theme-to work/themes/acme

Use this when someone comes back with only the finished .html and wants
changes: unpack it, edit the slides, and build again. Images stay embedded,
so nothing else is needed.

--theme-to also saves the theme the deck was built with as a theme folder
(fonts and logo stay embedded inside its CSS). That lets a custom theme be
reused from any deck that carries it, even when the original theme folder is
gone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Recover an editable source from a built deck.")
    ap.add_argument("deck", help="a deck built by build.py")
    ap.add_argument("-o", "--output", help="where to write the source (default: <name>.src.html next to the deck)")
    ap.add_argument("--theme-to", help="also save the deck's theme into this folder")
    args = ap.parse_args()

    path = Path(args.deck).expanduser().resolve()
    if not path.is_file():
        _deck.die(f"{path} does not exist")
    text = path.read_text(encoding="utf-8")
    src = _deck.Source(text, path)
    if not src.is_built:
        _deck.die("this file was not built by DynamicDecks (no deck markers found). If it is already a source, edit it directly.")

    out = Path(args.output).expanduser() if args.output else path.with_name(path.stem + ".src.html")
    if out.resolve() == path:
        _deck.die("the output would overwrite the deck; pass a different -o")
    keep = {k: v for k, v in src.metas.items() if k not in ("viewport", "generator")}
    metas = "\n".join(f'<meta name="{k}" content="{v.replace(chr(34), "&quot;")}">' for k, v in keep.items())
    custom = (_deck.between(text, "custom") or "").strip()
    doc = f"""<!doctype html>
<html lang="{src.lang}">
<head>
<meta charset="utf-8">
<title>{src.title}</title>
{metas}
{custom}
</head>
<body>
{src.main}
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    slides = len(re.findall(r"<section\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bslide\b", src.main))
    print(f"Source written to {out} ({slides} slides, theme '{src.meta('theme')}', icons '{src.meta('icons')}')")
    print("  Edit it, then: python scripts/build.py " + str(out))

    if args.theme_to:
        theme_css = _deck.between(text, "theme")
        m = re.search(r"<style[^>]*>(.*)</style>", theme_css or "", flags=re.S)
        if not m:
            _deck.die("no theme found inside the deck")
        tdir = Path(args.theme_to).expanduser()
        tdir.mkdir(parents=True, exist_ok=True)
        name = tdir.name
        (tdir / "theme.css").write_text(
            f"/* THEME: {name}. Recovered from {path.name}; fonts and logo are embedded in this file. */\n" + m.group(1).strip() + "\n",
            encoding="utf-8")
        variants = (re.search(r'data-variants="([^"]*)"', text) or [None, "light"])[1].split()
        meta = {"name": name, "label": name, "description": f"Recovered from {path.name}",
                "variants": variants, "default_variant": variants[0] if variants else "light",
                "icons": src.meta("icons"), "fonts": {"license": "", "families": []}, "logo": None}
        (tdir / "theme.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"Theme written to {tdir}. Use it with: build.py --theme {tdir}")


if __name__ == "__main__":
    main()
