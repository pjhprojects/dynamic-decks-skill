#!/usr/bin/env python3
"""Delivery checks for a deck (source or built file).

    python scripts/check.py talk.html
    python scripts/check.py talk.src.html --strict

Fails (exit status 1) on anything that breaks the deck's promises:
  * a file loaded from the internet            (the deck must work offline)
  * a hard-coded color or font in slide content (it would ignore a theme swap)
  * an icon that is not in the icon library
  * a slide without speaker notes
  * an animated slide with no resting state     (print and previews would be wrong)
  * CSS or script that is not scoped to its slide
Warnings point at things worth a look: hard-coded durations, dense slides,
pasted-in icons, images without alt text.

An element can opt out of the color and font check with data-raw="reason"
(for example a customer's logo drawn in its own colors). The reason is
listed in the report.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402

NAMED = set("""aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet
brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred
darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray
green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen
lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink
lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen
linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy
oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip
peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal
thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split())

HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
FUNC = re.compile(r"(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
COLOR_PROP = re.compile(
    r"^(?:color|background(?:-color|-image)?|border(?:-(?:top|right|bottom|left|block|inline)(?:-(?:start|end))?)?"
    r"(?:-color)?|outline(?:-color)?|fill|stroke|stop-color|flood-color|lighting-color|box-shadow|text-shadow|"
    r"caret-color|accent-color|column-rule(?:-color)?|text-decoration(?:-color)?|text-emphasis(?:-color)?|"
    r"filter|backdrop-filter|scrollbar-color|--[\w-]+)$")
PAINT_ATTRS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color", "bgcolor", "text")
DURATION = re.compile(r"(?<![\w.-])(\d*\.?\d+)(ms|s)\b")
REMOTE = re.compile(r"^\s*(?:https?:)?//", re.I)
RESOURCE_ATTRS = ("src", "href", "xlink:href", "poster", "data", "srcset")
RESOURCE_TAGS = {"img", "source", "video", "audio", "iframe", "embed", "object", "link", "script", "image",
                 "use", "track", "input", "feimage"}
STATE_SELECTOR = re.compile(r"(?:^|,)\s*(?:\.is-(?:entered|active|rest)\b|\[data-step-index)")
JS_NET = re.compile(r"\bfetch\s*\(|XMLHttpRequest|new\s+WebSocket|EventSource\s*\(|\bimport\s*\(|importScripts|sendBeacon|https?://")
JS_RISKY = re.compile(r"requestAnimationFrame|setInterval\s*\(|setTimeout\s*\(|deck\.loop\s*\(|deck\.after\s*\(|(?<!deck)\.animate\s*\(")
JS_COLOR = re.compile(r"""['"`]\s*(#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4}))\s*['"`]""")
JS_NAMED = re.compile(r"""(?:fillStyle|strokeStyle|shadowColor|color|backgroundColor|background|fill|stroke)\s*[=:]\s*['"`](\w+)['"`]""")


def css_walk(css: str):
    """Yield ('selector', chain) and ('decl', chain, prop, value) for a stylesheet, nesting included."""
    css = _deck.strip_css_comments(css)
    stack: list[str] = []
    buf, quote, paren = [], "", 0
    for ch in css:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren = max(0, paren - 1)
            buf.append(ch)
        elif ch == "{" and paren == 0:
            stack.append("".join(buf).strip())
            buf = []
            yield ("selector", tuple(stack))
        elif ch in "};" and paren == 0:
            decl = "".join(buf).strip()
            buf = []
            if ":" in decl and not decl.startswith("@"):
                prop, val = decl.split(":", 1)
                yield ("decl", tuple(stack), prop.strip().lower(), val.strip())
            elif decl.startswith("@import"):
                yield ("decl", tuple(stack), "@import", decl)
            if ch == "}" and stack:
                stack.pop()
        else:
            buf.append(ch)
    decl = "".join(buf).strip()
    if ":" in decl and not decl.startswith("@"):
        prop, val = decl.split(":", 1)
        yield ("decl", tuple(stack), prop.strip().lower(), val.strip())


def raw_color_in(prop: str, value: str) -> str | None:
    """The first hard-coded color in a CSS value, if any."""
    v = re.sub(r"url\([^)]*\)", "url()", value)
    m = HEX.search(v)
    if m:
        return m.group(0)
    m = FUNC.search(v)
    if m:
        return m.group(0) + "...)"
    if COLOR_PROP.match(prop):
        cleaned = re.sub(r"var\(\s*--[\w-]+", " ", v)
        for word in re.findall(r"(?<![\w-])[a-zA-Z]+(?![\w-])", cleaned):
            if word.lower() in NAMED:
                return word
    return None


class Report:
    def __init__(self):
        self.items: list[dict] = []
        self.exempt: list[str] = []
        self.info: list[str] = []

    def add(self, level: str, slide, kind: str, msg: str):
        self.items.append({"level": level, "slide": slide, "kind": kind, "message": msg})

    def fail(self, slide, kind, msg):
        self.add("fail", slide, kind, msg)

    def warn(self, slide, kind, msg):
        self.add("warn", slide, kind, msg)

    @property
    def failures(self):
        return [i for i in self.items if i["level"] == "fail"]

    @property
    def warnings(self):
        return [i for i in self.items if i["level"] == "warn"]


def describe(node) -> str:
    cls = node.attrs.get("class")
    return "<" + node.tag + (' class="' + cls + '"' if cls else "") + ">"


def check_css(rep: Report, slide, css: str, where: str, scoped: bool):
    for item in css_walk(css):
        if item[0] == "selector":
            chain = item[1]
            sel = chain[-1]
            if scoped and len(chain) == 1 and STATE_SELECTOR.search(sel):
                rep.fail(slide, "scope",
                         f"{where}: the selector \"{sel}\" never matches, because the state class is on the slide itself. "
                         f"Write \"&{sel.strip().split(',')[0].strip()}\" (& is this slide).")
            if sel.startswith("@keyframes") or sel.startswith("@-webkit-keyframes"):
                name = sel.split()[-1]
                rep.keyframes.setdefault(name, set()).add(slide)
            continue
        _, chain, prop, val = item
        in_keyframes = any(s.startswith(("@keyframes", "@-webkit-keyframes")) for s in chain)
        if prop == "@import":
            rep.fail(slide, "offline", f"{where}: @import loads another file. Everything must be inline.")
            continue
        if re.search(r"url\(\s*['\"]?\s*(?:https?:)?//", val, flags=re.I):
            rep.fail(slide, "offline", f"{where}: {prop} loads a file from the internet.")
        raw = raw_color_in(prop, val)
        if raw:
            rep.fail(slide, "color",
                     f"{where}: \"{prop}: {val[:70]}\" hard-codes {raw}. Use a theme token, for example var(--color-accent).")
        if prop == "font-family" and "var(--font-" not in val and val not in ("inherit", "unset", "initial"):
            rep.fail(slide, "font", f"{where}: \"font-family: {val[:60]}\" hard-codes a font. Use var(--font-display), var(--font-body) or var(--font-mono).")
        if prop == "font" and "var(--font-" not in val and val not in ("inherit", "unset", "initial"):
            rep.fail(slide, "font", f"{where}: the \"font\" shorthand hard-codes a font. Set font-size and font-weight separately, or include var(--font-body).")
        if prop in ("animation", "animation-fill-mode") and re.search(r"\bforwards\b", val):
            rep.fail(slide, "rest",
                     f"{where}: \"{prop}: {val[:60]}\" relies on 'forwards'. The finished look must be the element's own "
                     "style: animate FROM a start state and use 'backwards' (or 'both').")
        if re.match(r"^(?:animation|transition)(?:-duration|-delay)?$", prop):
            for m in DURATION.finditer(re.sub(r"var\([^)]*\)", "", val)):
                if float(m.group(1)) != 0:
                    rep.warn(slide, "motion",
                             f"{where}: \"{prop}: {val[:60]}\" hard-codes {m.group(0)}. Prefer var(--dur-fast), var(--dur-base) "
                             "or var(--dur-slow) so motion matches the rest of the deck.")
                    break
        if not in_keyframes and prop in ("opacity", "visibility", "display") and val.split("!")[0].strip() in ("0", "hidden", "none"):
            guarded = any(re.search(r"is-entered|is-step|data-step|:not\(|:hover|is-rest|deck-rest|is-active", s) for s in chain)
            if not guarded and where != "theme":
                rep.warn(slide, "rest",
                         f"{where}: \"{' '.join(chain)[-50:]} {{ {prop}: {val} }}\" hides content in the element's own style. "
                         "If an animation reveals it, the printed and resting slide will be missing it.")


def check_script(rep: Report, slide, js: str, where: str):
    stripped = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", js, flags=re.S))
    m = JS_NET.search(stripped)
    if m:
        rep.fail(slide, "offline", f"{where}: uses {m.group(0).strip()}, which reaches outside the file. Decks must work offline.")
    for m in JS_COLOR.finditer(stripped):
        before = stripped[max(0, m.start() - 28):m.start()]
        if re.search(r"(?:querySelector(?:All)?|closest|matches|getElementById|href)\W*$", before):
            continue  # an id selector such as '#add', not a color
        rep.fail(slide, "color", f"{where}: hard-codes {m.group(1)}. Read colors from the theme with deck.token('--color-accent').")
        break
    for m in JS_NAMED.finditer(stripped):
        if m.group(1).lower() in NAMED:
            rep.fail(slide, "color", f"{where}: hard-codes the color '{m.group(1)}'. Read colors from the theme with deck.token('--color-accent').")
            break
    if FUNC.search(re.sub(r"deck\.token\([^)]*\)", "", stripped)) and re.search(r"['\"`]\s*(?:rgba?|hsla?|oklch|oklab)\(", stripped):
        rep.fail(slide, "color", f"{where}: builds a color with rgb()/hsl(). Read colors from the theme with deck.token().")
    if re.search(r"\.font\s*=\s*['\"`]", stripped) and "token(" not in stripped:
        rep.fail(slide, "font", f"{where}: sets a canvas font by hand. Build it from deck.token('--font-body').")
    if JS_RISKY.search(stripped) and "deck:rest" not in stripped:
        rep.fail(slide, "rest",
                 f"{where}: animates with timers or frames but has no 'deck:rest' handler. Add "
                 "slide.addEventListener('deck:rest', ...) that draws the finished frame, so print and previews are right.")
    if re.search(r"document\.(?:querySelector|getElementById|getElementsBy)", stripped):
        rep.warn(slide, "scope", f"{where}: looks things up on the whole document. Use slide.querySelector(...) so it stays inside this slide.")
    if re.search(r"\b(?:localStorage|sessionStorage|document\.cookie)\b", stripped):
        rep.warn(slide, "scope", f"{where}: uses browser storage, which is unreliable for a file opened from disk.")


def run_checks(src: _deck.Source, icon_set: _deck.IconSet | None, settings: dict, fallback_set=None) -> Report:
    rep = Report()
    rep.keyframes = {}
    if not src.main:
        rep.fail(None, "structure", "No slides found. A deck needs <main class=\"deck\"> with <section class=\"slide\"> children.")
        return rep
    tree = _deck.parse_tree(src.main)
    slides = _deck.slides_of(tree)
    main = next((n for n in tree.walk() if n.tag == "main"), None)
    if not slides:
        rep.fail(None, "structure", "No <section class=\"slide\"> elements directly inside <main class=\"deck\">.")
        return rep
    if main is not None:
        strays = [c for c in main.children if c not in slides]
        if strays:
            rep.warn(None, "structure",
                     f"{len(strays)} element(s) inside <main> are not slides ({', '.join(describe(s) for s in strays[:3])}); they will not be shown.")
    if not src.title:
        rep.warn(None, "structure", "The deck has no <title>; browsers will show the file name.")

    notes_required = settings.get("notes", "required") == "required" and src.meta("notes", "") not in ("off", "none", "optional")
    for css in src.deck_styles:
        check_css(rep, None, css, "deck-wide CSS", scoped=False)
    for js in src.deck_scripts:
        check_script(rep, None, js, "deck-wide script")

    seen_ids: dict[str, int] = {}
    motion_slides = 0
    for n, slide in enumerate(slides, 1):
        layout = slide.attrs.get("data-layout")
        if layout and layout not in _deck.LAYOUTS:
            rep.fail(n, "layout", f"unknown layout \"{layout}\". Use one of: {', '.join(_deck.LAYOUTS)}; or leave data-layout off for a blank framed slide.")
        sid = slide.attrs.get("id")
        if sid:
            if sid in seen_ids:
                rep.fail(n, "structure", f"id \"{sid}\" is already used by slide {seen_ids[sid]}.")
            seen_ids[sid] = n

        notes = [c for c in slide.children if c.tag == "aside" and "notes" in c.classes()]
        if notes_required and slide.attrs.get("data-notes") != "none":
            if not notes or not notes[0].all_text().strip():
                rep.fail(n, "notes", "no speaker notes. Add <aside class=\"notes\">...</aside> with what to say on this slide.")

        has_motion = False
        words = 0
        bullets = 0
        per_list: dict[int, int] = {}
        for node in slide.walk():
            if node is slide:
                pass
            raw_holder = node.closest(lambda x: "data-raw" in x.attrs)
            exempt = raw_holder is not None
            if exempt and node is raw_holder:
                rep.exempt.append(f"slide {n}: {describe(node)} keeps its own colors ({node.attrs.get('data-raw') or 'no reason given'})")
            tag = node.tag
            in_notes = node.closest(lambda x: x.tag == "aside" and "notes" in x.classes()) is not None

            if "data-anim" in node.attrs or "data-count" in node.attrs or "data-type" in node.attrs:
                has_motion = True

            if tag == "style":
                css = "".join(node.text)
                if "data-slide-scope" not in node.attrs:
                    rep.fail(n, "scope", "a <style> inside a slide needs the data-slide-scope attribute, or it would restyle every slide.")
                check_css(rep, n, css, "slide CSS", scoped=True)
                if re.search(r"\banimation\s*:|@keyframes", css):
                    has_motion = True
                continue
            if tag == "script":
                js = "".join(node.text)
                if node.attrs.get("src"):
                    rep.fail(n, "offline", f"<script src=\"{node.attrs['src'][:60]}\"> loads a separate file. Scripts must be inline.")
                if "data-slide-scope" not in node.attrs and "data-deck" not in node.attrs:
                    rep.fail(n, "scope", "a <script> inside a slide needs the data-slide-scope attribute so the engine runs it for this slide only.")
                check_script(rep, n, js, "slide script")
                has_motion = True
                continue
            if tag == "link":
                rep.fail(n, "offline", "<link> loads a separate file. Styles and fonts must come from the theme.")
            if tag == "iframe":
                rep.warn(n, "offline", "<iframe> content usually needs a connection and will be blank offline.")
            if tag in RESOURCE_TAGS:
                for a in RESOURCE_ATTRS:
                    v = node.attrs.get(a, "")
                    if v and REMOTE.match(v) and not (tag == "a"):
                        rep.fail(n, "offline", f"<{tag} {a}=\"{v[:70]}\"> loads from the internet. Reference a local file so the build can embed it.")
            if tag == "use":
                href = node.attrs.get("href") or node.attrs.get("xlink:href") or ""
                if href.startswith("#icon-"):
                    name = href[len("#icon-"):]
                    ok = icon_set is None or icon_set.has(name) or (fallback_set is not None and fallback_set.has(name))
                    if not ok:
                        rep.fail(n, "icon",
                                 f"icon \"{name}\" is not in the '{icon_set.name}' set. Find one with: python scripts/find_icon.py \"<idea>\". "
                                 "If nothing fits, say so and offer to draw one; do not substitute a look-alike.")
            if tag == "svg" and not exempt:
                cls = " ".join(node.classes())
                vb = (node.attrs.get("viewbox") or "").replace(",", " ").split()
                small = len(vb) == 4 and _num(vb[2]) <= 64 and _num(vb[3]) <= 64
                has_use = any(c.tag == "use" for c in node.walk())
                has_shapes = any(c.tag in ("path", "circle", "rect", "polyline", "polygon", "line") for c in node.walk())
                if small and has_shapes and not has_use and not re.search(r"\b(chart|diagram)\b", cls):
                    rep.warn(n, "icon", f"{describe(node)} looks like an icon pasted in by hand. Icons come from the library: <svg class=\"icon\"><use href=\"#icon-NAME\"/></svg>.")
            if tag == "img" and "alt" not in node.attrs:
                rep.warn(n, "image", f"<img src=\"{node.attrs.get('src', '')[:40]}\"> has no alt text.")
            if tag == "font":
                rep.fail(n, "font", "<font> hard-codes type styling. Use classes and theme tokens.")

            if not exempt:
                style = node.attrs.get("style", "")
                if style:
                    for prop, val in _deck.split_declarations(style):
                        prop = prop.lower()
                        raw = raw_color_in(prop, val)
                        if raw:
                            rep.fail(n, "color", f"{describe(node)} style=\"{prop}: {val[:50]}\" hard-codes {raw}. Use a theme token, for example var(--color-accent).")
                        if prop in ("font-family", "font") and "var(--font-" not in val and val != "inherit":
                            rep.fail(n, "font", f"{describe(node)} style=\"{prop}: {val[:50]}\" hard-codes a font. Use var(--font-display), var(--font-body) or var(--font-mono).")
                        if re.match(r"^(?:animation|transition)(?:-duration|-delay)?$", prop):
                            has_motion = True
                            if any(float(m.group(1)) != 0 for m in DURATION.finditer(re.sub(r"var\([^)]*\)", "", val))):
                                rep.warn(n, "motion", f"{describe(node)} style=\"{prop}: {val[:50]}\" hard-codes a duration. Prefer the motion tokens.")
                        if re.search(r"url\(\s*['\"]?\s*(?:https?:)?//", val, flags=re.I):
                            rep.fail(n, "offline", f"{describe(node)} style loads a file from the internet.")
                for a in PAINT_ATTRS:
                    if a == "text" and tag != "body":
                        continue
                    if a == "color" and tag not in ("font", "svg", "g", "path", "circle", "rect", "text"):
                        continue
                    v = node.attrs.get(a)
                    if v is None:
                        continue
                    lv = v.strip().lower()
                    if lv in ("none", "currentcolor", "inherit", "transparent", "context-stroke", "context-fill", "") or lv.startswith(("url(#", "var(")):
                        continue
                    rep.fail(n, "color",
                             f"{describe(node)} {a}=\"{v[:40]}\" hard-codes a color. Use a class (for example series-1, node--accent) "
                             f"or style=\"{a}: var(--color-accent)\".")
                ff = node.attrs.get("font-family")
                if ff and "var(--font-" not in ff:
                    rep.fail(n, "font", f"{describe(node)} font-family=\"{ff[:40]}\" hard-codes a font.")

            if not in_notes and tag not in ("style", "script"):
                if tag == "li":
                    lst = node.parent
                    if lst is not None and lst.tag in ("ul", "ol") and not lst.attrs.get("class") and lst.closest(lambda x: x.tag == "li") is None:
                        per_list[id(lst)] = per_list.get(id(lst), 0) + 1
                        bullets = max(bullets, per_list[id(lst)])
                if node.closest(lambda x: x.tag == "svg") is None:
                    words += len(" ".join(node.text).split())

        if has_motion:
            motion_slides += 1
        if bullets > 6:
            rep.warn(n, "density", f"{bullets} bullets in one list. More than six is hard to read from the back of a room; split the slide or cut.")
        if words > 110:
            rep.warn(n, "density", f"about {words} words on the slide. Move detail into the notes.")

    for name, where in rep.keyframes.items():
        if len(where) > 1 and not name.startswith("deck-"):
            rep.warn(None, "scope", f"@keyframes \"{name}\" is defined on slides {sorted(x for x in where if x)}; keyframe names are shared by the whole deck, so give each a unique name.")
    rep.info.append(f"{len(slides)} slides; motion on {motion_slides} of them")
    return rep


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 1e9


def print_report(rep: Report, label: str, quiet: bool = False) -> None:
    fails, warns = rep.failures, rep.warnings
    if quiet and not fails and not warns:
        return
    print(f"Checks for {label}: " + "; ".join(rep.info))
    for item in sorted(rep.items, key=lambda i: (i["level"] != "fail", i["slide"] or 0)):
        tag = "FAIL" if item["level"] == "fail" else "warn"
        where = f"slide {item['slide']}" if item["slide"] else "deck"
        print(f"  {tag}  {where:<9} {item['kind']:<9} {item['message']}")
    for e in rep.exempt:
        print(f"  note  {e}")
    if fails:
        print(f"Result: {len(fails)} problem(s) to fix before delivery" + (f", {len(warns)} warning(s)." if warns else "."))
    elif warns:
        print(f"Result: passes, with {len(warns)} warning(s) to look at.")
    else:
        print("Result: all checks pass.")


def check_file(path: Path, icon_set_name: str | None = None, strict: bool = False, quiet: bool = False,
               as_json: bool = False) -> int:
    path = Path(path)
    src = _deck.Source(path.read_text(encoding="utf-8"), path)
    settings = _deck.load_settings()
    name = icon_set_name or src.meta("icons") or settings.get("icons") or "lucide"
    icon_set = _deck.load_icon_set(name)
    if icon_set is None:
        _deck.warn(f"icon set '{name}' is not installed; icon names were not checked")
    fallback = None
    if settings.get("icon_fallback") == "default" and icon_set is not None and icon_set.name != "lucide":
        fallback = _deck.load_icon_set("lucide")
    rep = run_checks(src, icon_set, settings, fallback)
    if as_json:
        print(json.dumps({"file": str(path), "items": rep.items, "exempt": rep.exempt, "info": rep.info}, indent=2))
    else:
        print_report(rep, path.name, quiet)
    return len(rep.failures) + (len(rep.warnings) if strict else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the delivery checks on a deck.")
    ap.add_argument("deck", help="deck source or built deck")
    ap.add_argument("--icons", help="icon set to check icon names against (default: the deck's)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = Path(args.deck).expanduser()
    if not p.is_file():
        _deck.die(f"{p} does not exist")
    problems = check_file(p, args.icons, args.strict, as_json=args.json)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
