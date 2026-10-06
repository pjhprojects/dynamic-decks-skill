# Contributing

Thanks for wanting to improve DynamicDecks. Issues and pull requests are welcome.

## Before you open a pull request

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python tests/run_all.py
python tools/package.py      # also refreshes examples/dynamic-decks-starter.html
python tools/screenshots.py  # remakes the README pictures; run it when the look changes
```

All tests should pass, and a change to behavior should come with a test for it.
The tests drive the real scripts and a real browser, so they also show how each
feature is meant to work.

## Rules the code follows

These are what keep every deck consistent, portable and restylable. A change
that breaks one of them needs a very good reason.

1. **A built deck is one file that makes no network requests.** Nothing is
   loaded from a CDN, a font service or an image host.
2. **Layouts and components use theme tokens only.** No hard-coded color, font
   or duration in `dynamic-decks/engine/layouts.css` or in the starter deck. A new
   design value becomes a token in `themes/default/theme.css` and a line in
   `reference/tokens.md`.
3. **The engine holds mechanics, not looks.** Its own interface (help panel,
   presenter window, edit mode) has fixed neutral styling so it reads the same
   in every theme.
4. **Every slide has a resting state.** Anything animated must look finished
   with animation off, because print, previews and the overview show that.
5. **Nothing appears on a slide uninvited.** Tools such as edit mode show only
   when the presenter asks for them with a key.
6. **Deck sources stay plain.** The build must not require changes to how
   slides are written, and `unpack.py` must be able to recover a source from
   any built deck.
7. **Scripts run on Python 3.9 with the standard library.** Pillow, Playwright
   and fontTools are optional; a script that needs one says what it skipped.

## Where things are

- `dynamic-decks/SKILL.md` is what the agent reads first. Keep it short, put
  detail in `dynamic-decks/reference/`, and write it for any agent: do not
  name a product or assume one agent's tools.
- `dynamic-decks/template/starter.src.html` is the markup the agent copies
  from. A new layout needs an example slide there.
- `dynamic-decks/template/showcase.src.html` is the sample deck people open
  first and the agent's working examples of dynamic slides. A new showcase
  slide is welcome when it shows a technique the deck does not have yet. It
  must pass the checks with no warnings, use only theme tokens, have a
  complete still frame, and carry the sentence someone could ask for it with.
- `tests/fixtures/` holds a deliberately broken deck, a PowerPoint template and
  a few icons used by the tests.

## Releasing

1. Update `VERSION` in `dynamic-decks/scripts/_deck.py` and add a section to
   `CHANGELOG.md`.
2. Run the tests and `python tools/package.py`, and commit.
3. Tag the commit `v<version>` and push the tag. The release workflow runs the
   tests and attaches `dynamic-decks.skill` and `dynamic-decks.zip` to a GitHub release.

## Licensing of contributions

By contributing you agree that your contribution is released under the
project's [MIT License](LICENSE). Do not add icons, fonts or other material
unless its license allows redistribution, and record it in
`dynamic-decks/NOTICE.md`.
