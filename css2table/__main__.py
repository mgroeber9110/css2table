"""Kommandozeile: python -m css2table eingabe.html [-o ausgabe.html]"""

import argparse
import os
import sys
from urllib.parse import urlparse

from .convert import convert


def file_loader(base_dir):
    """Lädt verlinkte Stylesheets aus dem lokalen Dateisystem."""
    def load(href):
        if urlparse(href).scheme in ('http', 'https'):
            return None  # Netzwerkzugriff gehört in den späteren Proxy
        path = href if os.path.isabs(href) else os.path.join(base_dir, href)
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            return None
    return load


def main(argv=None):
    parser = argparse.ArgumentParser(prog='css2table', description=__doc__)
    parser.add_argument('input', help='HTML-Datei (- für stdin)')
    parser.add_argument('-o', '--output', help='Ausgabedatei (Standard: stdout)')
    parser.add_argument('-w', '--width', type=int, default=800,
                        help='angenommene Bildschirmbreite in px (Standard: 800)')
    parser.add_argument('--base-url', help='Basis-URL für relative Links und Bilder')
    parser.add_argument('--encoding', default='utf-8',
                        help='Zeichensatz der Ausgabe, z. B. iso-8859-1 (Standard: utf-8)')
    args = parser.parse_args(argv)

    if args.input == '-':
        html, base_dir = sys.stdin.buffer.read(), os.getcwd()
    else:
        with open(args.input, 'rb') as f:
            html = f.read()
        base_dir = os.path.dirname(os.path.abspath(args.input))

    result = convert(html, viewport_width=args.width, base_url=args.base_url,
                     load_stylesheet=file_loader(base_dir))
    result = result.replace('charset=utf-8', 'charset=' + args.encoding, 1)
    data = result.encode(args.encoding, errors='xmlcharrefreplace')
    if args.output:
        with open(args.output, 'wb') as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)


if __name__ == '__main__':
    main()
