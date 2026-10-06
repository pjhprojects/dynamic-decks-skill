#!/usr/bin/env python3
"""Draw a chart as themed inline SVG for a slide.

    python scripts/chart.py spec.json                 (prints an HTML fragment)
    python scripts/chart.py spec.json -o chart.html
    python scripts/chart.py --type bar --categories "2023,2024,2025" --values "12,18,27" \\
        --name Revenue --prefix "$" --suffix M --highlight 2025 --animate

Spec (JSON):
    {
      "type": "bar",                      bar | hbar | line | donut
      "categories": ["2023", "2024", "2025"],
      "series": [{"name": "Revenue", "values": [12, 18, 27]}],
      "format": {"prefix": "$", "suffix": "M", "decimals": 0},
      "highlight": "2025",                a category (bar, hbar, donut) or a series name (line)
      "stacked": false,                   bar only
      "area": false,                      line only, single series
      "center_value": "62%", "center_label": "of revenue",     donut only
      "width": 1680, "height": 600,       size of the space the chart will fill, in stage px
      "animate": true,
      "label": "Revenue by year",         read by screen readers
      "source": "Source: finance, FY2025"
    }

The geometry is computed here, so bars, ticks and labels are exact. Colors and
type come from the theme through classes (series-1 ... series-8, chart-bar,
chart-line ...), never from values in this file, so a theme swap restyles the
chart. Paste the output inside a slide body.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path

FS_XS, FS_SM = 24, 30          # default --text-xs / --text-sm of the stage
GAP = 4                        # surface gap between touching marks
RADIUS = 8                     # rounded data end of a bar


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def text_w(s: str, size: float) -> float:
    return len(str(s)) * size * 0.56


def nice_ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v < hi + step * 0.999:
        ticks.append(round(v, 10))
        v += step
    return ticks


class Fmt:
    def __init__(self, spec: dict, values: list[float]):
        f = spec.get("format") or {}
        self.prefix = f.get("prefix", "")
        self.suffix = f.get("suffix", "")
        d = f.get("decimals")
        if d is None:
            d = 0 if all(float(v).is_integer() for v in values) else 1
        self.decimals = int(d)

    def __call__(self, v: float, decimals: int | None = None) -> str:
        d = self.decimals if decimals is None else decimals
        s = f"{abs(v):,.{d}f}"
        return ("-" if v < 0 else "") + self.prefix + s + self.suffix

    def tick(self, v: float, step: float) -> str:
        d = 0 if float(step).is_integer() else max(1, self.decimals)
        return self(v, d)


def bar_path(x: float, y0: float, y1: float, w: float, horizontal: bool = False) -> str:
    """A bar from baseline y0 to value y1, rounded at the value end only."""
    length = abs(y1 - y0)
    r = min(RADIUS, w / 2, length)
    if horizontal:
        # x is the cross position (top), y0/y1 run along the x axis
        a, b = y0, y1
        s = 1 if b >= a else -1
        return (f"M{a:.1f},{x:.1f} H{b - s * r:.1f} Q{b:.1f},{x:.1f} {b:.1f},{x + r:.1f} "
                f"V{x + w - r:.1f} Q{b:.1f},{x + w:.1f} {b - s * r:.1f},{x + w:.1f} H{a:.1f} Z")
    s = -1 if y1 <= y0 else 1
    return (f"M{x:.1f},{y0:.1f} V{y1 - s * r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 - s * r:.1f} V{y0:.1f} Z")


def anim(kind: str, i: int, on: bool) -> str:
    return f' data-anim="{kind}" style="--i:{i}"' if on else ""


def legend(names: list[str], shape: str = "", muted: set[int] | None = None, values: list[str] | None = None,
           column: bool = False) -> str:
    items = []
    for i, n in enumerate(names):
        cls = f"series-{i + 1}" if not muted or i not in muted else "series-neutral"
        sh = f' data-shape="{shape}"' if shape else ""
        val = f' <strong class="tabular">{esc(values[i])}</strong>' if values else ""
        items.append(f'    <li class="legend-item {cls}"><span class="legend-swatch"{sh}></span>{esc(n)}{val}</li>')
    cls = "legend legend--column" if column else "legend"
    return f'  <ul class="{cls}">\n' + "\n".join(items) + "\n  </ul>"


def chart_bar(spec: dict) -> tuple[str, str]:
    cats = [str(c) for c in spec["categories"]]
    series = spec["series"]
    W, H = spec["width"], spec["height"]
    on = spec.get("animate", False)
    stacked = bool(spec.get("stacked")) and len(series) > 1
    hl = spec.get("highlight")
    allv = [v for s in series for v in s["values"]]
    fmt = Fmt(spec, allv)
    if stacked:
        totals = [sum(s["values"][i] for s in series) for i in range(len(cats))]
        lo, hi = 0, max(totals)
    else:
        lo, hi = min(0, min(allv)), max(0, max(allv))
    label_all = len(series) == 1 and len(cats) <= 10
    ticks = nice_ticks(lo, hi, 4)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    if label_all:
        top, bottom = hi * 1.0, lo
        y_min, y_max = bottom, top
        left = 0
    else:
        y_min, y_max = ticks[0], ticks[-1]
        left = max(text_w(fmt.tick(t, step), FS_XS) for t in ticks) + 20
    m_top, m_bottom, m_right = FS_SM + 22, FS_SM + 30, 8
    pw, ph = W - left - m_right, H - m_top - m_bottom

    def y(v):
        return m_top + ph - (v - y_min) / (y_max - y_min or 1) * ph
    band = pw / len(cats)
    n = 1 if stacked else len(series)
    bw = min(96, (band * 0.72 - GAP * (n - 1)) / n)
    group = bw * n + GAP * (n - 1)
    out = []
    if not label_all:
        for t in ticks:
            cls = "chart-axis" if t == 0 else "chart-grid"
            out.append(f'<line class="{cls}" x1="{left:.1f}" x2="{W - m_right:.1f}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
            out.append(f'<text x="{left - 14:.1f}" y="{y(t) + FS_XS * 0.34:.1f}" text-anchor="end">{esc(fmt.tick(t, step))}</text>')
    else:
        out.append(f'<line class="chart-axis" x1="{left:.1f}" x2="{W - m_right:.1f}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    k = 0
    for ci, cat in enumerate(cats):
        gx = left + band * ci + (band - group) / 2
        muted = hl is not None and str(hl) != cat and len(series) == 1
        if stacked:
            acc = 0.0
            for si, s in enumerate(series):
                v = s["values"][ci]
                y0, y1 = y(acc), y(acc + v)
                acc += v
                last = si == len(series) - 1
                top_y = y1 + (0 if last else GAP)
                if y0 - top_y < 1:
                    continue
                d = bar_path(gx, y0, top_y, bw) if last else f"M{gx:.1f},{y0:.1f} V{top_y:.1f} H{gx + bw:.1f} V{y0:.1f} Z"
                out.append(f'<path class="chart-bar series-{si + 1}" d="{d}"{anim("grow-up", ci, on)}>'
                           f'<title>{esc(cat)}, {esc(s["name"])}: {esc(fmt(v))}</title></path>')
            out.append(f'<text class="chart-value" x="{gx + bw / 2:.1f}" y="{y(acc) - 14:.1f}" text-anchor="middle"'
                       f'{anim("fade", ci + 2, on)}>{esc(fmt(acc))}</text>')
        else:
            for si, s in enumerate(series):
                v = s["values"][ci]
                x = gx + si * (bw + GAP)
                cls = f"chart-bar series-{si + 1}" + (" is-muted" if muted else "")
                out.append(f'<path class="{cls}" d="{bar_path(x, y(0), y(v), bw)}"{anim("grow-up", k, on)}>'
                           f'<title>{esc(cat)}{", " + esc(s["name"]) if len(series) > 1 else ""}: {esc(fmt(v))}</title></path>')
                show = label_all or (hl is not None and str(hl) == cat)
                if show:
                    ly = y(v) - 14 if v >= 0 else y(v) + FS_SM + 6
                    out.append(f'<text class="chart-value" x="{x + bw / 2:.1f}" y="{ly:.1f}" text-anchor="middle"'
                               f'{anim("fade", k + 2, on)}>{esc(fmt(v))}</text>')
                k += 1
        if text_w(cat, FS_SM) > band * 0.98:
            print(f"note: the label \"{cat}\" is wider than its bar slot; shorten it or use type hbar", file=sys.stderr)
        out.append(f'<text class="chart-category" x="{left + band * ci + band / 2:.1f}" y="{m_top + ph + FS_SM + 12:.1f}" '
                   f'text-anchor="middle">{esc(cat)}</text>')
    lg = legend([s["name"] for s in series]) if len(series) > 1 else ""
    return lg, "\n    ".join(out)


def chart_hbar(spec: dict) -> tuple[str, str]:
    cats = [str(c) for c in spec["categories"]]
    s = spec["series"][0]
    vals = s["values"]
    W, H = spec["width"], spec["height"]
    on = spec.get("animate", False)
    hl = spec.get("highlight")
    fmt = Fmt(spec, vals)
    left = min(W * 0.36, max(text_w(c, FS_SM) for c in cats) + 24)
    right = max(text_w(fmt(v), FS_SM) for v in vals) + 22
    pw = W - left - right
    band = H / len(cats)
    bh = min(56, band * 0.62)
    hi = max(max(vals), 0) or 1
    out = [f'<line class="chart-axis" x1="{left:.1f}" x2="{left:.1f}" y1="0" y2="{H:.1f}"/>']
    for i, (c, v) in enumerate(zip(cats, vals)):
        top = band * i + (band - bh) / 2
        x1 = left + max(0, v) / hi * pw
        muted = hl is not None and str(hl) != c
        cls = "chart-bar series-1" + (" is-muted" if muted else "")
        mid = top + bh / 2 + FS_SM * 0.34
        out.append(f'<text class="chart-category" x="{left - 18:.1f}" y="{mid:.1f}" text-anchor="end">{esc(c)}</text>')
        out.append(f'<path class="{cls}" d="{bar_path(top, left, x1, bh, horizontal=True)}"{anim("grow-right", i, on)}>'
                   f'<title>{esc(c)}: {esc(fmt(v))}</title></path>')
        out.append(f'<text class="chart-value" x="{x1 + 14:.1f}" y="{mid:.1f}"{anim("fade", i + 2, on)}>{esc(fmt(v))}</text>')
    return "", "\n    ".join(out)


def chart_line(spec: dict) -> tuple[str, str]:
    cats = [str(c) for c in spec["categories"]]
    series = spec["series"]
    W, H = spec["width"], spec["height"]
    on = spec.get("animate", False)
    hl = spec.get("highlight")
    allv = [v for s in series for v in s["values"] if v is not None]
    fmt = Fmt(spec, allv)
    lo, hi = min(allv), max(allv)
    if lo >= 0 and lo < hi * 0.6:
        lo = 0
    ticks = nice_ticks(lo, hi, 4)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    y_min, y_max = ticks[0], ticks[-1]
    direct = len(series) <= 4
    left = max(text_w(fmt.tick(t, step), FS_XS) for t in ticks) + 20
    end_labels = [f"{s['name']}  {fmt(s['values'][-1])}" if len(series) > 1 else fmt(s["values"][-1]) for s in series]
    right = (max(text_w(t, FS_SM) for t in end_labels) + 30) if direct else 16
    m_top, m_bottom = 18, FS_SM + 30
    pw, ph = W - left - right, H - m_top - m_bottom

    def y(v):
        return m_top + ph - (v - y_min) / (y_max - y_min or 1) * ph

    def x(i):
        return left + (pw * i / (len(cats) - 1) if len(cats) > 1 else pw / 2)
    out = []
    for t in ticks:
        cls = "chart-axis" if t == y_min else "chart-grid"
        out.append(f'<line class="{cls}" x1="{left:.1f}" x2="{left + pw:.1f}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text x="{left - 14:.1f}" y="{y(t) + FS_XS * 0.34:.1f}" text-anchor="end">{esc(fmt.tick(t, step))}</text>')
    every = max(1, math.ceil(len(cats) * (max(text_w(c, FS_SM) for c in cats) + 28) / max(1, pw)))
    for i, c in enumerate(cats):
        if i % every and i != len(cats) - 1:
            continue
        if i == len(cats) - 1 and i % every and (len(cats) - 1 - (i // every) * every) * pw / max(1, len(cats) - 1) < text_w(c, FS_SM) + 28:
            continue
        out.append(f'<text class="chart-category" x="{x(i):.1f}" y="{m_top + ph + FS_SM + 12:.1f}" text-anchor="middle">{esc(c)}</text>')
    ends = []
    for si, s in enumerate(series):
        pts = [(x(i), y(v)) for i, v in enumerate(s["values"]) if v is not None]
        muted = hl is not None and str(hl) != s["name"]
        cls = f"series-{si + 1}" + (" is-muted" if muted else "")
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        if spec.get("area") and len(series) == 1:
            out.append(f'<path class="chart-area {cls}" d="{d} L{pts[-1][0]:.1f},{y(y_min):.1f} L{pts[0][0]:.1f},{y(y_min):.1f} Z"'
                       f'{anim("fade", 4, on)}/>')
        out.append(f'<path class="chart-line {cls}" d="{d}"{anim("draw", si, on)}><title>{esc(s["name"])}</title></path>')
        out.append(f'<circle class="chart-dot {cls}" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="9"{anim("pop", si + 8, on)}>'
                   f'<title>{esc(s["name"])}, {esc(cats[-1])}: {esc(fmt(s["values"][-1]))}</title></circle>')
        ends.append([pts[-1][1], si, muted])
    if direct:
        order = sorted(ends)
        for i in range(1, len(order)):
            if order[i][0] - order[i - 1][0] < FS_SM + 8:
                order[i][0] = order[i - 1][0] + FS_SM + 8
        for ly, si, muted in order:
            cls = "chart-series-label" if not muted else "chart-category"
            out.append(f'<text class="{cls}" x="{left + pw + 22:.1f}" y="{ly + FS_SM * 0.34:.1f}"{anim("fade", si + 9, on)}>{esc(end_labels[si])}</text>')
    muted_set = {i for i, s in enumerate(series) if hl is not None and str(hl) != s["name"]}
    lg = legend([s["name"] for s in series], "line", muted_set) if len(series) > 1 else ""
    return lg, "\n    ".join(out)


def chart_donut(spec: dict) -> tuple[str, str]:
    cats = [str(c) for c in spec["categories"]]
    vals = spec["series"][0]["values"]
    if len(cats) > 6:
        print("note: a donut with more than six slices is hard to read; fold the smallest into 'Other'", file=sys.stderr)
    H = spec["height"]
    W = spec["width"] = H          # the donut is square; the legend sits beside it
    on = spec.get("animate", False)
    hl = spec.get("highlight")
    fmt = Fmt(spec, vals)
    total = sum(vals) or 1
    cx = cy = H / 2
    ro, ri = H / 2 - 6, (H / 2 - 6) * 0.64
    out, a0 = [], -math.pi / 2
    for i, (c, v) in enumerate(zip(cats, vals)):
        a1 = a0 + 2 * math.pi * v / total
        large = 1 if a1 - a0 > math.pi else 0
        p = lambda r, a: f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}"  # noqa: E731
        d = (f"M{p(ro, a0)} A{ro:.1f},{ro:.1f} 0 {large} 1 {p(ro, a1)} "
             f"L{p(ri, a1)} A{ri:.1f},{ri:.1f} 0 {large} 0 {p(ri, a0)} Z")
        muted = hl is not None and str(hl) != c
        cls = f"chart-slice series-{i + 1}" + (" is-muted" if muted else "")
        out.append(f'<path class="{cls}" d="{d}"{anim("fade", i, on)}><title>{esc(c)}: {esc(fmt(v))} '
                   f'({v / total * 100:.0f}%)</title></path>')
        a0 = a1
    cv = spec.get("center_value")
    if cv is None and hl is not None and str(hl) in cats:
        cv = f"{vals[cats.index(str(hl))] / total * 100:.0f}%"
    cl = spec.get("center_label") or (str(hl) if hl is not None else "")
    if cv:
        out.append(f'<text class="chart-center-value" x="{cx:.1f}" y="{cy + (4 if cl else 26):.1f}" text-anchor="middle">{esc(cv)}</text>')
    if cl:
        out.append(f'<text class="chart-center-label" x="{cx:.1f}" y="{cy + 44:.1f}" text-anchor="middle">{esc(cl)}</text>')
    muted_set = {i for i, c in enumerate(cats) if hl is not None and str(hl) != c}
    lg = legend(cats, "", muted_set, [f"{v / total * 100:.0f}%" for v in vals], column=True)
    return lg, "\n    ".join(out)


KINDS = {"bar": chart_bar, "hbar": chart_hbar, "line": chart_line, "donut": chart_donut}


def render(spec: dict) -> str:
    kind = spec.get("type", "bar")
    if kind not in KINDS:
        raise SystemExit(f"error: unknown chart type '{kind}'. Use one of: {', '.join(KINDS)}")
    spec.setdefault("width", 1680)
    spec.setdefault("height", 600)
    if not spec.get("categories") or not spec.get("series"):
        raise SystemExit("error: the spec needs 'categories' and at least one entry in 'series'")
    for s in spec["series"]:
        if len(s["values"]) != len(spec["categories"]):
            raise SystemExit(f"error: series '{s.get('name', '')}' has {len(s['values'])} values for {len(spec['categories'])} categories")
    if len(spec["series"]) > 8:
        raise SystemExit("error: more than 8 series. Fold the smallest into 'Other' or split into several charts.")
    lg, body = KINDS[kind](spec)
    label = spec.get("label") or ", ".join(s.get("name", "") for s in spec["series"])
    parts = [f'<figure class="chart-figure" data-kind="{kind}">']
    if lg:
        parts.append(lg)
    parts.append(f'  <svg class="chart" viewBox="0 0 {spec["width"]:g} {spec["height"]:g}" role="img" aria-label="{esc(label)}">\n    {body}\n  </svg>')
    if spec.get("source"):
        parts.append(f'  <figcaption>{esc(spec["source"])}</figcaption>')
    parts.append("</figure>")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Draw a themed SVG chart for a slide.")
    ap.add_argument("spec", nargs="?", help="JSON spec file, or - for stdin")
    ap.add_argument("-o", "--output")
    ap.add_argument("--type", choices=sorted(KINDS))
    ap.add_argument("--csv", help="CSV file: first column categories, other columns one series each (header row names them)")
    ap.add_argument("--categories", help="comma-separated")
    ap.add_argument("--values", action="append", help="comma-separated numbers; repeat for more series")
    ap.add_argument("--name", action="append", help="series name; repeat to match --values")
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--suffix", default=None)
    ap.add_argument("--decimals", type=int, default=None)
    ap.add_argument("--highlight")
    ap.add_argument("--stacked", action="store_true")
    ap.add_argument("--area", action="store_true")
    ap.add_argument("--animate", action="store_true")
    ap.add_argument("--width", type=float)
    ap.add_argument("--height", type=float)
    ap.add_argument("--label")
    ap.add_argument("--source")
    ap.add_argument("--center-value")
    ap.add_argument("--center-label")
    args = ap.parse_args()

    spec: dict = {}
    if args.spec:
        text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
        spec = json.loads(text)
    if args.csv:
        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            rows = [r for r in csv.reader(fh) if r]
        head, data = rows[0], rows[1:]
        spec["categories"] = [r[0] for r in data]
        spec["series"] = [{"name": head[c], "values": [float(r[c].replace(",", "")) for r in data]} for c in range(1, len(head))]
    if args.categories:
        spec["categories"] = [c.strip() for c in args.categories.split(",")]
    if args.values:
        names = args.name or []
        spec["series"] = [{"name": names[i] if i < len(names) else f"Series {i + 1}",
                           "values": [float(v) for v in vals.split(",")]} for i, vals in enumerate(args.values)]
    fmt = spec.setdefault("format", {})
    for key in ("prefix", "suffix", "decimals"):
        if getattr(args, key) is not None:
            fmt[key] = getattr(args, key)
    for key in ("type", "highlight", "width", "height", "label", "source", "center_value", "center_label"):
        if getattr(args, key) is not None:
            spec[key] = getattr(args, key)
    for key in ("stacked", "area", "animate"):
        if getattr(args, key):
            spec[key] = True
    if not spec:
        ap.error("give a spec file, --csv, or --categories with --values")
    out = render(spec)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
        print(f"Chart written to {args.output}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
