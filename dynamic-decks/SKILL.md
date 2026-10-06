---
name: dynamic-decks
description: Build presentations as one self-contained HTML file that opens in any browser offline, with dynamic slides (numbers that count, text that types, parts that move, charts that play, live interactive controls), keyboard and clicker navigation, speaker notes, a presenter window, PDF export, swappable themes, an icon library and themed SVG charts and diagrams. Use this skill whenever the user asks for a presentation, slide deck, slides, pitch deck or talk and has not asked for a PowerPoint, Keynote or Google Slides file, and always when they mention DynamicDecks, a dynamic deck, an HTML deck, HTML slides, animated or interactive slides, a custom slide visual, a presenter view in the browser, or restyling a deck. Also use it to edit or re-theme a deck made with it, to turn a PowerPoint template or brand guide into a deck theme, and to add a custom icon set.
license: MIT. Complete terms in LICENSE.txt; bundled icons and fonts keep their own licenses, listed in NOTICE.md.
---

# DynamicDecks

Produce a presentation as a single `.html` file. The recipient double-clicks it
and presents: no install, no connection. Because the deck is a web page, a
slide can do anything a browser can: count, type, move, play a chart, react to
the presenter. Use that. A deck that could have been a PowerPoint file has
missed the point of this skill.

A deck has five layers. Only the last one is yours to write for each deck:

| Layer | What it is | Where |
|---|---|---|
| Engine | Navigation, scaling, steps, notes, presenter view, print | `engine/` |
| Theme | Every design value, as named tokens; fonts; logo | `themes/<name>/` |
| Icons | The approved icon set | `icons/<name>/` |
| Layouts | Ready-made slide types and components, built from tokens | `engine/layouts.css` |
| **Content** | The slides, their notes, and any per-slide custom code | the deck source you write |

`scripts/build.py` combines them into the one file.

Paths in this document are relative to this skill's folder. Run the scripts
from wherever the deck source is, giving the script's full path, for example
`python <skill folder>/scripts/build.py talk.src.html`. The skill folder may be
read-only; deck sources, built decks and renders belong in the working folder.

## The rules, and why they exist

1. **Write content only. Never edit or copy the engine, layouts or theme into
   a deck.** The build adds them. One shared engine is what makes every deck
   behave the same and lets a fix reach all future decks.
2. **Use theme tokens for every color, font and duration**, including in
   charts, diagrams, inline styles and scripts. A slide with a hand-picked blue
   ignores a theme swap. The check fails on hard-coded colors and fonts.
3. **Compose freely.** Layouts are conveniences, never a requirement. Any slide
   may hold custom HTML, SVG, CSS and script. The constraint is on the
   ingredients, not the composition: that is how unusual slides still look
   like part of the deck.
4. **Every slide looks finished with no animation running.** Animate from a
   start state to the slide's own styles. Print, PDF, previews and backward
   navigation show that resting state.
5. **Icons come from the icon library by name.** If nothing fits, say so and
   offer to draw one in the set's style and add it. Do not paste in or
   substitute a look-alike: mixed icon styles are the first thing that makes a
   deck look assembled from parts.
6. **Nothing loads from the internet.** Images are local files that the build
   embeds; fonts come from the theme. A deck that needs wifi fails at the
   worst moment.
7. **Every slide has speaker notes**, unless the user says not to.

## Workflow for a new deck

### 1. Gather and outline first

