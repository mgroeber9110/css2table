"""Gespeicherte Webseiten aus testpages/ umwandeln und auswerten.

Jede Seite liegt in einem eigenen Unterordner, so wie der Browser sie mit
"Seite speichern unter" ablegt (seite.html plus seite_files/ mit CSS):

    testpages/tagesschau/tagesschau.de.html
    testpages/tagesschau/tagesschau.de_files/main.css

Aufruf: python tools/testpages.py [ordner]
Die Ausgabe landet in testpages/out/<name>.html.
"""

import os
import re
import sys
import time
from collections import Counter

import lxml.html

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from css2table import convert  # noqa: E402
from css2table.__main__ import file_loader  # noqa: E402
from css2table.cascade import StyleResolver  # noqa: E402
from css2table.convert import DROP  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'testpages')


def find_pages(root=ROOT):
    """Alle HTML-Dateien direkt in den Unterordnern von `root`."""
    pages = []
    if not os.path.isdir(root):
        return pages
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if name == 'out' or not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if f.endswith(('.html', '.htm')):
                pages.append(os.path.join(folder, f))
    return pages


def words(text):
    return Counter(re.findall(r'\w+', text.lower()))


def visible_words(html, base_dir):
    """Wörter, die im Original laut CSS sichtbar sind (ohne Skripte, display:none usw.)."""
    doc = lxml.html.document_fromstring(html)
    styles = StyleResolver(doc, load_stylesheet=file_loader(base_dir))
    parts = []

    def walk(el, hidden):
        s = styles.style(el)
        hidden = hidden or el.tag in DROP or s['display'] == 'none' or s['visibility'] == 'hidden'
        if not hidden and el.text:
            parts.append(el.text)
        for child in el:
            if isinstance(child.tag, str):
                walk(child, hidden)
            if not hidden and child.tail:
                parts.append(child.tail)

    body = doc.find('body')
    walk(body if body is not None else doc, False)
    return words(' '.join(parts))


def output_words(html):
    doc = lxml.html.document_fromstring(html)
    body = doc.find('body')
    return words((body if body is not None else doc).text_content())


def check(path, out_dir=None):
    """Seite umwandeln; liefert Kennzahlen als dict."""
    with open(path, 'rb') as f:
        html = f.read()
    base_dir = os.path.dirname(path)
    start = time.perf_counter()
    result = convert(html, load_stylesheet=file_loader(base_dir))
    seconds = time.perf_counter() - start
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, os.path.basename(path)), 'w', encoding='utf-8') as f:
            f.write(result)
    original = visible_words(html, base_dir)
    converted = output_words(result)
    kept = sum((original & converted).values())
    return {
        'page': os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
        'seconds': seconds,
        'size_in': len(html),
        'size_out': len(result.encode('utf-8')),
        'tables': result.count('<table'),
        'text_coverage': kept / max(1, sum(original.values())),
        'html': result,
    }


def main(argv=None):
    root = (argv or sys.argv[1:] or [ROOT])[0]
    pages = find_pages(root)
    if not pages:
        print(f'Keine Testseiten in {root} gefunden.')
        return 1
    out_dir = os.path.join(root, 'out')
    print(f'{"Seite":40} {"Zeit":>6} {"KB ein":>7} {"KB aus":>7} {"Tabellen":>8} {"Text":>6}')
    for path in pages:
        r = check(path, out_dir)
        print(f'{r["page"]:40} {r["seconds"]:5.1f}s {r["size_in"] // 1024:7} '
              f'{r["size_out"] // 1024:7} {r["tables"]:8} {r["text_coverage"]:6.0%}')
    print(f'Ausgabe in {out_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
