# Changelog

All notable changes to DynamicDecks are listed here. Versions follow
[semantic versioning](https://semver.org): the number in
`dynamic-decks/scripts/_deck.py` and the release tag are kept the same.

## 1.4.0 (2026-10-07)

Fixes from the first real company template to go through the import. Its
content layout was not recognized, so nothing was read for content slides, and
the workarounds that followed caused the rest. Each was reproduced on a
template generated to have the same construction (`template-custom.pptx`).

- **Layouts with no type are recognized.** Company templates are often built
  from custom layouts that do not say what they are. The content, title and
  section layouts are now also found by name, and the content layout, failing
  that, by what is on it and how many slides use it. `--layout KIND=NAME`
  settles it by hand, and the report says how each layout was matched. When no
  content layout is found the report says IMPORT INCOMPLETE and lists the
  layouts, instead of a quiet note.
- **A title box that is not a title placeholder is read as the title.** A text
  placeholder named "Title", or a short box above all the others, gives the
  title its position, size, weight and color, and is no longer mistaken for
  the body (which had turned bullets off and taken the wrong text size).
- **A picture supplied alongside a template keeps the template's text boxes.**
  `--background` with `from-pptx` used to discard them and guess the largest
  empty area, which put titles below a rule. With no template, a rule across
  the top of a supplied picture is now read as the line under the title.
- **Rules no longer get a shadow.** LibreOffice draws a theme shadow on a
  shape even when the shape's own empty effect list switches it off, as
  PowerPoint honors. The import corrects such shapes before drawing.
- **Title and section slides keep the template's text color.** White on a
  brand orange stays white, where the import used to choose black for scoring
  higher on contrast, and to darken the orange. The report gives the contrast
  figure, and `--contrast-floor` keeps the render check from reporting the
  brand's own pairing.
- **Fixed: a theme could be recorded under the name `--text-lg`.** A loop
  variable overwrote the theme's name whenever the template's body text was
  outside 24 to 32pt.
- **Stand-in fonts.** For Arial, Helvetica, Times New Roman, Courier New,
  Calibri and Cambria, an embedded open-licensed font with the same letter
  widths (Liberation Sans, Arimo, Carlito and so on) now stands in on its own
  and the original is no longer reported as missing. `--font-alias` names any
  other stand-in.
- **Cards under a rule.** A theme whose template draws a rule under the title
  sets `--card-rule: none`, since the line on top of each card read as a
  second rule.
- **Compare before writing slides.** `--preview` now writes
  `preview/compare.png`: the template's own slides, drawn with sample text,
  beside the same slides in the theme. The skill's instructions say to look at
  it first and to fix the import, not the theme or the slides, when the two
  differ.

Not done from the same report: a render check for "title below a rule" and
one for soft-edged or doubled lines. With the causes fixed they would have
nothing to catch, and the comparison sheet shows both at a glance.

## 1.3.0 (2026-10-07)

Two faults reported from a real company template, reproduced on templates
made to match the report, and what they showed about the approach.

- **Background pictures were soft.** They were drawn at 1920 x 1080, the same
  pixel count as the stage, so on a dense display or full screen they were
  stretched, and text and thin rules in the artwork blurred. Pictures are now
  drawn at 3840 x 2160. Line artwork, flat shapes and lettering are stored
  without loss (such pictures are a few KB); only photographs are compressed,
  lightly. The build no longer recompresses a theme's pictures. A picture
  supplied with `--background` keeps its own size up to 3840 px wide.
- **A title was pushed off the band or rule it belongs with.** The text area
  was the template's boxes, but then "corrected" against the picture: a title
  box lying on a band was treated as blocked and moved below it, and the body
  followed the title instead of starting at its own box, so text could run
  through a rule under the title. Now the template's text boxes are the
  authority:
  - The title box and the text box are kept apart. The title has an area as
    tall as its box and sits in it as the template has it (`--title-min`,
    `--title-anchor`); the body starts where the text box starts.
  - A title on a band or tint stays there, in a color measured from what is
    under the title box. Body color comes from under the text box.
  - When the template draws something under the title, `--title-max` records
    how much room a title has, the report says how many lines fit, and
    `render.py` reports a title that runs into it.
  - A box is pulled in only when its edge runs a little way under artwork at
    the slide's side, and the report says so. A layout with no text boxes gets
    the built-in margins. Only pictures supplied by hand are searched for
    their empty part.
  - Positions now allow for the inset PowerPoint keeps inside a text box, so
    text starts where it does in PowerPoint.
- **Nothing the template draws is dropped.** Small artwork (a logo, a thin
  rule) used to be left out when it covered under 2.5% of the slide, which
  moved the logo to the footer and lost the rule. It is now kept, where the
  template has it. Hairlines are detected on the full-size picture. For the
  old result, a flat theme with a dark variant and the logo in the footer,
  pass `--backgrounds never`.
- The report says when a background contains text set in a font that is not
  installed where the theme is made, since LibreOffice then draws it in a
  stand-in.
- `--preview` outlines the title area and the text area separately.

A theme made again from the same template will change: sharper pictures,
titles placed as the template has them, and, where the template has a logo or
rule on an otherwise flat slide, a picture theme with one look instead of a
flat theme with two. Themes already made keep working as they are; their
pictures are no longer recompressed when a deck is built. The built-in theme
renders pixel for pixel as before.

## 1.2.0 (2026-10-07)

A theme made from a PowerPoint template now carries what the slide master
holds besides colors, fonts and backgrounds.

- **Several slide masters.** A file can hold more than one (light and dark,
  sub-brands, leftovers from pasted slides). The theme is made from the one
  most slides use; the report lists them all, and `--master` takes a number
  or a name to pick another.
- **Title alignment.** Left, centered or right is read for each kind of slide
  and becomes `--title-align`, which moves the eyebrow, title and subtitle
  together. PowerPoint's own default master centers titles, so themes from
  many templates now do too. Title and section slides also take where their
  text sits top to bottom (`--hero-justify`).
- **Footer and slide number.** Their side, height, text size and color follow
  the master's footer boxes (`--footer-size`, `--footer-offset`,
  `--footer-color`, and a few rules for the arrangement). A template that
  shows no slide number or footer text gets a theme that hides it
  (`--footer-number`, `--footer-label`), and the report says why.
