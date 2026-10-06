#!/usr/bin/env python3
"""Package the skill for installing.

    python tools/package.py              writes dist/dynamic-decks.skill and dist/dynamic-decks.zip

Both files are the same zip archive of the dynamic-decks/ folder. The .skill name
is what the Claude apps recognize as a skill file; the .zip name is for the
skill upload dialog.
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "dynamic-decks"
SKIP_DIRS = {"__pycache__", ".git", "preview"}
SKIP_FILES = {".DS_Store"}


def main() -> None:
    skill_md = SKILL / "SKILL.md"
    if not skill_md.is_file():
        sys.exit("dynamic-decks/SKILL.md not found")
    head = skill_md.read_text(encoding="utf-8").split("---", 2)
    if len(head) < 3 or not re.search(r"^name:\s*dynamic-decks\s*$", head[1], flags=re.M) or "description:" not in head[1]:
        sys.exit("SKILL.md needs frontmatter with name: dynamic-decks and a description")
    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / "dynamic-decks.skill"
    files = sorted(f for f in SKILL.rglob("*") if f.is_file() and not (set(f.parts) & SKIP_DIRS)
                   and f.name not in SKIP_FILES and f.suffix != ".pyc")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, Path("dynamic-decks") / f.relative_to(SKILL))
    shutil.copyfile(target, dist / "dynamic-decks.zip")
    version = re.search(r'^VERSION = "([^"]+)"', (SKILL / "scripts" / "_deck.py").read_text(encoding="utf-8"), flags=re.M)
    print(f"Packaged DynamicDecks {version.group(1) if version else ''}: {len(files)} files, {target.stat().st_size / 1024:.0f} KB")
    print(f"  {target}\n  {dist / 'dynamic-decks.zip'}")

    # keep the ready-to-open example in step with the source
    import os
    import subprocess
    env = dict(os.environ, DYNAMIC_DECKS_HOME=str(dist / ".empty-library"))
    for name in ("showcase", "starter"):
        example = REPO / "examples" / f"dynamic-decks-{name}.html"
        example.parent.mkdir(exist_ok=True)
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(SKILL / "template" / f"{name}.src.html"),
                               "-o", str(example), "--quiet"], env=env)
        print(f"  {example}" + ("" if proc.returncode == 0 else "  (the build reported problems)"))


if __name__ == "__main__":
    main()
