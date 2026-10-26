"""Hilfsfunktionen zum Lesen einzelner CSS-Werte."""

import re

import tinycss2
from tinycss2 import color3

ABS_UNITS = {'px': 1.0, 'pt': 4 / 3, 'pc': 16.0, 'in': 96.0,
             'cm': 96 / 2.54, 'mm': 96 / 25.4, 'q': 96 / 101.6}

FONT_KEYWORDS = {'xx-small': 9, 'x-small': 10, 'small': 13, 'medium': 16,
                 'large': 18, 'x-large': 24, 'xx-large': 32, 'xxx-large': 48}

# Pixelgrößen der HTML-Schriftgrößen <font size=1..7>
HTML_FONT_SIZES = [10, 13, 16, 18, 24, 32, 48]

GENERIC_FONTS = {
    'sans-serif': ['Arial', 'Helvetica', 'sans-serif'],
    'serif': ['Times New Roman', 'Times', 'serif'],
    'monospace': ['Courier New', 'Courier', 'monospace'],
    'cursive': ['Comic Sans MS', 'cursive'],
    'fantasy': ['Impact', 'fantasy'],
}
# Moderne Systemschrift-Namen, die ein alter Browser nicht kennt
SYSTEM_FONTS = {'system-ui', 'ui-sans-serif', '-apple-system', 'blinkmacsystemfont'}


def tokens(value):
    """Komponentenwerte ohne Leerraum und Kommentare."""
    if isinstance(value, str):
        value = tinycss2.parse_component_value_list(value)
    return [t for t in value if t.type not in ('whitespace', 'comment')]


def parts(value):
    """Wert an Leerraum auf oberster Ebene zerlegen, z. B. '0 auto' -> ['0', 'auto']."""
    return [tinycss2.serialize([t]).strip() for t in tokens(value)]


def split_commas(toks):
    groups = [[]]
    for t in toks:
        if t.type == 'literal' and t.value == ',':
            groups.append([])
        elif t.type not in ('whitespace', 'comment'):
            groups[-1].append(t)
    return groups


def length(value, font_size=16.0):
    """Länge lesen: ('px', n), ('%', n) oder None (auto, calc(), unbekannt)."""
    if value is None:
        return None
    toks = tokens(value) if isinstance(value, str) else [value]
    if len(toks) != 1:
        return None
    t = toks[0]
    if t.type == 'number' and t.value == 0:
        return ('px', 0.0)
    if t.type == 'percentage':
        return ('%', float(t.value))
    if t.type == 'dimension':
        unit = t.lower_unit
        if unit in ABS_UNITS:
            return ('px', t.value * ABS_UNITS[unit])
        if unit == 'em':
            return ('px', t.value * font_size)
        if unit == 'rem':
            return ('px', t.value * 16.0)
        if unit in ('ex', 'ch'):
            return ('px', t.value * font_size / 2)
        if unit in ('vw', 'vi'):
            # Ohne berechnetes Layout ist 1vw etwa 1 % der Breite
            return ('%', float(t.value))
    return None


def px(value, font_size=16.0, ref=None):
    """Länge in Pixel; Prozent nur, wenn eine Bezugsbreite bekannt ist."""
    result = length(value, font_size)
    if result is None:
        return None
    kind, n = result
    if kind == '%':
        return n * ref / 100 if ref is not None else None
    return n


def font_size(value, parent):
    """Berechnete Schriftgröße in Pixel."""
    v = (value or '').strip().lower()
    if v in FONT_KEYWORDS:
        return float(FONT_KEYWORDS[v])
    if v == 'smaller':
        return parent / 1.2
    if v == 'larger':
        return parent * 1.2
    result = length(v, parent)
    if result is None:
        return parent
    kind, n = result
    return parent * n / 100 if kind == '%' else n


def color(value):
    """CSS-Farbe als '#rrggbb'; Transparenz wird mit Weiß gemischt."""
    if value is None or value == '':
        return None
    try:
        c = color3.parse_color(value)
    except Exception:
        return None
    if c is None or isinstance(c, str):
        return None
    r, g, b, a = c
    if a <= 0.01:
        return None
    if a < 1:
        r, g, b = (x * a + (1 - a) for x in (r, g, b))
    return '#%02x%02x%02x' % tuple(round(x * 255) for x in (r, g, b))


def first_color(value):
    """Erste Farbe in einem background-Wert, auch innerhalb eines Verlaufs."""
    for t in tokens(value):
        if t.type == 'function' and 'gradient' in t.lower_name:
            for arg in tokens(t.arguments):
                c = color(arg)
                if c:
                    return c
        elif t.type in ('ident', 'hash', 'function'):
            c = color(t)
            if c:
                return c
    return None


def font_face(family):
    """CSS font-family in eine Liste für <font face> übersetzen."""
    names = []
    for part in (family or '').split(','):
        name = part.strip().strip('"\'')
        low = name.lower()
        if not name or low in ('inherit', 'initial', 'unset'):
            continue
        if low in SYSTEM_FONTS:
            low = 'sans-serif'
        elif low.startswith(('ui-', '-')):
            continue
        if low in GENERIC_FONTS:
            names += GENERIC_FONTS[low]
            break
        names.append(name)
    unique = []
    for n in names:
        if n not in unique:
            unique.append(n)
    return ', '.join(unique[:4]) or None


def html_font_size(size_px):
    """Pixelgröße auf <font size=1..7> abbilden."""
    return 1 + min(range(7), key=lambda i: abs(HTML_FONT_SIZES[i] - size_px))


_RANGE_RE = re.compile(r'^\(\s*width\s*(>=|<=|>|<)\s*([^)]+)\)$')


def media_matches(query_list, width):
    """Media Query für einen Bildschirm der Breite `width` auswerten."""
    query_list = (query_list or '').strip().lower()
    if not query_list:
        return True
    return any(_media_query(q.strip(), width) for q in query_list.split(','))


def _media_query(query, width):
    if not query:
        return True
    negate = False
    ok = True
    for word in re.findall(r'\([^)]*\)|[a-z-]+', query):
        if word in ('only', 'and'):
            continue
        if word == 'not':
            negate = True
        elif word in ('screen', 'all'):
            continue
        elif word.startswith('('):
            ok = ok and _media_feature(word, width)
        else:
            ok = False  # print, speech, ...
    return ok != negate


def _media_feature(feature, width):
    m = _RANGE_RE.match(feature)
    if m:
        op, value = m.groups()
        v = px(value.strip())
        if v is None:
            return False
        return {'>=': width >= v, '<=': width <= v, '>': width > v, '<': width < v}[op]
    name, _, value = feature[1:-1].partition(':')
    name, value = name.strip(), value.strip()
    if name in ('min-width', 'max-width'):
        v = px(value)
        if v is None:
            return False
        return width >= v if name == 'min-width' else width <= v
    if name == 'orientation':
        return value == 'landscape'
    if name == 'prefers-color-scheme':
        return value == 'light'
    if name == 'prefers-reduced-motion':
        return value == 'reduce'
    return False
