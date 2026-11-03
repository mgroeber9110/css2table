# Test pages

Saved copies of real web pages (HTML and CSS only) used to check the
converter. Each page lives in its own subfolder, as the browser stores it with
"Save page as":

    testpages/tagesschau/tagesschau.de.html
    testpages/tagesschau/tagesschau.de_files/main-….css

The pages themselves are protected by copyright and are therefore not checked
in (see `.gitignore`). Only this file is in the repository.

```sh
python tools/testpages.py      # convert all pages, output in testpages/out/
python -m pytest tests/test_testpages.py
```

For each page, `tools/testpages.py` shows the run time, size, number of tables,
images kept, and two text measures:

- **Text**: the share of the words visible in the original that still appear in
  the converted page. Visibility follows the converter's own rules, so this
  measures what the layout conversion loses and should stay close to 100%.
- **Hidden**: the share of words that CSS does not hide with `display: none` or
  `visibility: hidden` but that the converter drops as hidden anyway (skip
  links, screen reader text, off-canvas menus, overlays). A jump here points to
  an over-eager heuristic.

When a saved page shows a new problem, rebuild the pattern with neutral text
in `tests/pages/` and add a check to `tests/test_pages.py`, so the fix stays
covered in the repository.

## Collection

| Folder | Source | Saved | Type |
| --- | --- | --- | --- |
| `tagesschau/` | Article page on tagesschau.de | 2026-10-26 | Article with fixed header, flexbox |
| `ndr/` | NDR.de home page | 2026-10-26 | Teaser grid with flexbox and grid |
| `tagesschau-main/` | tagesschau.de home page | 2026-10-27 | Long teaser page with sliders and many hidden labels |
| `rainews/` | Tagesschau page of RaiNews (South Tyrol) | 2026-10-28 | Menu as CSS table (`display: table-cell`), icon fonts, uppercase labels |
| `heise/` | heise online home page | 2026-10-29 | Long Tailwind page: utility classes, column grids, product sliders |
| `spiegel/` | SPIEGEL home page | 2026-11-01 | Very long page, swiper sliders, mega menu |
| `bbc/` | BBC News home page | 2026-11-01 | Inline CSS-in-JS styles, no-JS menu in `<details>` |
| `guardian/` | The Guardian international page | 2026-11-01 | Named grid lines, scrolling card strips |
| `t3n/` | t3n home page | 2026-11-01 | Styled components, off-canvas burger menu |
| `netzpolitik/` | netzpolitik.org home page | 2026-11-01 | WordPress blocks, column-flow ticker carousel |
| `wikipedia/` | German Wikipedia article (Netscape Navigator) | 2026-11-01 | Text page with infobox table |
| `csstricks/` | CSS-Tricks home page | 2026-11-01 | Card sliders with min-width, code snippets |
| `thomann/` | Thomann category page (electric guitars) | 2026-11-01 | Shop: auto-fill category grid, Tailwind |
