# Authoring slides

How a deck source is written: the file shape, the slide contract, every layout,
the shared components, and step reveals. `template/starter.src.html` holds a
working example of everything here; copy slides from it rather than typing
markup from memory.

## Contents

- [The source file](#the-source-file)
- [The slide contract](#the-slide-contract)
- [Layouts](#layouts)
- [Components](#components)
- [Icons](#icons)
- [Step reveals](#step-reveals)
- [Motion helpers](#motion-helpers)
- [Utilities](#utilities)
- [Fitting content on a slide](#fitting-content-on-a-slide)

## The source file

A source is a plain HTML file, saved as `<name>.src.html`. It holds only the
deck's own content. The engine, theme, layouts and icons are added by the build.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Deck title</title>
<meta name="deck:footer" content="Short label shown in the footer">
<!-- all optional -->
<meta name="deck:theme" content="default">
<meta name="deck:variant" content="dark">
<meta name="deck:icons" content="lucide">
<style data-deck> /* deck-wide effects, see custom-slides.md */ </style>
</head>
<body>
<main class="deck">
  <section class="slide" data-layout="title"> ... </section>
  <section class="slide" data-layout="bullets"> ... </section>
</main>
</body>
</html>
```

The stage is 1920 x 1080 px and is scaled to the window, so sizes are written
in px against that stage (2px is 1pt on a standard 13.33in slide).

## The slide contract

```html
<section class="slide" data-layout="two-column" id="optional-id">
  <p class="slide-eyebrow">Optional short kicker</p>
  <h2 class="slide-title">The point of the slide, as a sentence</h2>
  <p class="slide-subtitle">Optional</p>
  <div class="slide-body">
    <!-- a layout's content, or any custom HTML and SVG -->
  </div>
  <aside class="notes"><p>What to say. Never shown to the audience.</p></aside>
</section>
```

- One `<section class="slide">` per slide, directly inside `<main class="deck">`, in order.
- `data-layout` is optional. Without it the slide has the frame (margins, title
  position, footer) and an empty body to compose freely.
- `aside.notes` is required on every slide (the check fails without it). It may
  contain paragraphs and lists.
- Colors, fonts and durations come from theme tokens only (`tokens.md`). Layout
  sizes and positions are free.
- Slide attributes:

| Attribute | Effect |
|---|---|
| `data-tone="inverse"` | Saturated background with light text, as on title slides. Also `surface`, `accent-soft`; `plain` on a title, section or closing slide makes it light. |
| `data-bg="title"`, `"section"`, `"closing"`, `"none"` | Puts the slide on that kind's background, with its margins and text colors; `none` gives a flat slide in a theme whose background is a picture. In a flat theme the three kinds share the title slide's color. |
| `data-bg="<name>"` | A background the theme took from one of the template's other layouts, such as `quote` or `dark-content`. The names are in the theme's `theme.json` under `backgrounds`; the build reports one the theme does not have. |
| `data-align="center"` or `"bottom"` | Vertical position of the body content. |
| `data-footer="off"` | Hides the footer and slide number. `on` shows it where a layout hides it. |
| `data-progress="off"` | Hides the progress bar while this slide is shown. |
| `data-steps="3"` | Declares steps that have no element of their own (for custom slides). |
| `data-notes="none"` | Exempts one slide from the notes check. Use rarely. |
| `id="pricing"` | Lets `deck.html#pricing` link straight to the slide. Must be unique. |

## Layouts

Fifteen layouts. Each name is a `data-layout` value. All are optional.

### title
Opening slide. Inverse tone, no footer.
```html
<section class="slide" data-layout="title">
  <p class="slide-eyebrow">Quarterly review</p>
  <h1 class="slide-title">Short title, three to five words</h1>
  <p class="slide-subtitle">One line that says what the audience will get.</p>
  <ul class="slide-meta"><li>Presenter name</li><li>2 October 2026</li></ul>
</section>
```
The title is very large: keep it under about 40 characters.

### section
Divider between parts. Inverse tone, no footer.
```html
<section class="slide" data-layout="section">
  <p class="section-number">2</p>   <!-- only when sections are a real sequence -->
  <h2 class="slide-title">What changed this quarter</h2>
  <p class="slide-subtitle">Optional line.</p>
</section>
```

### bullets
Title plus a short list. Three to five bullets, each one line or two.
```html
<div class="slide-body">
  <ul>
    <li>First point</li>
    <li>Second point
      <ul><li>One level of nesting is styled; avoid deeper.</li></ul>
    </li>
  </ul>
</div>
```
`<ol>` gives accent numerals. A `<p class="lede">` above the list sets a larger opening line.

### two-column
```html
<div class="slide-body">
  <div class="col"><h3>Left heading</h3> ... </div>
  <div class="col"><h3>Right heading</h3> ... </div>
</div>
```
`data-split="2-1"` or `"1-2"` on the slide makes the columns unequal.
`data-align="center"` centers them vertically.

### big-number
One figure is the point.
```html
<div class="slide-body">
  <p class="big-number" data-count>62%</p>
  <p class="big-number-label">of new customers came from referrals.</p>
  <p class="big-number-context">Up from 41% a year ago. Source: CRM, FY2026.</p>
</div>
```
Keep the figure to about six characters. `data-count` counts up to the written value.

### stats
Two to four figures side by side.
```html
<div class="slide-body">
  <div class="stat">
    <span class="stat-value" data-count>1,284</span>
    <span class="stat-label">active accounts</span>
    <span class="stat-delta is-good">+12% vs last quarter</span>   <!-- optional; is-bad for the wrong direction -->
  </div>
  ...
</div>
```

### cards
Three or four parallel points, each with an optional icon.
```html
<div class="slide-body">
  <article class="card">
    <svg class="icon icon--lg" aria-hidden="true"><use href="#icon-rocket"/></svg>
    <h3>Heading</h3>
    <p>One or two lines.</p>
  </article>
  ...
</div>
```
Cards share one row. For two rows, set `data-cols="3"` (or 2, 4) on the slide.

### chart
The title states the takeaway; the body holds a chart figure. Generate the
figure with `scripts/chart.py` (see `charts-and-diagrams.md`).
`data-split="2-1"` or `"3-1"` adds a `<div class="chart-notes">` column beside it.

### image
Half the slide is a picture that runs to the edge.
```html
<section class="slide" data-layout="image">
  <h2 class="slide-title">...</h2>
  <div class="slide-body"><p>...</p></div>
  <figure class="slide-image">
    <img src="photos/site.jpg" alt="What the picture shows">
    <figcaption>Optional caption or credit</figcaption>
  </figure>
  <aside class="notes">...</aside>
</section>
```
`data-image-side="left"` flips it. `style="--image-width: 40%"` changes the split.
For a picture inside the frame instead, put `<figure class="figure"><img ...><figcaption>...</figcaption></figure>`
in any slide body (`data-fit="cover"` crops to fill).

Image paths are relative to the source file. The build embeds and compresses them.

### quote
```html
<div class="slide-body">
  <blockquote class="quote">The sentence worth pausing on.</blockquote>
  <p class="quote-by">Name <span class="quote-role">Role, organization</span></p>
</div>
```
Only quote real words from a real source. Keep it under about 25 words.

### diagram
A centered inline SVG (`<svg class="diagram">`) or a process row
(`<ol class="flow">`). See `charts-and-diagrams.md`.

### table
```html
<div class="slide-body">
  <table class="table">
    <thead><tr><th></th><th class="is-highlight">Option A</th><th>Option B</th></tr></thead>
    <tbody>
      <tr><th>Row label</th><td class="is-highlight">...</td><td>...</td></tr>
    </tbody>
  </table>
</div>
```
`class="num"` right-aligns numbers. `is-highlight` on one column's cells marks
the recommendation. Up to about five rows and four columns; `data-size="compact"`
on the table fits a couple more.

### timeline
```html
<div class="slide-body">
  <ol class="timeline">
    <li class="timeline-item is-done">
      <span class="timeline-date">March</span>
      <span class="timeline-title">Pilot</span>
      <span class="timeline-text">Two teams, six weeks.</span>
    </li>
    <li class="timeline-item is-current"> ... </li>
    <li class="timeline-item"> ... </li>
  </ol>
</div>
```
Three to five items.

### closing
Last slide. Inverse tone, no footer.
```html
<section class="slide" data-layout="closing">
  <h2 class="slide-title">The one thing to remember</h2>
  <p class="slide-subtitle">Optional line.</p>
  <div class="slide-body">
    <ul class="next-steps">
      <li><svg class="icon" aria-hidden="true"><use href="#icon-calendar"/></svg> Decide by 15 October.</li>
    </ul>
  </div>
</section>
```

### full-bleed
No frame at all: no padding, no title position, no footer. The slide is a blank
1920 x 1080 canvas for custom work. See `custom-slides.md`.

### No layout
A slide without `data-layout` keeps the frame and gives you an empty
`.slide-body` (a column flexbox with a gap). Compose with the utilities below or
with custom markup.

## Components

Usable inside any slide body.

| Component | Markup |
|---|---|
| Callout | `<div class="callout"><svg class="icon">...</svg><div>Text</div></div>`; `data-tone="accent-2"` or `"plain"` |
| Panel | `<div class="panel">...</div>`: a tinted box |
| Tag | `<span class="tag">Beta</span>`; `data-tone="accent"` or `"soft"` |
| Legend | `<ul class="legend"><li class="legend-item series-1"><span class="legend-swatch"></span>Name</li></ul>` |
| Source line | `<p class="source">Source: ...</p>` |
| Lede | `<p class="lede">A larger opening sentence.</p>` |
| Code | `<pre><code>...</code></pre>`, inline `<code>` |

## Icons

```html
<svg class="icon" aria-hidden="true"><use href="#icon-rocket"/></svg>
```

- Find names with `python scripts/find_icon.py "idea"`. Only names it prints exist.
- Sizes: `icon--sm`, default, `icon--lg`, `icon--xl`, `icon--inline` (matches the text).
- Color follows the surrounding text. Modifiers: `icon--accent`, `icon--accent-2`,
  `icon--muted`, `icon--positive`, `icon--negative`. `icon--duo` colors the
  second tone of a two-tone icon.
- `<span class="icon-badge"><svg class="icon">...</svg></span>` puts an icon in a tinted square.
- Never paste or draw an icon inline. If nothing in the set fits, tell the user
  and offer to draw one in the set's style and add it to the library.

## Step reveals

Add `data-step` to any element to hold it back until the presenter advances.

```html
<li data-step>Appears on the first click</li>
<li data-step>Appears on the second</li>
<div data-step="2">Appears together with the second</div>
```

- Unnumbered steps reveal in document order. A number groups elements into one step.
- Going backwards, and print, show every step.
- `data-steps-focus` on the parent dims the steps already seen.
- An element with both `data-step` and `data-anim` plays that animation when revealed.
- The slide carries `data-step-index="N"` and each shown element `.is-step-shown`
  (the latest one `.is-step-current`), for custom styling.

## Motion helpers

```html
<div data-anim="rise">...</div>
<div data-stagger> <div data-anim="rise">1</div> <div data-anim="rise">2</div> </div>
```

`data-anim` values: `fade`, `rise`, `drop`, `from-left`, `from-right`, `zoom`,
`pop`, `bounce`, `wipe`, `grow-up`, `grow-right` (bars), `draw` (SVG lines),
`travel` (along a path, below).
`data-anim-speed="fast"` or `"slow"`; for any other length set
`style="--anim-dur: calc(var(--dur-slow) * 3)"`, and `--anim-delay` to hold it back.
`data-stagger` on a parent delays each child in turn; `style="--i: 3"` sets one
element's place in the sequence by hand.

**Counting.** `data-count` on a number counts up to the value written in the
markup. Text around the number stays (`$4.82M`, `117%`); `data-count-from="9"`
starts somewhere other than zero, so a figure can count down.

**Typing.** `data-type` types an element's text one character at a time.

```html
<h2 class="slide-title" data-type>What would it take to double this?</h2>
<p data-type data-type-speed="60" data-type-caret>Second line, typed after the first.</p>
```

- The text keeps its full size while it types, so nothing on the slide shifts.
  Inline markup (`<em>`, `<strong>`, links) is kept; `<pre>` keeps its spacing.
- Several typed elements on a slide take turns in source order. Inside a
  `data-step` element, typing starts when that step is revealed.
- `data-type-speed` is characters per second (default 42). `data-type-delay`
  is a pause before it starts (a duration or a token such as `--dur-slow`).
  `data-type-caret` keeps the caret blinking after the last character.
- The element fires a `deck:typed` event when it finishes, for a script that
  should act next (see `custom-slides.md`).

**Travelling.** `data-anim="travel"` moves an element along a path of its own
and stops at the end. Give it the path with `offset-path`; in an SVG the path
uses the drawing's coordinates, so it can be the same `d` as a visible line.

```html
<path class="edge" d="M100 300 C 500 0, 1100 0, 1500 300"/>
<circle class="mark" r="18" data-anim="travel"
        style="offset-path: path('M100 300 C 500 0, 1100 0, 1500 300'); --anim-dur: calc(var(--dur-slow) * 3)"/>
```

Add `offset-rotate: auto` to the style to turn the element to face along the path.

Use motion where it does a job: counting the figure that matters, building a
chart in the order of the argument, moving something along a process, one
confident arrival per section. Keep ordinary content slides still; a deck
where everything moves reads as noise. `SKILL.md` has the guidance on how much.

## Utilities

`grid-2`, `grid-3`, `grid-4` (equal columns), `stack` (column with gap), `row`
(horizontal, centered), `fill` (take the remaining space), `center`,
`push-down` (stick to the bottom). Change a gap with `style="--gap: var(--space-5)"`.

Text: `text-xs` to `text-3xl`, `text-muted`, `text-subtle`, `text-accent`,
`text-accent-2`, `text-positive`, `text-negative`, `font-display`, `font-mono`,
`weight-medium`, `weight-bold`, `tabular`, `nowrap`, `balance`.

## Fitting content on a slide

The type is sized to be read from the back of a room, so a slide holds less
than a page does. Working limits:

- Title: one or two lines. State the point, not the topic.
- Bullets: at most five or six, one or two lines each.
- Body text: about 60 words. Detail belongs in the notes.
- Smallest text: `--text-xs` (footers, sources, axis labels). Nothing smaller.

When `render.py` reports overflow, cut words or split the slide. Do not shrink
the type to make it fit.

A theme with a picture background may leave a much narrower text area than the
built-in one (the build says how wide). Plan for it: two columns instead of
four, shorter lines, one idea fewer per slide.
