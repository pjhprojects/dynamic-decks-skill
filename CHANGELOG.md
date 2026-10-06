# Changelog

All notable changes to DynamicDecks are listed here. Versions follow
[semantic versioning](https://semver.org): the number in
`dynamic-decks/scripts/_deck.py` and the release tag are kept the same.

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