- **Bullets.** The first two levels take the template's bullet: a dot, square,
  dash, another character or none, with its color and indent
  (`--bullet-*`, `--bullet-2-*`). Common symbol-font bullets are understood.
- **Body text.** The template's body size is reported and the type scale leans
  toward it by at most 10%; it is not copied, because these layouts hold more
  on a slide than one PowerPoint text box. Line spacing is carried.
- **More layouts as named backgrounds.** Every other layout with a look of its
  own (a quote slide, a dark content slide, a divider) becomes a background a
  slide asks for with `data-bg="name"`, with its own margins and colors.
- **Smaller decks.** Each background picture is now in a deck once, however
  many kinds of slide share it, and pictures a deck does not use are left out.
  The build reports a `data-bg` name the theme does not have.
- The two-content layout's gap becomes `--column-gap`.
- New flags on the create commands: `--title-align`, `--bullet`,
  `--slide-number`, `--footer-label`; on `from-pptx` also `--master` and
  `--no-extra-backgrounds`.

The built-in theme renders pixel for pixel as in 1.1.0, and themes made with
1.0 or 1.1 keep working: every new token has a default equal to the old
behavior. A theme made again from the same template with 1.2 will look
different where the template says so (centered titles, dot bullets, the footer).

Still tested only on templates made for the tests. Not carried: the date box,
picture bullets, the logo's position on the master, table and chart styles,
and PowerPoint's own placeholder arrangements.

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
