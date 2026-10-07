# Changelog

All notable changes to DynamicDecks are listed here. Versions follow
[semantic versioning](https://semver.org): the number in
`dynamic-decks/scripts/_deck.py` and the release tag are kept the same.

## 1.1.0 (2026-10-07)

Branded backgrounds from PowerPoint templates are kept as they were designed.

- **Picture backgrounds.** When a template's background is more than a flat
  color (a photo, a gradient, bands and marks drawn with shapes), `add_theme.py
  from-pptx` keeps it as a picture for each kind of slide: content, title,
  section and closing. With LibreOffice installed the pictures are drawn from
  the template itself, so they are exact. Without it, a photo background is
  taken from the file, a plain gradient is written as CSS, and artwork made of
  shapes is left out and reported.
- **Each picture is measured once.** The theme records the text area (from the
  template's own text boxes, pulled in from artwork along the edges), whether
  text should be dark or light, whether the picture is calm enough to read over
  or needs a panel, and a one-sentence description. Margins, text colors and
  the panel follow from that, so slides written later need not look at the
  picture. `theme.json` holds the measurements under `backgrounds`.
- **Per slide:** `data-bg="title"`, `"section"` or `"closing"` puts any slide
  on that picture with its margins and colors; `data-bg="none"` and any
  `data-tone` give a flat slide.
- **Your own pictures:** `--background content=bg.png` (also `title`,
  `section`, `closing`) on `new`, `from-pptx` and `from-spec`. The largest
  empty part of the picture becomes the text area.
- `--backgrounds auto|always|never` on `from-pptx`, and `--preview` now also
  writes `preview/backgrounds.png`, each picture with its text area outlined.
- **Real contrast check.** `render.py` compares every piece of text with the
  pixels actually behind it (picture, photo or colored shape) and reports text
  that is hard to read there, with a higher bar on a busy patch. `--no-contrast`
  skips it. Decorative text marked `aria-hidden="true"` is left alone.
- New tokens: `--frame-left`, `--frame-right`, `--hero-bottom`, `--bg-image`,
  `--bg-panel`. Themes made with 1.0.0 work unchanged.
- Title slides in a flat brand color: muted text on them now always clears
  4.5:1.

Tested on templates made for the tests (a photo background, shape artwork, a
busy picture), not yet on a wide range of real company templates.

## 1.0.0 (2026-10-06)

First public release. The project was called html-deck while it was being built;
a library folder made under that name (`~/.html-deck`) is still read.

- Slide engine: scaling to a 16:9 stage, keyboard, clicker, click and swipe
  navigation, step reveals, deep links, slide lifecycle events and a resting
  state for every slide.
- Presenting: presenter window with current slide, next slide, notes, timer
  and clock; notes overlay; overview grid; blank screen; light and dark switch;
  PDF export of slides and of slides with notes.
  Printed notes pages carry their own header and footer (print date, deck
  title, page numbers), so Chrome and Edge leave out theirs and the file's
  path is not printed.
- Shortcuts panel on `?` or `H`, from every state and in both windows. It
  marks the presenter window and PDF export as needing the downloaded file,
  and pressing `S` or `P` inside an AI assistant's preview says the same.
- Edit mode on `E`: click an element to copy a reference to it, and
  `locate.py` to resolve a reference to source lines.
- Built-in theme (light and dark) with open-licensed fonts, fifteen layouts,
  shared components, and chart and diagram classes.
- Motion helpers, one attribute each: `data-anim` (twelve entrances, `draw`
  for lines, `travel` along a path), `data-stagger`, `data-count` for numbers
  that count up and `data-type` for text that types itself without shifting
  the layout.
- Showcase deck: seventeen slides that explain the skill and demonstrate
  dynamic slides (typing, counting, a marker travelling a route, a ranking
  that plays, a chart revealed in steps, live sliders, a diagram with traffic,
  a canvas that follows the pointer). Its source ships in the skill as working
  examples to adapt. The starter deck remains the reference for every layout.
- Built-in Lucide icon set with search by meaning.
- Scripts: `build`, `check`, `render`, `chart`, `find_icon`, `locate`, `unpack`,
  `add_theme` (from a PowerPoint template, brand values or a spec) and
  `add_icons` (from a folder of SVGs).
- User themes and icon sets are stored outside the skill, so updates leave
  them alone.
