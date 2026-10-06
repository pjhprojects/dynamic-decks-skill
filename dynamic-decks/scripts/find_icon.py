#!/usr/bin/env python3
"""Find icons in an icon set by meaning.

    python scripts/find_icon.py growth
    python scripts/find_icon.py "team meeting" security --limit 6
    python scripts/find_icon.py --check rocket trending-up not-a-real-icon
    python scripts/find_icon.py --sets

Search several ideas at once: each quoted argument is its own search. Results
are icon names to use as  <svg class="icon"><use href="#icon-NAME"/></svg>.
Only names printed here (or confirmed by --check) exist in the set; a name
that is not in the set fails the build.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402

# Presentation concepts mapped to words that appear in icon names and tags.
CONCEPTS = {
    "growth": "trending-up chart increase sprout rocket arrow-up-right scaling",
    "grow": "trending-up sprout scaling arrow-up-right",
    "increase": "trending-up arrow-up plus chevrons-up",
    "decline": "trending-down arrow-down-right decrease",
    "decrease": "trending-down arrow-down minus",
    "money": "dollar banknote coins wallet piggy credit-card currency",
    "revenue": "dollar banknote coins trending-up receipt",
    "cost": "dollar receipt wallet coins calculator",
    "price": "tag dollar receipt badge",
    "budget": "wallet calculator piggy coins",
    "profit": "trending-up coins banknote piggy",
    "finance": "landmark banknote dollar chart wallet",
    "bank": "landmark piggy banknote",
    "team": "users user-round handshake group",
    "people": "users user person contact",
    "customer": "users user heart smile handshake store",
    "user": "user circle-user contact",
    "partner": "handshake users link",
    "partnership": "handshake link users",
    "leader": "crown flag compass user-star",
    "leadership": "crown flag compass",
    "hire": "user-plus briefcase users",
    "time": "clock timer calendar hourglass alarm",
    "schedule": "calendar clock calendar-days",
    "deadline": "alarm calendar-clock timer flag",
    "speed": "zap gauge rocket timer fast",
    "fast": "zap gauge rocket fast-forward",
    "efficiency": "gauge zap timer",
    "performance": "gauge activity zap chart",
    "security": "shield lock key fingerprint",
    "secure": "shield lock key",
    "privacy": "lock eye-off shield",
    "risk": "triangle-alert shield-alert alert flame",
    "warning": "triangle-alert alert octagon",
    "danger": "triangle-alert skull flame siren",
    "idea": "lightbulb sparkles brain",
    "innovation": "lightbulb sparkles rocket flask",
    "goal": "target flag goal crosshair trophy",
    "target": "target crosshair goal",
    "strategy": "compass map route target chess",
    "plan": "map route clipboard list calendar",
    "roadmap": "map route milestone flag signpost",
    "milestone": "milestone flag check",
    "success": "check circle-check badge-check trophy award",
    "done": "check circle-check check-check",
    "win": "trophy award medal crown",
    "award": "award trophy medal badge",
    "quality": "award badge-check star gem",
    "fail": "x circle-x ban thumbs-down",
    "error": "circle-x triangle-alert bug octagon",
    "problem": "bug triangle-alert circle-x puzzle",
    "solution": "lightbulb key puzzle check",
    "data": "database chart table hard-drive",
    "analytics": "chart activity trending-up pie",
    "chart": "chart bar line pie area",
    "report": "file-text clipboard chart presentation",
    "metric": "gauge chart activity ruler",
    "ai": "sparkles bot brain cpu",
    "robot": "bot",
    "automation": "bot workflow cog zap repeat",
    "process": "workflow route git-branch list-ordered repeat",
    "workflow": "workflow git-branch route",
    "settings": "settings sliders cog wrench",
    "search": "search scan telescope",
    "research": "microscope flask search telescope book",
    "science": "flask atom microscope dna test-tube",
    "communication": "message mail phone megaphone",
    "message": "message mail send",
    "email": "mail inbox send",
    "chat": "message bot",
    "announce": "megaphone bell radio",
    "marketing": "megaphone target badge-percent",
    "sales": "handshake badge-dollar shopping-cart trending-up",
    "document": "file file-text clipboard",
    "write": "pencil pen file-pen",
    "code": "code terminal braces git",
    "developer": "code terminal git-branch",
    "cloud": "cloud server",
    "server": "server database hard-drive",
    "world": "globe earth map",
    "europe": "globe earth map euro",
    "region": "globe map map-pin earth",
    "country": "globe flag map",
    "international": "globe earth languages plane",
    "expand": "expand maximize globe scaling",
    "engineer": "code wrench hard-hat cpu user-cog",
    "retention": "repeat heart users magnet",
    "churn": "user-minus user-x trending-down",
    "approve": "check circle-check stamp thumbs-up",
    "decide": "split signpost scale gavel",
    "global": "globe earth languages",
    "location": "map-pin navigation map",
    "travel": "plane map luggage",
    "launch": "rocket send play",
    "start": "play rocket flag power",
    "stop": "octagon square ban pause",
    "health": "heart activity stethoscope pill",
    "medical": "stethoscope pill hospital syringe cross",
    "education": "graduation-cap book school",
    "learn": "graduation-cap book lightbulb",
    "training": "graduation-cap dumbbell presentation",
    "build": "hammer wrench construction blocks",
    "tool": "wrench hammer drill",
    "integration": "plug link puzzle cable network",
    "connect": "plug link cable network share",
    "network": "network share waypoints",
    "scale": "scaling expand maximize layers",
    "legal": "scale gavel file-text",
    "law": "scale gavel landmark",
    "compliance": "shield-check clipboard-check scale",
    "shop": "shopping-cart store tag package",
    "commerce": "shopping-cart store credit-card",
    "product": "package box boxes",
    "delivery": "truck package send",
    "shipping": "truck package ship container",
    "energy": "zap battery plug sun",
    "environment": "leaf recycle sprout tree",
    "sustainability": "leaf recycle sprout",
    "question": "circle-help message-circle-question",
    "help": "circle-help life-buoy headset",
    "support": "life-buoy headset headphones",
    "mobile": "smartphone tablet",
    "phone": "phone smartphone",
    "computer": "laptop monitor",
    "video": "video play clapperboard",
    "photo": "image camera",
    "music": "music headphones",
    "compare": "scale git-compare columns",
    "decision": "split git-branch signpost",
    "choice": "split signpost list-checks",
    "feedback": "message-square thumbs-up star",
    "like": "thumbs-up heart",
    "love": "heart",
    "home": "house",
    "building": "building factory landmark",
    "company": "building briefcase",
    "factory": "factory",
    "work": "briefcase",
    "job": "briefcase",
    "calendar": "calendar",
    "list": "list list-checks",
    "checklist": "list-checks clipboard-check",
    "lock": "lock key",
    "open": "lock-open door-open",
    "download": "download",
    "upload": "upload",
    "share": "share send",
    "focus": "focus crosshair target eye",
    "vision": "eye telescope binoculars",
    "insight": "lightbulb eye search",
    "attention": "bell eye megaphone",
    "balance": "scale",
    "cycle": "refresh repeat rotate",
    "change": "refresh repeat shuffle",
    "transform": "refresh wand shuffle",
    "magic": "wand sparkles",
    "new": "sparkles plus badge-plus",
    "fire": "flame",
    "hot": "flame",
    "star": "star",
    "layers": "layers",
    "stack": "layers",
    "puzzle": "puzzle",
    "key": "key",
}


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def stem(t: str) -> str:
    for suf in ("ies", "es", "s", "ing"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[:-len(suf)] + ("y" if suf == "ies" else "")
    return t


def search(icon_set: _deck.IconSet, query: str, limit: int) -> list[tuple[float, str]]:
    terms = tokens(query)
    if not terms:
        return []
    scored = []
    for name, entry in icon_set.icons.items():
        ntoks = name.split("-")
        tags = [t for k in entry.get("k", []) for t in [k.lower()]]
        ttoks = [t for k in tags for t in tokens(k)]
        total, matched = 0.0, 0
        for term in terms:
            st = stem(term)
            best = 0.0
            if name == term or name == query.strip().lower().replace(" ", "-"):
                best = 100
            elif term in ntoks or st in ntoks:
                best = 60
            elif term in tags or term in ttoks or st in ttoks:
                best = 40
            elif any(t.startswith(st) for t in ntoks):
                best = 25
            elif any(t.startswith(st) for t in ttoks):
                best = 15
            for pos, w in enumerate(CONCEPTS.get(term, CONCEPTS.get(st, "")).split()):
                wt = w.split("-")
                if name == w:
                    best = max(best, 58 - pos * 3)
                elif all(x in ntoks for x in wt):
                    best = max(best, 36 - pos * 2)
            if best:
                matched += 1
                total += best
        if matched:
            total *= matched / len(terms)
            total -= len(ntoks) * 1.5 + (4 if "a" in entry else 0)
            scored.append((total, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:limit]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find icons by meaning.")
    ap.add_argument("queries", nargs="*", help="one search per argument; quote multi-word ideas")
    ap.add_argument("--set", dest="icon_set", help="icon set to search (default: the active set)")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--check", nargs="+", metavar="NAME", help="confirm that these exact names exist")
    ap.add_argument("--list", action="store_true", help="print every icon name")
    ap.add_argument("--sets", action="store_true", help="list installed icon sets")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    settings = _deck.load_settings()
    if args.sets:
        active = args.icon_set or settings.get("icons") or "lucide"
        for name, path, origin in _deck.list_icon_sets():
            meta = _deck.read_json(path / "set.json", {}) or {}
            flag = "  (active)" if name == active else ""
            print(f"{name:<16} {meta.get('count', '?'):>5} icons  {meta.get('style', ''):<7} {origin}{flag}")
            if meta.get("license"):
                print(f"{'':<16} {meta['license']}")
        return

    set_name = args.icon_set or settings.get("icons") or "lucide"
    icon_set = _deck.load_icon_set(set_name)
    if not icon_set:
        _deck.die(f"no icon set named '{set_name}'. Installed: " + ", ".join(n for n, _, _ in _deck.list_icon_sets()))

    if args.list:
        print("\n".join(icon_set.names()))
        return

    if args.check:
        missing = [n for n in args.check if not icon_set.has(n)]
        for n in args.check:
            print(f"{'ok     ' if icon_set.has(n) else 'MISSING'} {n}")
        if missing:
            print(f"\n{len(missing)} not in set '{icon_set.name}'. Closest matches:")
            for n in missing:
                hits = search(icon_set, n.replace("-", " "), 5)
                print(f"  {n}: " + (", ".join(h for _, h in hits) or "nothing close"))
            sys.exit(1)
        return

    if not args.queries:
        ap.error("give something to search for")
    results = {}
    for q in args.queries:
        results[q] = [name for _, name in search(icon_set, q, args.limit)]
    if args.json:
        print(json.dumps({"set": icon_set.name, "results": results}, indent=2))
        return
    print(f"Icon set: {icon_set.name} ({len(icon_set.icons)} icons, {icon_set.style} style)")
    for q, names in results.items():
        print(f"\n{q}")
        if not names:
            print("  nothing fits. Say so, and offer to draw one in this set's style; do not swap in a look-alike.")
            continue
        for n in names:
            entry = icon_set.icons[n]
            keys = ", ".join(entry.get("k", [])[:6])
            alias = f"  (same as {entry['a']})" if "a" in entry else ""
            print(f"  {n:<28} {keys}{alias}")


if __name__ == "__main__":
    main()
