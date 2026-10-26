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

For each page, `tools/testpages.py` shows the run time, size, number of tables
and the **text coverage**: the share of the words that the CSS makes visible in
the original which still appear in the converted page.

## Collection

| Folder | Source | Saved | Type |
| --- | --- | --- | --- |
| `tagesschau/` | Article page on tagesschau.de | 2026-10-26 | Article with fixed header, flexbox |
| `ndr/` | NDR.de home page | 2026-10-26 | Teaser grid with flexbox and grid |
