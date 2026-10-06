#!/usr/bin/env python3
"""Open a built deck in a real browser and look at it.

    python scripts/render.py talk.html                       screenshots + contact sheet + checks
    python scripts/render.py talk.html --out shots/
    python scripts/render.py talk.html --pdf talk.pdf        one slide per page, resting state
    python scripts/render.py talk.html --notes-pdf notes.pdf slide plus notes per page
    python scripts/render.py talk.html --variant dark --slides 3,7-9

Every slide is captured in its resting state (final frame, all steps shown),
which is what print, previews and the overview use. The run also reports:
  * content that runs off the slide or collides with the footer
  * text smaller than the smallest theme size
  * script errors
  * any network request (a deck must make none)
Look at contact.png (or the individual slide-NN.png files) before delivering.

Needs Playwright with Chromium:  pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deck  # noqa: E402

PROBE = r"""
(n) => {
  const slide = Deck.slides[n];
  const out = { number: n + 1, layout: slide.getAttribute('data-layout') || '', problems: [] };
  const sr = slide.getBoundingClientRect();
  const scale = sr.width / 1920;
  const px = (v) => Math.round(v / scale);
  const bleed = slide.getAttribute('data-layout') === 'full-bleed';
  if (slide.getAttribute('data-script-error')) out.problems.push('script error: ' + slide.getAttribute('data-script-error'));
  const body = slide.querySelector(':scope > .slide-body');
  if (body && body.scrollHeight > body.clientHeight + 3) {
    out.problems.push('content is ' + (body.scrollHeight - body.clientHeight) + 'px taller than the space under the title');
  }
  if (body && body.scrollWidth > body.clientWidth + 3) {
    out.problems.push('content is ' + (body.scrollWidth - body.clientWidth) + 'px wider than the slide body');
  }
  const footer = slide.querySelector(':scope > .slide-footer');
  const footerTop = footer && getComputedStyle(footer).display !== 'none' ? footer.getBoundingClientRect().top : null;
  let off = 0, collide = 0, small = 0, smallest = 999, clipped = 0;
  const seen = new Set();
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_ELEMENT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.closest('aside.notes, style, script, .slide-footer, [data-bleed], defs, symbol')) continue;
    const cs = getComputedStyle(node);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = node.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    const hasText = Array.from(node.childNodes).some((c) => c.nodeType === 3 && c.textContent.trim());
    if (!bleed && !node.closest('[data-layout="image"] > .slide-image')) {
      if (r.right > sr.right + 2 || r.bottom > sr.bottom + 2 || r.left < sr.left - 2 || r.top < sr.top - 2) {
        if (hasText || node.tagName === 'IMG' || node.tagName === 'svg') off++;
      }
    }
    if (hasText) {
      const fs = parseFloat(cs.fontSize) ;
      if (fs && fs < smallest) smallest = fs;
      if (fs && fs < 20) small++;
      if (footerTop !== null && !node.closest('.slide-image') && r.bottom > footerTop + 2 && r.top < sr.bottom && !seen.has(node)) { collide++; seen.add(node); }
      if (node.scrollWidth > node.clientWidth + 2 && cs.overflow !== 'visible' && node.clientWidth > 0) clipped++;
    }
  }
  if (off) out.problems.push(off + ' element(s) run off the edge of the slide');
  if (collide) out.problems.push(collide + ' text element(s) reach into the footer area');
  if (clipped) out.problems.push(clipped + ' text element(s) are cut off');
  if (small) out.problems.push(small + ' text element(s) are under 20px (smallest ' + Math.round(smallest) + 'px); hard to read when projected');
  out.steps = parseInt(slide.dataset.stepIndex || '0', 10);
  out.hasNotes = !!slide.querySelector(':scope > aside.notes');
  return out;
}
"""


def parse_slides(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(total))
    picked = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            picked += list(range(int(a) - 1, int(b)))
        elif part:
            picked.append(int(part) - 1)
    return [i for i in picked if 0 <= i < total]


def contact_sheet(files: list[tuple[int, Path]], out: Path, cols: int = 4) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    tw, th, pad, label = 480, 270, 16, 26
    rows = math.ceil(len(files) / cols)
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label + pad) + pad), (24, 26, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    for k, (num, f) in enumerate(files):
        im = Image.open(f).convert("RGB").resize((tw, th), Image.LANCZOS)
        x = pad + (k % cols) * (tw + pad)
        y = pad + (k // cols) * (th + label + pad)
        sheet.paste(im, (x, y + label))
        draw.text((x, y), f"{num}", fill=(230, 232, 240), font=font)
    sheet.save(out)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a built deck in Chromium: screenshots, checks, PDF.")
    ap.add_argument("deck", help="built deck (.html)")
    ap.add_argument("--out", help="folder for screenshots and the report (default: <deck>-render next to the deck)")
    ap.add_argument("--slides", help="which slides to capture, for example 3,7-9 (default: all)")
    ap.add_argument("--variant", help="theme variant to render, for example dark")
    ap.add_argument("--pdf", help="also write a PDF of the slides to this path")
    ap.add_argument("--notes-pdf", help="also write a PDF with each slide and its notes to this path")
    ap.add_argument("--no-shots", action="store_true", help="skip screenshots (checks and PDF only)")
    ap.add_argument("--scale", type=float, default=1.0, help="screenshot scale factor (default 1 = 1920x1080)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args()

    deck = Path(args.deck).expanduser().resolve()
    if not deck.is_file():
        _deck.die(f"{deck} does not exist")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _deck.die("Playwright is not installed. Run: pip install playwright && playwright install chromium\n"
                  "Without it, open the deck in a browser yourself and page through every slide before delivering.")

    out_dir = Path(args.out).expanduser() if args.out else deck.with_name(deck.stem + "-render")
    out_dir.mkdir(parents=True, exist_ok=True)
    url = deck.as_uri()
    requests, console, report = [], [], {"deck": str(deck), "slides": []}

    with sync_playwright() as p:
        launch = {}
        exe = os.environ.get("DYNAMIC_DECKS_CHROMIUM") or os.environ.get("HTML_DECK_CHROMIUM")
        if exe:
            launch["executable_path"] = exe
        try:
            browser = p.chromium.launch(**launch)
        except Exception as exc:  # noqa: BLE001
            alt = "/opt/pw-browsers/chromium"
            if not exe and Path(alt).exists():
                browser = p.chromium.launch(executable_path=alt)
            else:
                _deck.die(f"could not start Chromium: {exc}\nSet DYNAMIC_DECKS_CHROMIUM to a Chromium or Chrome executable.")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=args.scale)
        page.on("request", lambda r: requests.append(r.url))
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console.append(f"error: {e}"))
        page.goto(url)
        page.wait_for_function("document.documentElement.classList.contains('deck-ready') && !!window.Deck", timeout=15000)
        page.evaluate("document.fonts.ready")
        if args.variant:
            page.evaluate("(v) => Deck.setVariant(v)", args.variant)
        total = page.evaluate("Deck.total")
        report["total"] = total
        page.evaluate("Deck.rest(true)")
        shots = []
        for i in parse_slides(args.slides, total):
            page.evaluate("(i) => Deck.go(i)", i)
            page.wait_for_timeout(60)
            info = page.evaluate(PROBE, i)
            if not args.no_shots:
                f = out_dir / f"slide-{i + 1:02d}.png"
                page.screenshot(path=str(f))
                shots.append((i + 1, f))
            report["slides"].append(info)
        if shots and contact_sheet(shots, out_dir / "contact.png"):
            report["contact"] = str(out_dir / "contact.png")

        if args.pdf:
            page.emulate_media(media="print")
            page.pdf(path=args.pdf, width="1920px", height="1080px", print_background=True, prefer_css_page_size=True)
            page.emulate_media(media="screen")
            report["pdf"] = args.pdf
        if args.notes_pdf:
            page.evaluate("Deck.printNotes({ print: false })")
            page.emulate_media(media="print")
            page.pdf(path=args.notes_pdf, print_background=True, prefer_css_page_size=True)
            page.emulate_media(media="screen")
            page.evaluate("Deck.endPrintNotes()")
            report["notes_pdf"] = args.notes_pdf
        browser.close()

    outside = sorted({u for u in requests if not u.startswith(("data:", "blob:", "about:")) and u.split("#")[0].split("?")[0] != url})
    report["network"] = outside
    report["console"] = console
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    problems = sum(len(s["problems"]) for s in report["slides"]) + len(outside) + sum(1 for c in console if c.startswith("error"))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Rendered {len(report['slides'])} of {total} slides from {deck.name}")
        for s in report["slides"]:
            for prob in s["problems"]:
                print(f"  LOOK  slide {s['number']:<3} {prob}")
        for u in outside:
            print(f"  FAIL  network request: {u}")
        for c in console:
            print(f"  {'FAIL' if c.startswith('error') else 'note'}  browser {c}")
        if not args.no_shots:
            print(f"  screenshots: {out_dir}/slide-NN.png" + (f"\n  contact sheet: {report['contact']}" if report.get("contact") else ""))
        if args.pdf:
            print(f"  PDF: {args.pdf}")
        if args.notes_pdf:
            print(f"  notes PDF: {args.notes_pdf}")
        if problems:
            print(f"Result: {problems} thing(s) to look at. Open the screenshots for those slides, fix, rebuild and render again.")
        else:
            print("Result: nothing flagged. Still look at the contact sheet before delivering.")
    sys.exit(1 if (outside or any(c.startswith("error") for c in console)) else 0)


if __name__ == "__main__":
    main()
