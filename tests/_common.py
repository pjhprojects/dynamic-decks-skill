"""Shared helpers for the DynamicDecks tests.

The tests drive the real scripts and a real browser. They need Python 3.9+,
Playwright with Chromium, and Pillow:

    pip install -r requirements-dev.txt
    python -m playwright install chromium
    python tests/run_all.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "dynamic-decks"
SCRIPTS = SKILL / "scripts"
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "tests" / ".out"
STARTER_SRC = SKILL / "template" / "starter.src.html"
SHOWCASE_SRC = SKILL / "template" / "showcase.src.html"


def run(script: str, *args, env: dict | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run one of the skill's scripts and capture its output."""
    full_env = dict(os.environ)
    # tests never touch a real user library unless they ask for one
    full_env["DYNAMIC_DECKS_HOME"] = str(OUT / "empty-library")
    if env:
        full_env.update(env)
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, env=full_env)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


def build(src: Path, out: Path, *args, env: dict | None = None) -> subprocess.CompletedProcess:
    out.parent.mkdir(parents=True, exist_ok=True)
    return run("build.py", src, "-o", out, *args, env=env)


def starter(name: str = "starter.html") -> Path:
    """The sample deck, built fresh into the test output folder."""
    out = OUT / name
    proc = build(STARTER_SRC, out)
    if not out.is_file():
        raise RuntimeError("could not build the starter deck:\n" + proc.stdout + proc.stderr)
    return out


def showcase(name: str = "showcase.html") -> Path:
    """The showcase deck, built fresh into the test output folder."""
    out = OUT / name
    proc = build(SHOWCASE_SRC, out)
    if not out.is_file():
        raise RuntimeError("could not build the showcase deck:\n" + proc.stdout + proc.stderr)
    return out


def launch(playwright):
    """Chromium, from Playwright's own install or a path given in DYNAMIC_DECKS_CHROMIUM."""
    exe = os.environ.get("DYNAMIC_DECKS_CHROMIUM") or os.environ.get("HTML_DECK_CHROMIUM")
    if exe:
        return playwright.chromium.launch(executable_path=exe)
    try:
        return playwright.chromium.launch()
    except Exception:
        alt = "/opt/pw-browsers/chromium"
        if Path(alt).exists():
            return playwright.chromium.launch(executable_path=alt)
        raise


class Checks:
    """Collects named pass/fail results and prints them as it goes."""

    def __init__(self, title: str):
        self.title = title
        self.results: list[tuple[str, bool]] = []
        print(f"\n== {title}")

    def ok(self, name: str, cond, detail="") -> bool:
        cond = bool(cond)
        self.results.append((name, cond))
        print(("  pass  " if cond else "  FAIL  ") + name + (f"  ::  {detail}" if detail != "" and not cond else ""))
        return cond

    def done(self) -> None:
        bad = [n for n, c in self.results if not c]
        print(f"  {len(self.results) - len(bad)}/{len(self.results)} passed")
        sys.exit(1 if bad else 0)
