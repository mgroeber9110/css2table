# css2table

Wandelt das CSS-Layout moderner Webseiten in HTML 4.01 mit Tabellen um, damit
Browser von etwa 2001 (IE 5/6, Netscape 4, Opera 5) ein ähnliches Layout zeigen.
Die Ausgabe enthält kein JavaScript und nur einfache Inline-Styles (CSS1).

Das ist der erste Prototyp des Konverters. Einen Proxy-Server gibt es noch nicht.

## Ansatz

Es wird **kein Layout berechnet** und kein Headless-Browser verwendet. Stattdessen
übersetzt css2table die geometrischen Vorgaben des CSS direkt in
Tabellen-Eigenschaften. Der alte Browser passt die Tabellen dann selbst an
Fenstergröße und Schriftgröße an.

1. HTML mit `lxml` parsen.
2. CSS aus `<style>`, `<link>` und `@import` mit `tinycss2` lesen, Regeln per
   `cssselect2` zuordnen und die Kaskade selbst auflösen (Spezifität,
   `!important`, Inline-Styles, Vererbung, `var()`, Media Queries für eine
   angenommene Bildschirmbreite).
3. Je Element entscheiden: Flex- oder Grid-Container werden zu Tabellen, Blöcke mit
   Hintergrund, Innenabstand oder Breite zu einzelligen Tabellen, alles andere
   bleibt (ggf. mit HTML4-Tag) erhalten.
4. Schrift und Farben als `<font>`, `bgcolor`, `align` usw. ausgeben, zusätzlich als
   `style`-Attribut für Browser, die CSS1 können.

| CSS | Tabelle |
| --- | --- |
| `display: flex` (Zeile) | eine `<tr>`, eine `<td>` je Kind |
| `flex-direction: column` | eine `<tr>` je Kind |
| `flex: 1`, `flex-grow` | `<td width="x%">` anteilig |
| `width` / `flex-basis` | `<td width>` in px oder % |
| `justify-content` | leere Abstandszellen (`center`, `space-between`, ...) |
| `align-items` / `align-self` | `valign` |
| `flex-wrap: wrap` | Zeilen anhand geschätzter Breiten, eine Tabelle je Zeile |
| `gap` | `cellspacing` |
| `grid-template-columns` (px, %, fr, `repeat()`, `minmax()`, `auto-fill`) | Spaltenbreiten; `fr` wird zu Prozent |
| `grid-column` / `grid-row` (`span`, Liniennummern) | `colspan` / `rowspan` |
| `grid-template-areas` / `grid-area` | Raster mit `colspan` / `rowspan` |
| `max-width` + `margin: 0 auto` | `<table width="…" align="center">` (volle Breite, wenn `max-width` größer als der Bildschirm ist) |
| `padding` | `cellpadding` (Mittelwert der vier Seiten) |
| `border` | `border` + `bordercolor` |
| `background(-color)`, auch Verläufe | `bgcolor` (erste Farbe) |
| `color`, `font-family`, `font-size`, `font-weight` | `<font color face size>`, `<b>`, `<i>` |
| `display: none`, `position: fixed`, `<script>`, `<iframe>`, `<video>`, `<svg>` | entfällt |

## Benutzung

```sh
pip install -e '.[test]'
python -m css2table seite.html -o seite-alt.html
python -m css2table seite.html --width 640 --encoding iso-8859-1 --base-url https://example.org/
```

- `--width`: angenommene Bildschirmbreite in Pixel (Standard 800) für Media Queries
  und für Schätzungen wie `auto-fill` oder `flex-wrap`.
- `--base-url`: macht relative Links und Bilder absolut.
- `--encoding`: Zeichensatz der Ausgabe; nicht darstellbare Zeichen werden zu `&#…;`.

Verlinkte Stylesheets werden nur aus lokalen Dateien relativ zur Eingabe geladen.

Als Bibliothek:

```python
from css2table import convert
html4 = convert(open('seite.html', 'rb').read(), viewport_width=800)
```

## Beispiele und Tests

`examples/grid.html` und `examples/flex.html` sind Testseiten mit typischen
Grid- und Flexbox-Layouts, `examples/out/` enthält die umgewandelten Fassungen.

```sh
python -m pytest
```

## Bekannte Grenzen

- Kein JavaScript: Inhalte, die erst per Skript entstehen, fehlen.
- `flex-wrap` und `auto-fill` beruhen auf geschätzten Breiten; ohne bekannte Breiten
  bleibt alles in einer Zeile.
- `gap` wird zu `cellspacing` und erscheint deshalb auch am Rand der Tabelle.
- Abstände (`margin`) zwischen Blöcken werden ignoriert, `padding` ist pro Box
  ein einziger Wert.
- `position: absolute`, `transform`, `float` von Blöcken (außer als `align`) und
  Pseudo-Elemente (`::before`) werden nicht nachgebildet.
- `max-width` kleiner als die Bildschirmbreite wird zu einer festen Pixelbreite.
