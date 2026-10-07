# Theme tokens

Every design value a slide may use. Write `var(--token)` in CSS, or
`deck.token('--token')` in a slide script. `python scripts/add_theme.py tokens`
prints the full list with the built-in values.

Using only these is what lets a theme swap restyle a custom slide. A hard-coded
color, font or duration ignores the swap, and the check fails on colors and fonts.

## Color

| Token | Use |
|---|---|
| `--color-bg` | Slide background |
| `--color-surface`, `--color-surface-2` | Panels, table stripes, quiet fills |
| `--color-text` | Main text and strong shapes |
| `--color-text-muted` | Secondary text |
| `--color-text-subtle` | Captions, footers, axis labels |
| `--color-border` | Hairlines, rules, outlines |
| `--color-accent` | The brand color: emphasis, key marks, eyebrows |
| `--color-accent-contrast` | Text placed on an accent fill |
| `--color-accent-soft` | Tinted background for highlights |
| `--color-accent-2`, `--color-accent-2-soft` | Second accent, for contrast with the first |
| `--color-positive`, `--color-negative`, `--color-warning` | Good, bad, caution. Pair with a word or icon, never color alone. |
| `--color-inverse-*` | Used by inverse slides. Do not use directly: set `data-tone="inverse"` and the tokens above re-map inside that slide. |

Need a tint or a transparent version? Mix tokens, do not invent a color:
`color-mix(in srgb, var(--color-accent) 30%, transparent)`.

## Charts

`--chart-1` to `--chart-8` are the series colors, in a fixed order chosen so
neighbors stay distinct for color-blind readers. Use them in order and never
reorder or cycle them. `--chart-neutral` de-emphasizes, `--chart-grid`,
`--chart-axis` and `--chart-label` draw the scaffolding. In markup, use the
classes `series-1` to `series-8` rather than the tokens.

## Type

| Token | Use |
|---|---|
| `--font-display` | Titles, big numbers, headings |
| `--font-body` | Everything else |
| `--font-mono` | Code |
| `--weight-regular`, `--weight-medium`, `--weight-bold`, `--weight-display` | Weights |
| `--text-xs`, `--text-sm` | Footers and sources; captions and labels |
| `--text-base`, `--text-md` | Body text; bullets and small headings |
| `--text-lg`, `--text-xl` | Subtitles and ledes; large statements |
| `--text-2xl`, `--text-3xl` | Quotes; section titles |
| `--text-display`, `--text-mega` | The deck title; a single huge figure |
| `--leading-tight`, `--leading-snug`, `--leading-normal` | Line height for display, short text, paragraphs |
| `--tracking-display`, `--tracking-tight`, `--tracking-normal` | Letter spacing |

## Space and frame

`--space-1` (8px) to `--space-8` (128px): the spacing scale. Use it for gaps,
padding and offsets so custom slides share the deck's rhythm.

`--frame-x`, `--frame-top`, `--frame-bottom` are the slide margins;
`--title-gap` the space under the title; `--title-size`, `--title-weight`,
`--title-color`, `--title-measure` shape the slide title. `--title-align` is
`start`, `center` or `end`: it aligns the eyebrow, title and subtitle together,
and works in both `text-align` and `align-self`, so a custom heading can follow
the theme with `text-align: var(--title-align)`. `--hero-justify`
(`flex-start`, `center`, `flex-end`) is where the text block sits top to
bottom on title and section slides.

`--frame-left` and `--frame-right` are the side margins on their own. They
equal `--frame-x` unless the theme's background has artwork down one side, so
use these two when placing something against a margin by hand. `--hero-bottom`
is the space under the text on title and section slides, and
`--section-number-gap` the space between a section's number and its title
(`auto` pins the number to the top of the slide).

## Background

Set by the theme, not by slides. `--bg-image` is the picture or gradient behind
a slide (`none` in a flat theme) and `--bg-panel` the translucent panel behind
the text when that picture is too busy to read over. A slide chooses with an
attribute instead: `data-bg="title"`, `"section"`, `"closing"` or `"none"`.

## Shape

`--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-pill`;
`--stroke-hair`, `--stroke-thin`, `--stroke-base`, `--stroke-bold` (line
weights for rules, diagram edges and chart lines); `--shadow-sm`, `--shadow-md`.

## Icons

`--icon-sm`, `--icon-md`, `--icon-lg`, `--icon-xl` (sizes), `--icon-stroke`
(line weight of outline icons).

## Motion

| Token | Use |
|---|---|
| `--dur-fast` | Small state changes |
| `--dur-base` | Most entrances |
| `--dur-slow` | Large or dramatic moves, line drawing |
| `--dur-slide` | The cross-fade between slides |
| `--dur-count` | Count-up length |
| `--stagger` | Delay between items in a cascade |
| `--ease-out` | Entrances (the default) |
| `--ease-in-out` | Moves that start and end on screen |
| `--ease-standard` | Neutral transitions |
| `--ease-spring` | A slight overshoot |
| `--ease-bounce` | A drop that settles |

Longer or shorter timing is fine when it is built from these:
`calc(var(--dur-slow) * 2)`, `calc(var(--stagger) * 4)`.
