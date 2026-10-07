# Themes, icon sets and settings

The skill works with no setup: a built-in theme (`default`, light and dark) and
a built-in icon set (`lucide`). Users can add their own themes and icon sets
and choose which to use. Read this when a user wants to add, change or choose one.

## Contents

- [Where things live](#where-things-live)
- [Choosing a theme or icon set for a deck](#choosing-a-theme-or-icon-set-for-a-deck)
- [Adding a theme from a PowerPoint template](#adding-a-theme-from-a-powerpoint-template)
- [What a theme takes from the slide master](#what-a-theme-takes-from-the-slide-master)
- [Backgrounds that are pictures](#backgrounds-that-are-pictures)
- [Adding a theme from a brand guide or description](#adding-a-theme-from-a-brand-guide-or-description)
- [What a theme is](#what-a-theme-is)
- [Adding an icon set](#adding-an-icon-set)
- [Settings](#settings)
- [Keeping a theme or icon set between sessions](#keeping-a-theme-or-icon-set-between-sessions)

## Where things live

| | Built-in (ships with the skill) | Added by the user |
|---|---|---|
| Themes | `<skill>/themes/default/` | `<library>/themes/<name>/` |
| Icon sets | `<skill>/icons/lucide/` | `<library>/icons/<name>/` |
| Settings | `<skill>/settings.json` | `<library>/settings.json` |

`<library>` is `$DYNAMIC_DECKS_HOME` when that is set, otherwise `~/.dynamic-decks`.
A library made when the skill was called html-deck (`~/.html-deck`, `$HTML_DECK_HOME`)
is still read until a `~/.dynamic-decks` folder exists; rename the folder to move over.
It is separate from the skill folder on purpose: updating or reinstalling the
skill replaces only the built-in items. A name in the library wins over the
same name in the skill.

`python scripts/add_theme.py list` and `python scripts/find_icon.py --sets`
show what is installed.

## Choosing a theme or icon set for a deck

In order of precedence:

1. A flag: `build.py --theme acme --variant dark --icons acme`
2. The deck source: `<meta name="deck:theme" content="acme">`, `deck:variant`, `deck:icons`
3. Settings (`"theme"`, `"variant"`, `"icons"`)
4. For icons only: the set the theme names in its `theme.json`, then `lucide`

`--theme` also accepts a path to a theme folder. When a user asks for a theme
or icon set by name for one deck, put it in the deck's metas so rebuilds keep it.

To restyle a finished deck, rebuild it with another theme. The input can be the
source or the built file:

```bash
python scripts/build.py talk.html --theme acme -o talk-acme.html
```

## Adding a theme from a PowerPoint template

```bash
python scripts/add_theme.py from-pptx Template.potx --name acme --preview
python scripts/add_theme.py from-pptx Template.pptx --name acme --fonts ./brand-fonts --logo logo.svg --logo-dark logo-white.svg
```

It reads the template's theme colors, heading and body fonts, the title
position, size and weight on the slide master, and a logo if the master has
exactly one small picture. A background that is more than a flat color is kept
as a picture (see [Backgrounds that are pictures](#backgrounds-that-are-pictures)).
From those it writes the full token set, derives the other variant (dark from
light, or light from dark) when the background is flat, and prints a list of
what to review. `--preview` builds the sample deck in the new theme and writes
contact sheets for each variant.

Then:

1. Read the "What to review" list and relay it to the user in plain words.
2. Look at the contact sheets. Fix what is off by editing `theme.css` by hand:
   it is ordinary CSS with every value named.
3. Run `python scripts/add_theme.py check acme` after editing.
4. Show the user the sample deck and ask whether it matches their template.

What a template cannot give, and what happens instead:

| Gap | What the theme does |
|---|---|
| Fonts are named, not included | The name goes first in the font stack, so it shows where installed. Elsewhere the built-in font is used. Pass `--fonts <folder>` to embed real font files. |
| Font licensing | Embedding puts the font inside every deck that is shared. Only embed fonts whose license allows that; ask the user. Files flagged by their maker as not embeddable are skipped. |
| Picture, gradient or shape artwork backgrounds | Kept as a picture per kind of slide. Exact with LibreOffice installed; without it, shape artwork is left out and reported. |
| Tints and shades of theme colors | The plain color is used. |
| Motion, spacing, corner style | The built-in values. `--shape sharp|soft|round` sets corners. |
| A 4:3 template | Decks are always 16:9; positions are scaled. |
| A dark version of the logo | The same logo is used on dark slides unless `--logo-dark` is given. |

A PowerPoint template never converts perfectly. Say so, and treat the first
result as a draft to review with the user.

## What a theme takes from the slide master

The slide master, and the layouts under it, hold more of a brand than its
colors. `from-pptx` reads the following once and stores each as a token or a
rule in the theme, so slides follow it without anyone opening the template again.

**Which master.** A file can hold several slide masters: a light and a dark
version, one per sub-brand, or leftovers that came along when slides were
pasted in from another deck. The theme is made from the master most slides
use, or the first when the file has no slides (a pure template). When there is
more than one, the report lists them all with how many layouts and slides each
has, and says which was used and why. To use another:

```bash
python scripts/add_theme.py from-pptx Template.pptx --name acme-dark --master 2
python scripts/add_theme.py from-pptx Template.pptx --name acme-dark --master "Corporate Dark"
```

A wrong master is the usual reason a new theme has colors or a background the
user does not recognize, so read that line of the report first.

## Backgrounds that are pictures

When a template's background is more than one flat color (a photo, a gradient,
bands or marks drawn with shapes, a logo on the master), the theme keeps it as
a **picture** instead of trying to rebuild it. A rebuilt background is always a
little wrong; a picture of it is the brand's own artwork, untouched. There is
one picture per kind of slide: `content`, `title`, `section`, `closing`.

How the picture is made:

- **With LibreOffice** (`soffice` on the PATH, or `DYNAMIC_DECKS_SOFFICE=/path/to/soffice`):
  an empty slide of each kind is drawn at 1920 x 1080. Everything the template
  puts on that kind of slide is in the picture, the logo included, so the theme
  does not place the logo a second time.
- **Without it**: a background that is one picture is taken straight from the
  file, and a plain gradient is written as CSS. Artwork made of shapes cannot be
  read this way and is left out. The report says so; install LibreOffice and run
  the command again for an exact copy.
- A flat background stays a flat color. Small marks (under 2.5% of the slide)
  are left out and reported; `--backgrounds always` keeps them, and
  `--backgrounds never` turns pictures off altogether.

Each picture is then **measured once**, so nobody has to look at it again when
writing slides. The result is in `theme.json` under `backgrounds`:

| Field | Meaning |
|---|---|
| `picture` | The file in the theme's `backgrounds/` folder, or the CSS gradient |
| `safe` | The text area as `[x, y, width, height]` on the 1920 x 1080 stage: where the template's own title and text boxes sit, pulled in from artwork along the edges |
| `ink`, `text` | Dark or light text, and the exact color, chosen from the pixels under the text area |
| `calm` | `true` when text can sit straight on the picture; `false` when it is too busy |
| `panel` | For a busy picture: the color and strength of the panel the theme puts behind the text |
| `description` | One sentence on where the artwork is, for composing a slide by hand |
| `from`, `drawn_by_libreoffice` | The template layout it came from, and how it was read |

The theme turns those into rules, so the ordinary layouts need nothing from you:

- The content picture sets `--bg-image`, the margins (`--frame-left`,
  `--frame-right`, `--frame-top`, `--frame-bottom`) and the text and background
  colors for the whole deck. A theme on a picture has one look: no dark variant
  is derived.
- Title, section and closing slides each get a rule in the theme's Decor
  section with their picture, margins and colors. A template with no closing
  layout uses the title's.
- A busy picture gets `--bg-panel`, a translucent panel over the text area.
  The rule that draws it is in the theme's Decor and uses `.slide::before`, so
  in such a theme a custom slide's own decoration needs an element of its own.

After creating such a theme:

1. Run with `--preview` and open `preview/backgrounds.png`: every picture with
   its text area outlined. Compare it with the template, and show the user.
2. Look at each picture and rewrite its `description` in `theme.json` in your
   own words: what must not be covered (a face, a product, a logo), where the
   quiet space is.
3. Read the notes. A narrow text area ("1005px of width for text") means fewer
   columns and shorter lines on every content slide of every deck in this theme.

When writing slides in such a theme:

- Slides that use a layout follow the margins on their own.
- `data-bg="title"` (or `section`, `closing`) puts any slide on that picture
  with its margins and colors. `data-bg="none"` gives a flat slide, and so does
  any `data-tone` other than `plain`.
- For a custom slide, read the `description` first and keep text inside the
  frame. Anything positioned by hand may land on the artwork.
- `render.py` compares every piece of text with the pixels really behind it and
  reports the ones that are hard to read. Move the text; do not recolor it.

To supply pictures yourself, with a template or without one:

```bash
python scripts/add_theme.py new --name acme --accent "#E4002B" \
    --background content=bg.png --background title=cover.jpg --preview
```

`--background KIND=FILE` works on `from-pptx`, `new` and `from-spec` (in a spec:
`"backgrounds": {"content": "bg.png"}`). A supplied picture has no text boxes
to go by, so its largest empty part becomes the text area; a picture with no
empty part gets the usual margins and a panel. Pictures that are not 16:9 are
cropped to fit.

Pictures are embedded in every deck built with the theme. The report gives the
size they add, typically 50 to 300 KB.

## Adding a theme from a brand guide or description

Read the brand guide (or the description), pick out the few base values, and
let the script expand them:

```bash
python scripts/add_theme.py new --name acme \
    --bg "#FFFFFF" --text "#1B1B1B" --accent "#E4002B" --accent2 "#00539B" \
    --chart "#E4002B,#00539B,#7A7A7A,#F2A900" \
    --font-display "Montserrat" --font-body "Open Sans" --fonts ./fonts \
    --logo logo.svg --shape sharp --preview
```

Only `--accent` is required. `--inverse-bg` sets the background of title and
section slides (default: the accent). For more control, write a JSON spec and
use `from-spec`; the keys are `name`, `label`, `colors` (`bg`, `text`, `accent`,
`accent2`, `chart`, `inverse_bg`, `title`), `fonts` (`display`, `body`, `mono`,
`dir`), `frame` (`x`, `top`, `title_size`, `title_weight`), `shape`, `logo`
(`light`, `dark`), `icons`, `dark` (false to skip the second variant),
`backgrounds` (`content`, `title`, `section`, `closing`: a picture file each).

Colors that would be unreadable are adjusted and listed in the review notes,
so tell the user when a brand color was changed and why.

## What a theme is

A folder with:

```
themes/acme/
  theme.css     1 fonts (@font-face)  2 tokens on :root  3 variants  4 decor
  theme.json    name, variants, default variant, icon set, logo files, backgrounds
  fonts/        font files, with their license text
  logo.svg      optional; logo-dark.svg for dark slides
  backgrounds/  optional; a picture per kind of slide
```

- **Tokens** are the contract; `tokens.md` lists them and
  `add_theme.py tokens` prints them. A theme may define a subset: anything
  missing falls back to the built-in theme's value, and the build says which.
- **Variants** override color tokens only:
  `:root[data-variant="dark"] { --color-bg: ...; }`. List them in `theme.json`.
- **Decor** is free CSS for the frame, written with tokens: a rule beside
  titles, a different footer, the logo in a corner. Example:
  `.slide-title::after { content: ""; display: block; width: var(--space-7); height: var(--stroke-bold); margin-top: var(--space-3); background: var(--color-accent); }`
- **Fonts**: the build embeds only the faces a deck needs (by family, italic
  use and character range), so a theme can carry many weights cheaply.
- A theme changes the look, not the structure. If a brand needs the title
  somewhere else or a different arrangement, that is decor or a custom slide,
  and takes design work.

## Adding an icon set

```bash
python scripts/add_icons.py ./svgs --name acme --license "Company icons, internal use" --set-default
python scripts/add_icons.py ./svgs --name acme --tags tags.json --strip-prefix "ic_" --two-tone
```

Each SVG is cleaned: every color becomes `currentColor` so the theme colors it,
scripts and styles and ids are removed, and the canvas is normalized to a
`viewBox`. The set is stored apart from every other set, with a searchable
index and a `catalog.html` to browse. The import prints what it skipped,
what it removed (gradients, text, embedded images), and which icons to look at.

- `--tags` takes a JSON object of icon name to keywords, which makes
  `find_icon.py` far better at finding icons by meaning. Without it, search
  uses the file names.
- `--two-tone` keeps a second color where an icon uses exactly two; it is
  colored by `--icon-secondary` (`class="icon icon--duo"` uses the second accent).
- Record a `--license`. Icons are embedded in every deck that uses them, so
  the user must be allowed to redistribute them. That is the user's call; ask.
- Sets are never mixed by default, so styles stay consistent. If the active
  set lacks an icon, say so and offer to draw one in its style. The setting
  `"icon_fallback": "default"` lets the build borrow from `lucide` instead.
- A theme can name its icon set in `theme.json` (`"icons": "acme"`), so a
  theme swap also swaps icon style. That only works when both sets use the
  same icon names.
- `python scripts/add_icons.py --catalog lucide -o lucide-catalog.html` writes a
  browsable page of any installed set, the built-in one included.

To add one hand-drawn icon to a user's set, save it as an SVG in their icon
folder and run the import again on the whole folder.

## Settings

`<library>/settings.json` overrides `<skill>/settings.json`:

| Key | Meaning | Default |
|---|---|---|
| `theme` | Theme for new decks | `default` |
| `variant` | Variant for new decks | the theme's own default |
| `icons` | Active icon set | the theme's choice, then `lucide` |
| `icon_fallback` | `none`, or `default` to borrow missing icons from `lucide` | `none` |
| `notes` | `required`, or `optional` to stop the check failing on missing notes | `required` |
| `compress_images`, `max_image_px`, `image_quality` | Image embedding | `true`, `2400`, `82` |

`--set-default` on `add_theme.py` and `add_icons.py` writes the user's
settings file. To change another setting, edit that file.

## Keeping a theme or icon set between sessions

On a user's own computer the library folder persists, so nothing more is needed.

In a cloud or sandboxed session the library folder may not survive the session.
Tell the user, and offer one of these:

- **Carry it in a deck.** Every built deck contains its theme. From any deck
  built with the theme: `python scripts/unpack.py old-deck.html --theme-to themes/acme`,
  then `build.py --theme themes/acme`. Rebuilding or editing a built deck needs
  nothing at all: when its theme is not installed, the build keeps the theme
  already inside it.
- **Keep the folder.** Give the user the theme (or icon set) folder as a zip
  to attach next time, and write it back into the library.
- **Bake it into the skill.** Copy the skill folder, run the add script with
  `--into <that copy>`, set it as the default in the copy's `settings.json`,
  repackage, and have the user save the new version. A later skill update
  would need the same step again, so prefer the library where it persists.
