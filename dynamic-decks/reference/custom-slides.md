# Custom slides and animation

When no layout fits, a slide can hold any HTML, SVG, CSS and script. Three
rules keep such a slide part of the deck:

1. **Build from the theme.** Colors, fonts and timing come from tokens
   (`tokens.md`), so the slide follows a theme swap.
2. **Stay inside the slide.** Its CSS and script are scoped to it and cannot
   touch other slides or the engine.
3. **Finish at rest.** With no animation running, the slide must look complete.
   Print, PDF, the overview, the presenter's next-slide preview, backward
   navigation and reduced-motion all show that resting state.

## Contents

- [Scoped CSS](#scoped-css)
- [The resting state](#the-resting-state)
- [Scoped script](#scoped-script)
- [The deck object](#the-deck-object)
- [Events](#events)
- [Multi-step custom slides](#multi-step-custom-slides)
- [Full-bleed slides](#full-bleed-slides)
- [Deck-wide effects](#deck-wide-effects)
- [Canvas](#canvas)
- [Interactive slides](#interactive-slides)
- [Recipes](#recipes)
- [Mistakes the check catches](#mistakes-the-check-catches)

## Scoped CSS

Put a `<style data-slide-scope>` inside the slide. The engine wraps it so it
only reaches that slide.

```html
<section class="slide" id="funnel">
  <h2 class="slide-title">...</h2>
  <div class="slide-body"> <div class="funnel">...</div> </div>
  <aside class="notes">...</aside>
  <style data-slide-scope>
    .funnel { display: grid; gap: var(--space-2); }
    .funnel > div { background: var(--color-accent); border-radius: var(--radius-md); }
    & { --local-gap: var(--space-5); }            /* & is this slide itself */
    &.is-entered .funnel > div { animation: funnel-in var(--dur-base) var(--ease-out) backwards; }
    @keyframes funnel-in { from { transform: scaleX(0); } }
  </style>
</section>
```

- Selectors match elements inside the slide. `&` is the slide element.
- State classes sit on the slide, so write `&.is-entered ...`, never `.is-entered ...`.
  - `&.is-entered`: the slide is current (start entrance animation here)
  - `&[data-step-index="2"]`: the slide is on step 2
- `@keyframes` names are shared by the whole deck. Prefix them with the slide's
  id (`funnel-in`) so two slides never collide. The engine's own are `deck-*`.
- Scoped rules outrank the layouts, so they can restyle the frame of their own slide.

## The resting state

Write the slide so that it looks finished with no animation at all. Then add
motion that animates **from** a start state **to** that finished look.

```css
/* right: the element's own style is the final frame */
&.is-entered .bar { animation: bar-in var(--dur-slow) var(--ease-out) backwards; }
@keyframes bar-in { from { transform: scaleY(0); } }

/* wrong: the final look exists only at the end of the animation */
.bar { transform: scaleY(0); }
&.is-entered .bar { animation: bar-grow 1s forwards; }
```

Use `backwards` (or `both`) so the start state also covers any delay. Do not
use `forwards`: at rest the engine switches animation off, and the slide would
show the hidden start state.

Looping animation (a pulse, a drift) is fine. At rest it simply stops on the
element's own style.

## Scoped script

Put a `<script data-slide-scope>` inside the slide. The engine runs it once at
load, as a function, with two values available: `slide` (this slide's element)
and `deck` (the API below). Variables stay private to the slide.

```html
<script data-slide-scope>
  const dots = slide.querySelectorAll('.dot');

  // 1. Set up the finished frame straight away.
  layout(1);

  // 2. Animate when the slide becomes current.
  slide.addEventListener('deck:enter', () => {
    deck.loop(slide, (elapsed) => {
      const p = Math.min(1, elapsed / deck.ms('--dur-slow'));
      layout(p);
      return p < 1;            // returning false ends the loop
    });
  });

  // 3. Show the finished frame whenever the engine asks for rest.
  slide.addEventListener('deck:rest', () => layout(1));

  function layout(progress) { /* position the dots for 0..1 */ }
</script>
```

- Look elements up with `slide.querySelector(...)`, never `document.querySelector(...)`.
- Read colors and sizes from the theme: `deck.token('--color-accent')`.
- Anything that uses frames or timers needs a `deck:rest` handler that draws
  the finished frame. The check fails without one.
- The script runs in every window that shows the deck (audience, presenter
  previews), so keep it self-contained and cheap. No network calls, no storage.

## The deck object

| Member | What it does |
|---|---|
| `deck.token(name)` | Value of a theme token, for example `deck.token('--chart-1')` |
| `deck.ms(nameOrValue)` | A duration in milliseconds: `deck.ms('--dur-slow')` |
| `deck.animate(el, keyframes, options)` | Web Animations with token names allowed for `duration`, `delay` and `easing`. Skipped at rest, cancelled on leave, defaults to `fill: 'backwards'`. |
| `deck.loop(slide, fn)` | Calls `fn(elapsedMs, deltaMs)` every frame until it returns `false` or the slide is left. Never runs at rest. |
| `deck.after(slide, delay, fn)` | A timer that is cleared when the slide is left. `delay` may be a token. |
| `deck.isRest(slide)` | True when the slide must not animate |
| `deck.index`, `deck.step`, `deck.total` | Current position |
| `deck.go(i, step)`, `deck.next()`, `deck.prev()` | Navigation |

`deck.animate` is the simplest route for one-off moves, and it needs no
`deck:rest` handler because cancelling returns the element to its own style:

```js
slide.addEventListener('deck:enter', () => {
  slide.querySelectorAll('.chip').forEach((chip, i) => {
    deck.animate(chip, [{ opacity: 0, transform: 'translateY(40px)' }, {}],
      { duration: '--dur-base', easing: '--ease-spring', delay: i * deck.ms('--stagger') });
  });
});
```

## Events

Dispatched on the slide element. They bubble, so `<script data-deck>` can
listen on `document`.

| Event | When | `event.detail` |
|---|---|---|
| `deck:enter` | The slide became current and may animate | `{ step, total, direction }` |
| `deck:rest` | Show the final frame now, with no motion (print, previews, overview, going back, reduced motion) | `{ step, total }` |
| `deck:step` | The step index was set, including right after enter or rest | `{ step, total, direction }` |
| `deck:leave` | The slide is no longer current. Loops, timers and `deck.animate` calls are already stopped. | |
| `deck:typed` | Dispatched on an element with `data-type` when its last character has appeared | |

A slide receives either `deck:enter` or `deck:rest` when shown, never both.

## Multi-step custom slides

For a diagram that builds over several clicks, declare the number of steps and
respond to them.

```html
<section class="slide" data-steps="3" id="pipeline">
  ...
  <style data-slide-scope>
    .stage { opacity: 0.25; transition: opacity var(--dur-base) var(--ease-out); }
    &[data-step-index="1"] .stage:nth-child(-n + 1),
    &[data-step-index="2"] .stage:nth-child(-n + 2),
    &[data-step-index="3"] .stage { opacity: 1; }
  </style>
</section>
```

At rest the slide is put on its last step, so the last step must be the
complete picture. A script can do the same with the `deck:step` event.

## Full-bleed slides

`data-layout="full-bleed"` removes the padding, the title position and the
footer. The slide is a positioned 1920 x 1080 box; place content with CSS grid
or absolute positions in stage px.

```html
<section class="slide" data-layout="full-bleed" data-tone="inverse" id="opening">
  <div class="hero">...</div>
  <aside class="notes">...</aside>
  <style data-slide-scope>
    & { display: grid; place-items: center; }
    .hero { font-family: var(--font-display); font-size: var(--text-display); }
  </style>
</section>
```

Decoration that runs past the slide edge is clipped. Mark it `data-bleed` so
`render.py` does not report it as overflow.

`render.py` also compares each piece of text with the pixels really behind it
(a picture background, a photo, a colored shape) and reports text that is hard
to read there. Move the text, or put a surface behind it. Large, faint text
that is decoration and not reading matter (a watermark year, a ghost numeral)
should carry `aria-hidden="true"`; the check leaves it alone.

In a theme whose background is a picture, the artwork is described in the
theme's `theme.json` (`backgrounds`, one `description` and one `safe` text area
per kind of slide). Read it before composing by hand, keep text inside the
frame, and use `var(--frame-left)` and `var(--frame-right)` rather than
`var(--frame-x)` when you position against a margin.

## Deck-wide effects

One rule in `<style data-deck>` in the head reaches every slide.

```html
<style data-deck>
  /* every image bounces in */
  .slide.is-entered img { animation: deck-bounce var(--dur-slow) var(--ease-bounce) backwards; }
</style>
```

The engine's keyframes can be reused by name: `deck-fade`, `deck-rise`,
`deck-drop`, `deck-from-left`, `deck-from-right`, `deck-zoom`, `deck-pop`,
`deck-bounce`, `deck-wipe`, `deck-grow-up`, `deck-grow-right`, `deck-draw`.
Deck-wide script goes in `<script data-deck>` and receives `deck`.

A theme can be nudged for one deck the same way, by overriding tokens:
`<style data-deck> :root { --dur-slide: 0ms; } </style>`.

## Canvas

Canvas draws with its own colors and fonts, so read them from the theme each
time you draw. That keeps the slide right after a variant switch.

```js
const cv = slide.querySelector('canvas');
const ctx = cv.getContext('2d');
function draw(p) {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = deck.token('--color-accent');
  ctx.font = `${deck.token('--weight-bold')} ${deck.token('--text-md')} ${deck.token('--font-display')}`;
  // ...
}
draw(1);
slide.addEventListener('deck:enter', () => deck.loop(slide, (t) => { const p = Math.min(1, t / deck.ms('--dur-slow')); draw(p); return p < 1; }));
slide.addEventListener('deck:rest', () => draw(1));
```

Give the canvas explicit `width` and `height` attributes in stage px. Prefer
SVG where it can do the job: it prints sharp and themes through classes.

## Interactive slides

A click anywhere on a slide advances the deck. Clicks on links, buttons, form
controls and media do not. For other interactive content, add `data-interactive`
to the element (or to the whole slide) so clicks stay with it. Keyboard
navigation keeps working.

State a control changes (a slider's value, a toggled view) belongs to that
window; it is not sent to the presenter window. Whatever the markup shows
before anyone touches it is the resting frame, so make that the view you would
want in a PDF.

`deck.setVariant('dark')` switches the theme variant for the whole deck, the
same as the T key.

## Recipes

`template/showcase.src.html` has a complete, working slide for each of these.
Find the slide by its id, read it, and adapt it to the content.

| Technique | Slide id | How it works |
|---|---|---|
| A word that retypes itself; a cursor dragging a slider while a figure follows | `hero` | One `deck.loop` rewrites the text and derives the slider position from elapsed time; a single function redraws everything from that position, and the still frame calls it with the resting value |
| Dots flowing between steps | `skill` | A looping CSS animation on `left`, with the dots' own position as the still frame |
| Counting figures over drawn trends | `numbers` | `data-count` and `data-anim="draw"`, no script |
| Typing, then building | `typing` | `data-type`; a `deck:typed` listener adds a class that the slide's CSS transitions from |
| A marker riding a route | `route` | `getPointAtLength` in a `deck.loop`; stops switch on as the marker passes |
| A ranking that plays | `race` | Values interpolated per frame; rows re-sort with a CSS transition on `translate` |
| One chart, several clicks | `story` | `data-step` on groups of bars, with `&[data-step-index="0"]` restyling the first frame |
| Live sliders | `forecast` | `input` listeners redraw an SVG path; no timers, so no `deck:rest` handler |
| Traffic on a diagram | `system` | A script adds dots to each edge; CSS moves them with `offset-path` |
| A canvas that follows the pointer | `anything` | Seeded positions so the still frame is the same everywhere; colors read from tokens each frame |
| Buttons that switch the theme | `theme` | `deck.setVariant`, with a `MutationObserver` so the buttons follow the T key |

Three habits all of them share:

- **Draw the last frame first.** Each script calls its draw function once with
  the finished state before anything animates, and again on `deck:rest`.
- **Derive every frame from elapsed time,** not from the previous frame, so the
  animation is the same at any frame rate and can be shown at any moment.
- **Use the engine's timers** (`deck.loop`, `deck.after`, `deck.animate`),
  which stop by themselves when the slide is left.

## Mistakes the check catches

| Report | Fix |
|---|---|
| hard-codes a color or font | Use a token or a class (`series-1`, `node--accent`, `text-accent`) |
| selector ".is-entered ..." never matches | Write `&.is-entered ...` |
| relies on 'forwards' | Animate from a start state, use `backwards` |
| no 'deck:rest' handler | Add one that draws the finished frame |
| `<style>` or `<script>` needs data-slide-scope | Add the attribute |
| loads from the internet | Use a local file; the build embeds it |

A genuine exception, such as another company's logo drawn in its own colors,
can opt out with `data-raw="reason"` on the element. The reason is printed in
the report. Do not use it to get around the theme.
