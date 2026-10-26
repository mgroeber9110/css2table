# css2table

Converts the CSS layout of modern web pages into HTML 4.01 with tables, so that
browsers from around 2001 (IE 5/6, Netscape 4, Opera 5) show a similar layout.
The output contains no JavaScript and only simple inline styles (CSS1).

This is the first prototype of the converter. There is no proxy server yet.

## Approach

css2table **does not compute a layout** and does not use a headless browser.
Instead it translates the geometric constraints of the CSS directly into table
properties. The legacy browser then adapts the tables to the window size and
font size by itself.

1. Parse the HTML with `lxml`.
2. Read CSS from `<style>`, `<link>` and `@import` with `tinycss2`, match rules with
   `cssselect2` and resolve the cascade ourselves (specificity, `!important`,
   inline styles, inheritance, `var()`, `all`, `revert`, media queries for an
   assumed screen width).
3. Decide per element: flex and grid containers become tables; blocks with a
   background, padding or width become single-cell tables; everything else is
   kept (with an HTML4 tag where needed).
4. Output fonts and colors as `<font>`, `bgcolor`, `align` etc., and additionally
   as a `style` attribute for browsers that support CSS1.

| CSS | Table |
| --- | --- |
| `display: flex` (row) | one `<tr>`, one `<td>` per child |
| `flex-direction: column` | one `<tr>` per child |
| `flex: 1`, `flex-grow` | `<td width="x%">` proportionally |
| `width` / `flex-basis` | `<td width>` in px or % |
| `justify-content` | empty spacer cells (`center`, `space-between`, ...) |
| `align-items` / `align-self` | `valign` |
| `flex-wrap: wrap` | lines based on estimated widths, one table per line |
| `gap` | `cellspacing` |
| `grid-template-columns` (px, %, fr, `repeat()`, `minmax()`, `auto-fill`) | column widths; `fr` becomes a percentage |
| `grid-column` / `grid-row` (`span`, line numbers) | `colspan` / `rowspan` |
| `grid-template-areas` / `grid-area` | grid with `colspan` / `rowspan` |
| `max-width` + `margin: 0 auto` | `<table width="…" align="center">` (full width if `max-width` is wider than the screen) |
| `padding` | `cellpadding` (average of the four sides) |
| `border` | `border` + `bordercolor` |
| `background(-color)`, including gradients | `bgcolor` (first color) |
| `color`, `font-family`, `font-size`, `font-weight` | `<font color face size>`, `<b>`, `<i>` |
| `calc()`, `min()`, `max()`, `clamp()` | evaluated; with percentages only the percentage part is kept (`calc(50% - 1rem)` → 50%) |
| `position: fixed` at the top (headers), `position: absolute` | kept in the normal flow |
| `display: none`, off-screen elements (skip links, off-canvas menus), bottom-anchored or full-screen `position: fixed` overlays, `<script>`, `<iframe>`, `<video>`, `<svg>` | dropped |

## Usage

```sh
pip install -e '.[test]'
python -m css2table page.html -o page-legacy.html
python -m css2table page.html --width 640 --encoding iso-8859-1 --base-url https://example.org/
```

- `--width`: assumed screen width in pixels (default 800) for media queries and
  for estimates such as `auto-fill` or `flex-wrap`.
- `--base-url`: makes relative links and images absolute.
- `--encoding`: character set of the output; characters that cannot be encoded
  become `&#…;`.

Linked stylesheets are only loaded from local files relative to the input.

As a library:

```python
from css2table import convert
html4 = convert(open('page.html', 'rb').read(), viewport_width=800)
```

## Examples and tests

`examples/grid.html` and `examples/flex.html` are test pages with typical grid
and flexbox layouts; `examples/out/` contains the converted versions.

Saved real-world pages go in `testpages/` (not checked in, see
[testpages/README.md](testpages/README.md)).

```sh
python -m pytest
python tools/testpages.py
```

## Known limitations

- No JavaScript: content that is only created by scripts is missing.
- `flex-wrap` and `auto-fill` rely on estimated widths; without known widths
  everything stays on one line.
- `gap` becomes `cellspacing` and therefore also appears at the table edges.
- Margins between blocks are ignored; `padding` is a single value per box.
- `position: absolute`, `transform`, floats of blocks (except as `align`) and
  pseudo-elements (`::before`) are not reproduced. Whether a positioned element
  is off-screen is a heuristic (large negative offsets, `translate(±100%)`,
  `clip`, `opacity: 0`).
- Dropdown menus that are hidden only via `:hover` or JavaScript remain visible.
- A `max-width` smaller than the screen width becomes a fixed pixel width.
