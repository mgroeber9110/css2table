"""Helpers for reading individual CSS values."""

import re

import tinycss2
from tinycss2 import color3

ABS_UNITS = {'px': 1.0, 'pt': 4 / 3, 'pc': 16.0, 'in': 96.0,
             'cm': 96 / 2.54, 'mm': 96 / 25.4, 'q': 96 / 101.6}

FONT_KEYWORDS = {'xx-small': 9, 'x-small': 10, 'small': 13, 'medium': 16,
                 'large': 18, 'x-large': 24, 'xx-large': 32, 'xxx-large': 48}

# Screen width assumed where a value needs one (the CLI default)
VIEWPORT_WIDTH = 800

# Pixel sizes of the HTML font sizes <font size=1..7>
HTML_FONT_SIZES = [10, 13, 16, 18, 24, 32, 48]

GENERIC_FONTS = {
    'sans-serif': ['Arial', 'Helvetica', 'sans-serif'],
    'serif': ['Times New Roman', 'Times', 'serif'],
    'monospace': ['Courier New', 'Courier', 'monospace'],
    'cursive': ['Comic Sans MS', 'cursive'],
    'fantasy': ['Impact', 'fantasy'],
}
# Modern system font names that a legacy browser does not know
SYSTEM_FONTS = {'system-ui', 'ui-sans-serif', '-apple-system', 'blinkmacsystemfont'}


def tokens(value):
    """Component values without whitespace and comments."""
    if isinstance(value, str):
        value = tinycss2.parse_component_value_list(value)
    return [t for t in value if t.type not in ('whitespace', 'comment')]


def parts(value):
    """Split a value at top-level whitespace, e.g. '0 auto' -> ['0', 'auto']."""
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
    """Read a length: ('px', n), ('%', n) or None (auto, unknown)."""
    if value is None:
        return None
    toks = tokens(value) if isinstance(value, str) else [value]
    if len(toks) != 1:
        return None
    t = toks[0]
    if t.type == 'function' and t.lower_name in MATH_FUNCTIONS:
        result = math_function(t, font_size)
        if result is None:
            return None
        pct, pixels, _ = result
        # calc(50% - 1rem) becomes 50%: the fixed part matters little in a table
        return ('%', pct) if pct else ('px', pixels)
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
            # Without a computed layout, 1vw is roughly 1% of the width
            return ('%', float(t.value))
    return None


MATH_FUNCTIONS = {'calc', 'min', 'max', 'clamp'}


def math_function(t, font_size):
    """Evaluate calc()/min()/max()/clamp() as (percent, px, is_number), or None.

    If percentages are involved, min() and max() use their first argument and
    clamp() its preferred value, since the real result depends on the layout.
    """
    args = [_calc_sum(group, font_size) for group in split_commas(t.arguments)]
    if not args or None in args:
        return None
    name = t.lower_name
    if name == 'calc':
        return args[0] if len(args) == 1 else None
    if name == 'clamp' and len(args) != 3:
        return None
    if any(a[0] for a in args):
        return args[1] if name == 'clamp' else args[0]
    values = [a[1] for a in args]
    if name == 'min':
        return (0.0, min(values), False)
    if name == 'max':
        return (0.0, max(values), False)
    return (0.0, max(values[0], min(values[1], values[2])), False)


def _calc_sum(toks, font_size):
    """Sum of products: the operands are linear terms (percent, px, is_number)."""
    total, sign = (0.0, 0.0, True), 1
    term = []
    for t in toks + [None]:
        if t is None or (t.type == 'literal' and t.value in '+-' and term):
            value = _calc_product(term, font_size)
            if value is None:
                return None
            total = (total[0] + sign * value[0], total[1] + sign * value[1], total[2] and value[2])
            if t is not None:
                sign, term = (1 if t.value == '+' else -1), []
        else:
            term.append(t)
    return total


def _calc_product(toks, font_size):
    if len(toks) % 2 == 0:
        return None
    result = _calc_operand(toks[0], font_size)
    for op, t in zip(toks[1::2], toks[2::2]):
        operand = _calc_operand(t, font_size)
        if result is None or operand is None or op.type != 'literal' or op.value not in '*/':
            return None
        if op.value == '*':
            if result[2]:
                result, operand = operand, result
            elif not operand[2]:
                return None
            result = (result[0] * operand[1], result[1] * operand[1], result[2])
        else:
            if not operand[2] or operand[1] == 0:
                return None
            result = (result[0] / operand[1], result[1] / operand[1], result[2])
    return result


def _calc_operand(t, font_size):
    if t.type == 'number':
        return (0.0, float(t.value), True)
    if t.type == '() block':
        return _calc_sum(tokens(t.content), font_size)
    if t.type == 'function' and t.lower_name in MATH_FUNCTIONS:
        return math_function(t, font_size)
    result = length(t, font_size)
    if result is None:
        return None
    kind, n = result
    return (n, 0.0, False) if kind == '%' else (0.0, n, False)


def px(value, font_size=16.0, ref=None):
    """Length in pixels; percentages only when a reference width is known."""
    result = length(value, font_size)
    if result is None:
        return None
    kind, n = result
    if kind == '%':
        return n * ref / 100 if ref is not None else None
    return n


def font_size(value, parent):
    """Computed font size in pixels."""
    v = (value or '').strip().lower()
    # For font sizes, vw must be a real width: assume the default screen width
    v = re.sub(r'(\d*\.?\d+)v[wi]\b', lambda m: '%gpx' % (float(m.group(1)) * VIEWPORT_WIDTH / 100), v)
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
    """CSS color as '#rrggbb'; transparency is blended with white."""
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
    """First color in a background value, including inside a gradient."""
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
    """Translate a CSS font-family into a list for <font face>."""
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
    """Map a pixel size onto <font size=1..7>."""
    return 1 + min(range(7), key=lambda i: abs(HTML_FONT_SIZES[i] - size_px))


_RANGE_RE = re.compile(r'^\(\s*width\s*(>=|<=|>|<)\s*([^)]+)\)$')


def media_matches(query_list, width):
    """Evaluate a media query for a screen of width `width`."""
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
