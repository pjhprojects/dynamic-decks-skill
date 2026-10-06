#!/usr/bin/env python3
"""Regenerate the pictures the README uses, from the showcase deck.

    python tools/screenshots.py            writes docs/images/*.png and demo.gif
    python tools/screenshots.py --no-gif   skips the animated demo

Needs Playwright with Chromium and Pillow. The animated demo also needs ffmpeg
on the PATH; without it the demo is skipped and the still pictures are written.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "dynamic-decks"
OUT = REPO / "docs" / "images"
sys.path.insert(0, str(REPO / "tests"))

from _common import launch  # noqa: E402

STAGE = {"width": 960, "height": 540}


def at(page, target):
    """Go to [slide, step] and play the entrance. slide: a number (1-based) or an id; step: how many steps to show."""
    return page.evaluate("""([s, step]) => {
        const i = typeof s === 'number' ? s - 1 : Deck.slides.findIndex(x => x.id === s);
        if (Deck.index === i) Deck.go(i === 0 ? 1 : 0);
        Deck.go(i, step);
        return i;
    }""", target)


# ---- the animated demo: (slide, seconds, steps shown on arrival, what happens while it is up) ----
def clicks(*times):
    """Press the right arrow at the given seconds."""
    pending = list(times)

    def hook(page, elapsed):
        while pending and elapsed >= pending[0]:
            pending.pop(0)
            page.keyboard.press("ArrowRight")
    return hook


def drag_growth(page, elapsed):
    """Sweep the growth slider up and back down."""
    import math
    value = 6.5 + 3.5 * math.sin(max(0.0, elapsed - 0.5) * 1.5) if elapsed > 0.5 else 6.5
    page.evaluate("""v => { const el = document.querySelector('.fc-growth'); el.value = Math.round(v * 2) / 2;
        el.dispatchEvent(new Event('input', { bubbles: true })); }""", value)


def sweep_pointer(page, elapsed):
    """Carry the pointer across the canvas slide in a slow arc."""
    import math
    page.mouse.move(520 + 300 * math.sin(elapsed * 1.1), 200 + 110 * math.cos(elapsed * 1.7))


DEMO = [
    ("hero", 3.4, 99, None),
    ("skill", 3.6, 99, None),
    ("numbers", 2.4, 99, None),
    ("typing", 5.4, 99, None),
    ("route", 5.0, 99, None),
    ("race", 7.8, 99, None),
    ("story", 5.0, 0, clicks(0.9, 2.2, 3.5)),
    ("forecast", 4.6, 99, drag_growth),
    ("system", 2.6, 99, None),
    ("anything", 4.0, 99, sweep_pointer),
]


def build(tmp: Path) -> Path:
    deck = tmp / "showcase.html"
    proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"),
                           str(SKILL / "template" / "showcase.src.html"), "-o", str(deck)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(proc.stdout + proc.stderr)
    return deck


def ready(page):
    page.wait_for_function("!!window.Deck")
    page.evaluate("document.fonts.ready")


def contact_sheet(browser, url: str, target: Path):
    import io
    from PIL import Image, ImageDraw
    ctx = browser.new_context(viewport={"width": 960, "height": 540})
    page = ctx.new_page()
    page.goto(url)
    ready(page)
    page.evaluate("Deck.rest(true)")
    count = page.evaluate("Deck.total")
    shots = []
    for n in range(1, count + 1):
        page.evaluate("n => Deck.go(n - 1)", n)
        page.wait_for_timeout(120)
        shots.append(Image.open(io.BytesIO(page.screenshot())))
    ctx.close()
    cols, gap, top = 6, 14, 26
    w, h = 400, 225
    rows = -(-count // cols)
    sheet = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * (h + top + gap) + gap), "#16181D")
    draw = ImageDraw.Draw(sheet)
    for i, shot in enumerate(shots):
        x = gap + (i % cols) * (w + gap)
        y = gap + (i // cols) * (h + top + gap)
        draw.text((x, y + 4), str(i + 1), fill="#C9CCD6")
        sheet.paste(shot.resize((w, h), Image.LANCZOS), (x, y + top))
    sheet.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(target, optimize=True)


def themes(browser, url: str, target: Path, slide: str = "race"):
    """The same slide in the light and the dark variant, side by side."""
    from PIL import Image
    import io
    ctx = browser.new_context(viewport={"width": 960, "height": 540})
    page = ctx.new_page()
    page.goto(url)
    ready(page)
    halves = []
    for variant in ("light", "dark"):
        page.evaluate("v => { Deck.rest(true); Deck.setVariant(v); }", variant)
        at(page, [slide, 99])
        page.wait_for_timeout(200)
        halves.append(Image.open(io.BytesIO(page.screenshot())))
    ctx.close()
    gap = 16
    sheet = Image.new("RGB", (960 * 2 + gap * 3, 540 + gap * 2), "#16181D")
    sheet.paste(halves[0], (gap, gap))
    sheet.paste(halves[1], (960 + gap * 2, gap))
    sheet.save(target, optimize=True)


def presenter(browser, url: str, target: Path, slide: str = "route"):
    ctx = browser.new_context(viewport={"width": 1100, "height": 619})
    page = ctx.new_page()
    page.goto(url)
    ready(page)
    page.evaluate("Deck.rest(true)")
    at(page, [slide, 99])
    page.evaluate("Deck.rest(false)")
    with ctx.expect_page() as pop:
        page.keyboard.press("s")
    view = pop.value
    view.wait_for_function("!!window.Deck")
    view.set_viewport_size({"width": 1100, "height": 619})
    view.wait_for_timeout(6500)                      # let the route finish, so the picture shows the whole slide
    view.screenshot(path=str(target))
    ctx.close()


def edit_mode(browser, url: str, target: Path):
    ctx = browser.new_context(viewport={"width": 1100, "height": 619})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.goto(url + "#14")
    ready(page)
    page.wait_for_timeout(1200)
    page.keyboard.press("e")
    box = page.evaluate("""() => {
        const h = [...document.querySelectorAll('.slide.is-active h3')].find(e => e.textContent.includes('Clickers'));
        const r = h.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2];
    }""")
    page.mouse.move(*box)
    page.mouse.click(*box)
    page.wait_for_timeout(250)
    page.screenshot(path=str(target))
    ctx.close()


def demo(browser, url: str, target: Path, tmp: Path, fps: int = 10) -> bool:
    """Play DEMO with motion on, one screenshot per frame, and make a GIF."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("  ffmpeg not found: skipped demo.gif")
        return False
    frames = tmp / "frames"
    frames.mkdir()
    ctx = browser.new_context(viewport=STAGE)
    page = ctx.new_page()
    page.goto(url)
    ready(page)
    page.mouse.move(-10, -10)
    page.wait_for_timeout(400)
    count = 0
    for slide, seconds, step, hook in DEMO:
        at(page, [slide, step])
        started = time.monotonic()
        for i in range(int(seconds * fps)):
            wait = started + i / fps - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if hook:
                hook(page, time.monotonic() - started)
            page.screenshot(path=str(frames / f"{count:04d}.png"))
            count += 1
    ctx.close()
    palette = tmp / "palette.png"
    src = ["-framerate", str(fps), "-i", str(frames / "%04d.png")]
    look = "scale=720:-1:flags=lanczos"
    subprocess.run([ffmpeg, "-y", "-v", "error", *src, "-vf", f"{look},palettegen=max_colors=64:stats_mode=diff", str(palette)], check=True)
    subprocess.run([ffmpeg, "-y", "-v", "error", *src, "-i", str(palette), "-lavfi",
                    f"{look}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", str(target)], check=True)
    return True


def main():
    ap = argparse.ArgumentParser(description="Regenerate the README pictures from the showcase deck.")
    ap.add_argument("--no-gif", action="store_true", help="skip the animated demo")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix="dynamic-decks-shots-") as tmp_name, sync_playwright() as p:
        tmp = Path(tmp_name)
        url = build(tmp).as_uri()
        browser = launch(p)
        contact_sheet(browser, url, OUT / "slides.png")
        themes(browser, url, OUT / "themes.png")
        presenter(browser, url, OUT / "presenter.png")
        edit_mode(browser, url, OUT / "edit-mode.png")
        if not args.no_gif:
            demo(browser, url, OUT / "demo.gif", tmp)
        browser.close()
    for f in sorted(OUT.iterdir()):
        print(f"  {f.relative_to(REPO)}  {f.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
