# Charts and diagrams

Both are inline SVG, drawn with classes that take their look from the theme.
Nothing is loaded from a chart library, so they stay sharp, restyle with the
theme, and work offline.

## Contents

- [Choosing a form](#choosing-a-form)
- [chart.py](#chartpy)
- [Rules for any chart](#rules-for-any-chart)
- [Drawing a chart by hand](#drawing-a-chart-by-hand)
- [Diagrams](#diagrams)
- [Process rows](#process-rows)

## Choosing a form

| The point is | Use |
|---|---|
| One number | The `big-number` or `stats` layout, not a chart |
| Comparing a few categories | `bar` (up to about 8), or `hbar` when labels are long or it is a ranking |
| Change over time | `line` |
| Parts of a whole, up to five parts | `donut`, or a stacked `bar` to compare wholes |
| Precise values across two dimensions | A `table` |

Put the takeaway in the slide title ("Referrals now drive most signups"), and
let the chart show the evidence for it.

## chart.py

Computes the geometry (scales, ticks, bar sizes, label positions) and prints an
HTML fragment to paste into a slide body. Prefer it to hand-placed coordinates:
arithmetic done by a script is exact.

```bash
python scripts/chart.py --type bar --categories "2023,2024,2025" --values "12,18,27" \
    --name Revenue --prefix "$" --suffix M --highlight 2025 --animate

python scripts/chart.py --type line --csv signups.csv --suffix "%" --animate --width 1200 --height 540
python scripts/chart.py spec.json -o chart.html
```

A JSON spec handles anything the flags do not:

```json
{
  "type": "bar",
  "categories": ["North", "South", "East", "West"],
  "series": [{"name": "2025", "values": [42, 31, 27, 18]},
             {"name": "2026", "values": [48, 39, 25, 26]}],
  "format": {"prefix": "$", "suffix": "M", "decimals": 0},
  "stacked": false,
  "highlight": "South",
  "width": 1680, "height": 600,
  "animate": true,
  "label": "Revenue by region, 2025 and 2026",
  "source": "Source: finance, FY2026"
}
```

| Type | Notes |
|---|---|
| `bar` | Vertical. One series: every bar is labeled and the gridlines are dropped. Several series: grouped, or `"stacked": true`. |
| `hbar` | Horizontal, one series, value at each bar tip. Sort the data yourself. |
| `line` | One or more series. Ends are labeled directly for up to four series. `"area": true` shades a single series. |
| `donut` | One series, up to six slices. `center_value` and `center_label` fill the middle. |

`highlight` keeps one category (or one line) in color and turns the rest
neutral: the standard way to point at the number that matters.

`width` and `height` are the space the chart will fill, in stage px. A full-width
chart under a one-line title is about 1680 x 600. Beside a notes column
(`data-split="3-1"`) the chart area is about 1200 wide; with `"2-1"` about 1080.
Subtract about 50 from the height when there is a legend, and again for a source line.

`animate` adds the motion helpers (bars grow, lines draw, labels fade in).

Use the real data the user gave you. Never invent figures; if the data is
missing, ask for it or mark the chart clearly as an illustration.

## Rules for any chart

- **Series color is fixed and ordered.** `series-1`, `series-2`, ... in order.
  Never skip, cycle or reorder them, and never use more than eight; fold the
  rest into "Other" or split into two charts.
- **One y-axis.** Two measures with different scales get two charts.
- **Text is ink, not series color.** Labels and values use the text classes; a
  colored mark beside them carries identity.
- **A legend for two or more series**, plus direct labels where they fit. No
  legend for a single series: the title says what it is.
- **Label selectively.** Every bar when there are few; otherwise the endpoint,
  the extreme, or the highlighted one.
- **Bars start at zero.**
- **Status colors are not series colors.** `--color-positive` and
  `--color-negative` mean good and bad, and always travel with a word or icon.

## Drawing a chart by hand

For a form `chart.py` does not cover (scatter, waterfall, annotated custom
charts), draw the SVG yourself with the same classes. Compute coordinates with
a short script rather than by eye.

```html
<figure class="chart-figure">
  <svg class="chart" viewBox="0 0 1680 600" role="img" aria-label="What the chart shows">
    <line class="chart-grid" x1="80" x2="1680" y1="300" y2="300"/>
    <line class="chart-axis" x1="80" x2="1680" y1="540" y2="540"/>
    <path class="chart-bar series-1" d="..." data-anim="grow-up"/>
    <path class="chart-line series-2" d="..." data-anim="draw"/>
    <circle class="chart-dot series-2" cx="..." cy="..." r="9"/>
    <text class="chart-value" x="..." y="..." text-anchor="middle">42</text>
    <text class="chart-category" x="..." y="..." text-anchor="middle">North</text>
  </svg>
  <figcaption>Source: ...</figcaption>
</figure>
```

| Class | For |
|---|---|
| `chart-bar`, `chart-line`, `chart-area`, `chart-dot`, `chart-slice` | Marks. Add `series-N` for color, `is-muted` to de-emphasize. |
| `chart-grid`, `chart-axis` | Gridlines and the baseline |
| `chart-value` | A number on or beside a mark (`chart-value--on-mark` inside a filled mark) |
| `chart-category`, `chart-series-label` | Axis categories; a series name at a line's end |
| `chart-annotation`, `chart-annotation-line` | A callout and its leader line |
| `chart-center-value`, `chart-center-label` | The middle of a donut |

Mark sizes at stage scale: lines 5px (the default of `chart-line`), dots radius
9, bars up to about 96 wide with an 8px rounded top and a 4px gap between
neighbors. Plain `<text>` in a chart is `--text-xs`; do not set smaller.

Set the `viewBox` to the pixel size of the space the chart fills, so type in
the chart matches type on the slide.

## Diagrams

`<svg class="diagram" viewBox="0 0 1680 600">` inside a `diagram` layout (or any
slide body). Draw boxes, lines and labels with these classes:

| Class | Look |
|---|---|
| `node` | Quiet box. Variants: `node--accent`, `node--accent-2`, `node--soft`, `node--outline`, `node--ghost` (dashed) |
| `edge` | Connecting line. Variants: `edge--accent`, `edge--subtle` |
| `arrowhead` | Fill for a marker's path (`arrowhead--accent`) |
| `label` | Text. Variants: `label--title`, `label--large`, `label--muted`, `label--small`, `label--on-accent` |
| `mark`, `mark--2` | Small filled emphasis shapes |

Arrowheads are SVG markers. Marker ids are shared across the deck, so prefix
them with the slide id:

```html
<defs>
  <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path class="arrowhead" d="M0,0 L10,5 L0,10 Z"/>
  </marker>
</defs>
<rect class="node" x="0" y="0" width="420" height="120" rx="14"/>
<text class="label label--title" x="32" y="52">Collect</text>
<text class="label label--muted" x="32" y="90">Forms and imports</text>
<path class="edge" d="M440,60 H600" marker-end="url(#flow-arrow)" data-anim="draw"/>
```

Sizing text in SVG: `label--title` is `--text-base` and `label` is `--text-sm`.
Allow about 0.55 of the font size per character when sizing a box, and leave
32px of padding. Check the render: SVG text does not wrap.

Animate a build with `data-anim` on groups (`from-left`, `pop`), `data-anim="draw"`
on edges, and `data-stagger` on the parent group. For a diagram that builds over
several clicks, use `data-step` on the groups.

## Process rows

For a simple left-to-right process, no coordinates are needed:

```html
<ol class="flow">
  <li class="flow-step"><svg class="icon" aria-hidden="true"><use href="#icon-search"/></svg><h3>Find</h3>One line of detail.</li>
  <li class="flow-step"><h3>Fix</h3>One line of detail.</li>
  <li class="flow-step is-accent"><h3>Ship</h3>One line of detail.</li>
</ol>
```

Three to five steps. Arrows are drawn between them automatically.
