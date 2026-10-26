# Testseiten

Gespeicherte Fassungen echter Webseiten (nur HTML und CSS), mit denen der
Konverter geprüft wird. Jede Seite liegt in einem eigenen Unterordner, so wie
der Browser sie mit "Seite speichern unter" ablegt:

    testpages/tagesschau/tagesschau.de.html
    testpages/tagesschau/tagesschau.de_files/main-….css

Die Seiten selbst sind urheberrechtlich geschützt und werden deshalb nicht
eingecheckt (siehe `.gitignore`). Nur diese Datei liegt im Repo.

```sh
python tools/testpages.py      # alle Seiten umwandeln, Ausgabe in testpages/out/
python -m pytest tests/test_testpages.py
```

`tools/testpages.py` zeigt je Seite Laufzeit, Größe, Zahl der Tabellen und die
**Text-Abdeckung**: welcher Anteil der Wörter, die im Original laut CSS sichtbar
sind, in der umgewandelten Seite noch vorkommt.

## Sammlung

| Ordner | Quelle | Gespeichert | Typ |
| --- | --- | --- | --- |
| `tagesschau/` | Artikelseite auf tagesschau.de | 26.10.2026 | Artikel mit fixiertem Header, Flexbox |
| `ndr/` | Startseite NDR.de | 26.10.2026 | Teaser-Raster mit Flexbox und Grid |