Collect the material (documents, data, the user's points) and write the
outline before touching markup: one line per slide giving its point and how
the slide will show it. Slide titles should state the point ("Referrals now
drive most signups"), not name the topic ("Signups"). Mark the slides that
carry the argument and decide what moves on each (see "Make the slides
dynamic" below); the rest can use a plain layout. Opening the template first
pulls the work toward filling layouts instead of making an argument.

Ask only what you cannot infer: audience, length of the talk, and whether a
specific theme should be used. Use the default theme unless the user names one
or their settings do (`python scripts/add_theme.py list`).

### 2. Write the source

Create `<name>.src.html` in the working folder. Read `reference/authoring.md`
for the file shape and each layout's markup, and copy slide patterns from
`template/starter.src.html`, which has a working example of every layout, the
motion helpers, a custom scripted slide and a full-bleed slide.

- Pick icons with `python scripts/find_icon.py "idea" "another idea"`. Use only
  names it prints.
- Make charts with `python scripts/chart.py` and paste the output into the
  slide (`reference/charts-and-diagrams.md`). Use the user's real numbers.
- For a slide no layout fits, or for custom animation, read
  `reference/custom-slides.md` first. It covers scoped CSS and script, the
  lifecycle events and the resting state. `template/showcase.src.html` has a
  working example of each dynamic technique to adapt.
- Token names are in `reference/tokens.md`.
- Put local images next to the source and reference them by relative path.

Write notes as what the presenter would say, two to four sentences per slide.
They are for speaking, so do not repeat the slide text.

### 3. Build

```bash
python scripts/build.py talk.src.html              # writes talk.html and runs the checks
python scripts/build.py talk.src.html --theme acme --variant dark --icons acme
```

The build prints the file size and then the delivery checks. Fix every FAIL
(the messages say how) and rebuild. Read the warnings and act on the ones that
apply. A failed check exits with status 1 even though the file was written.

### 4. Look at every slide

```bash
python scripts/render.py talk.html                 # screenshots, contact sheet, overflow report
```

This opens the deck in a real browser, captures every slide in its resting
state, and reports content that runs off a slide, collides with the footer or
is too small to read, plus any script error or network request. The resting
state is the last frame of each animation, so this also proves the still
version of every dynamic slide is complete. Then open
`talk-render/contact.png` and actually look: the report cannot judge whether a
slide is balanced, a diagram reads correctly, or a label overlaps a line. Open
individual `slide-NN.png` files for anything that looks off, fix, rebuild and
render again. Check the other variant too (`--variant dark`) if the deck may be
shown in it.

When content overflows, cut words or split the slide. Do not shrink type.

If Playwright is not available, say so, and ask the user to page through the
deck themselves before presenting; do not claim the slides were checked visually.

### 5. Deliver

Give the user the single `.html` file. If they want a PDF too:

```bash
python scripts/render.py talk.html --pdf talk.pdf --notes-pdf talk-notes.pdf
```

Keep the `.src.html` in the working folder for revisions, but the built file
alone is enough: it can be unpacked again (see below).

Tell the user, briefly, how to present it:

- Download the file and open it in a browser. A preview pane inside an AI
  assistant shows the slides and most keys work there, but the presenter
  window and PDF export do not: they need the file opened in a real browser.
  Arrow keys, space or a clicker move through it. **F** is full screen.
- **S** opens the presenter window (current slide, next slide, notes, timer).
  Put the slides on the projector and keep that window on the laptop.
- **N** shows notes on the same screen for rehearsing. **O** is an overview. **?** lists every key.
- **P** saves the slides as a PDF (Chrome or Edge give the best result); **Shift+P** prints slides with notes.
- **E** is edit mode, for asking for changes: click any element to copy a
  reference to it, then paste that into a message to you.

And the limits, when relevant: recipients cannot click into a slide to edit it
(changes go through you), some mail systems block `.html` attachments (zip it
or share a link to the file), and it is made for desktop browsers, not phones.

## Editing an existing deck

If the `.src.html` is at hand, edit it and rebuild. If the user brings back
only the built file (a new session, or a deck someone sent them):

```bash
python scripts/unpack.py talk.html          # writes talk.src.html
```

Edit, build, render, deliver as above. Images stay embedded, and if the deck's
theme is not installed here, the build keeps the theme already inside the file.

### When the user pastes an element reference

Every deck has an edit mode for pointing at things. The user presses **E**,
hovers to outline an element, and clicks to copy a reference to it, which they
paste into their message instead of describing the element. Nothing shows on
the slides until E is pressed, so it never gets in the way of presenting:

```
make [slide 7 › card 2 › heading "Clickers and keys" @7.2.2.2] shorter
```

The words are for the person. The quoted text is a cross-check. The part after
`@` is the element's exact position: the slide number, then the index of each
child element on the way down. Resolve it before editing, so the change goes to
that element and not to one that merely looks similar:

```bash
python scripts/locate.py talk.src.html 'the reference, or the whole message'
```

It prints the file, the line range and the markup for each reference in the
text. Run it on the file you are about to edit (unpack a built deck first), and
act on how each one matched:

- `exact match` or `matched by position`: edit those lines.
- `found by its text`: the slide changed since the reference was copied, and
  the element was found again by its text. Check the markup shown is what the
  user means, then edit it.
- `text differs`: something else is at that position now, or a script writes
  that text. Do not guess; show the user what you found and ask.
- `not found`: ask the user to pick the element again in the current file.

A reference to a slide (`[slide 7 "..." @7]`) means the whole slide. A
reference to content a script draws resolves to the nearest element that is in
the source, usually the container the script fills. References go stale once
the deck is rebuilt with structural changes, so resolve each one against the
current file and never reuse line numbers from an earlier turn.

After a change, tell the user which element you changed in their words (the
readable part of the reference), not as a line number.

To restyle a finished deck, rebuild it with a different theme; no slide edits
are needed, and the built file works as input:

```bash
python scripts/build.py talk.html --theme acme -o talk-acme.html
```

## Make the slides dynamic

A deck built here is a web page, so a slide can do anything a browser can.
That is the reason to use this skill instead of making a PowerPoint file, and a
deck of titles and bullets wastes it. For each slide in the outline, ask how
the point could be **shown** rather than stated:

| The point is | Show it by | See in the showcase |
|---|---|---|
| A figure | Counting it up, with its trend drawing beneath | `#numbers` |
| A question, quote or line of code | Typing it out | `#typing` |
| A journey, process or hand-off | Something travelling the route, lighting each stage | `#route`, `#skill` |
| Change over time | A chart that plays through the periods | `#race` |
| An argument with a turn in it | One chart revealed in steps, a click per beat | `#story` |
| A decision that depends on assumptions | Live controls that recalculate on the slide | `#forecast` |
| How a system works | A diagram with traffic moving along its connections | `#system` |
| A mood or a big idea | A full-bleed visual, generative or reactive | `#hero`, `#anything` |

`template/showcase.src.html` holds a working slide for each of these. Read the
ones you need and adapt them; do not paste one in unchanged for content it does
not fit. `reference/custom-slides.md` explains the rules they follow.

How much: in a typical deck, make the three to six slides that carry the
argument dynamic and keep the rest quiet. Give each dynamic slide one moving
idea, and let the motion do a job (direct the eye, show order, show change,
answer a question). Motion that only decorates, the same entrance on every
slide, or several effects competing on one slide tires the room. If the user
asks for a plain deck, make a plain deck; if they ask for more ("make every
image bounce", a showpiece opening), do it fully. That is what this format is
for.

- Ready-made, one attribute each: `data-anim` (including `draw` for lines and
  `travel` along a path), `data-stagger`, `data-count`, `data-type`,
  `data-step` (see `reference/authoring.md`).
- Custom: scoped CSS and script, with a still frame for print and previews
  (see `reference/custom-slides.md`).
- Deck-wide: one rule in `<style data-deck>` reaches every slide.

All of it uses the theme's motion and color tokens, so a showpiece still looks
like part of the deck and follows a theme swap.

## Themes and icon sets

The built-in theme `default` (light and dark) and icon set `lucide` need no
setup. Users can add their own and choose which to use; read
`reference/themes-and-icons.md` before doing any of this:

- **A theme from a PowerPoint template**:
  `python scripts/add_theme.py from-pptx Template.potx --name acme --preview`
- **A theme from a brand guide or description**:
  `python scripts/add_theme.py new --name acme --accent "#E4002B" ... --preview`
- **An icon set from a folder of SVGs**:
  `python scripts/add_icons.py ./svgs --name acme --license "..."`

Each prints what it could not carry over or had to adjust. Relay that list to
the user in plain words, show them the sample deck in their theme, and treat
the first result as a draft to review together. Two things are the user's to
decide: whether their fonts may be embedded in files they share, and whether
their icons may be redistributed. Ask; do not assume.

User themes and icon sets are stored in a library folder outside the skill
(`~/.dynamic-decks`, or `$DYNAMIC_DECKS_HOME`), so updating the skill never touches
them. In a session where that folder does not persist, tell the user and use
one of the options in the reference (the simplest: any deck built with their
theme carries it, and can hand it back).

## Scripts

| Script | Purpose |
|---|---|
| `build.py` | Source or built deck in, one self-contained `.html` out; runs the checks |
| `check.py` | The delivery checks on their own |
| `render.py` | Screenshots, contact sheet, overflow report, PDF and notes PDF (needs Playwright) |
| `chart.py` | Bar, horizontal bar, line and donut charts as themed SVG |
| `find_icon.py` | Search the icon set by meaning; `--check NAME...` confirms names; `--sets` lists sets |
| `unpack.py` | Built deck back to an editable source; `--theme-to` recovers its theme |
| `locate.py` | Resolve element references copied in edit mode to source lines |
| `add_theme.py` | `from-pptx`, `new`, `from-spec`, `check`, `list`, `tokens` |
| `add_icons.py` | Import a folder of SVGs as an icon set; `--catalog` writes a browsable page |

All take `--help`. They need Python 3.9 or later. Pillow (image compression,
contact sheets), Playwright with Chromium (`render.py`) and fontTools (reading
font files for a theme) are optional; each script says what it skipped without
them.

## Reference files

| File | Read it when |
|---|---|
| `reference/authoring.md` | Writing any slide: file shape, the slide contract, all fifteen layouts, components, steps, motion helpers (`data-anim`, `data-count`, `data-type`) |
| `reference/tokens.md` | Styling anything by hand: every token and what it is for |
| `reference/custom-slides.md` | A slide needs custom CSS, script or animation, or is full-bleed |
| `reference/charts-and-diagrams.md` | A slide has a chart, a diagram or a process |
| `reference/themes-and-icons.md` | Adding, choosing or keeping a theme or icon set; settings |
| `template/starter.src.html` | Working markup for every layout, to copy from |
| `template/showcase.src.html` | Working dynamic slides: typing, counting, travel along a path, a chart that plays, a stepped chart, live controls, a diagram with traffic, canvas |
