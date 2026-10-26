"""CSS cascade: read stylesheets, match rules, compute values per element.

Deliberately simple: there is no layout computation, only the values
the converter needs to map the page onto tables.
"""

import re
from urllib.parse import urljoin

import cssselect2
import tinycss2

from .values import font_size, media_matches, parts, tokens, first_color

UA_CSS = """
head, script, style, link, meta, title, template, base, [hidden], area,
datalist, param, source, track, dialog { display: none }
html, body, div, p, h1, h2, h3, h4, h5, h6, ul, ol, dl, dt, dd, header,
footer, nav, main, section, article, aside, figure, figcaption, form,
fieldset, legend, blockquote, pre, hr, address, center, details, summary,
hgroup, menu, dir { display: block }
li { display: list-item }
table { display: table }
caption { display: table-caption }
thead { display: table-header-group }
tbody { display: table-row-group }
tfoot { display: table-footer-group }
tr { display: table-row }
td, th { display: table-cell }
body { margin: 8px }
h1 { font-size: 2em; font-weight: bold }
h2 { font-size: 1.5em; font-weight: bold }
h3 { font-size: 1.17em; font-weight: bold }
h4 { font-weight: bold }
h5 { font-size: 0.83em; font-weight: bold }
h6 { font-size: 0.67em; font-weight: bold }
a[href] { color: #0000ee; text-decoration: underline }
b, strong, th { font-weight: bold }
i, em, cite, var, dfn, address { font-style: italic }
pre, code, kbd, samp, tt { font-family: monospace }
pre { white-space: pre }
small { font-size: smaller }
big { font-size: larger }
center, th { text-align: center }
"""

INHERITED = {'color', 'font-family', 'font-size', 'font-weight', 'font-style',
             'text-align', 'white-space', 'visibility', 'list-style-type'}

INITIAL = {
    'display': 'inline', 'position': 'static', 'float': 'none',
    'visibility': 'visible', 'color': 'black', 'font-family': 'Times New Roman',
    'font-size': '16px', 'font-weight': 'normal', 'font-style': 'normal',
    'text-align': 'left', 'white-space': 'normal', 'list-style-type': 'disc',
    'flex-direction': 'row', 'flex-wrap': 'nowrap', 'flex-grow': '0',
    'flex-basis': 'auto', 'justify-content': 'normal', 'align-items': 'normal',
    'align-self': 'auto', 'width': 'auto', 'max-width': 'none',
    'border-style': 'none', 'border-width': 'medium',
    'grid-template-columns': 'none', 'grid-template-areas': 'none',
    'grid-column-start': 'auto', 'grid-column-end': 'auto',
    'grid-row-start': 'auto', 'grid-row-end': 'auto',
    'row-gap': 'normal', 'column-gap': 'normal',
}
for _side in ('top', 'right', 'bottom', 'left'):
    INITIAL['margin-' + _side] = '0'
    INITIAL['padding-' + _side] = '0'


class Style(dict):
    """Computed values of an element; missing values return the initial value."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_size = 16.0
        self.custom = {}

    def __missing__(self, key):
        return INITIAL.get(key)


def _four(value):
    p = parts(value)
    if not 1 <= len(p) <= 4:
        return None
    top = p[0]
    right = p[1] if len(p) > 1 else top
    bottom = p[2] if len(p) > 2 else top
    left = p[3] if len(p) > 3 else right
    return top, right, bottom, left


BORDER_STYLES = {'none', 'hidden', 'dotted', 'dashed', 'solid', 'double',
                 'groove', 'ridge', 'inset', 'outset'}


def expand(name, value):
    """Expand shorthand properties into longhands."""
    if name in ('margin', 'padding'):
        sides = _four(value)
        if not sides:
            return []
        return [(f'{name}-{s}', v) for s, v in zip(('top', 'right', 'bottom', 'left'), sides)]
    if name == 'border':
        out = [('border-style', 'none'), ('border-width', 'medium')]
        for p in parts(value):
            if p in BORDER_STYLES:
                out.append(('border-style', p))
            elif p[0].isdigit() or p in ('thin', 'medium', 'thick'):
                out.append(('border-width', p))
            else:
                out.append(('border-color', p))
        return out
    if name == 'background':
        return [('background-color', first_color(value) or 'transparent')]
    if name == 'flex':
        p = parts(value)
        if p == ['none']:
            return [('flex-grow', '0'), ('flex-basis', 'auto')]
        if p == ['auto']:
            return [('flex-grow', '1'), ('flex-basis', 'auto')]
        if p in (['initial'], ['0']):
            return [('flex-grow', '0'), ('flex-basis', 'auto')]
        grow, basis = None, None
        for item in p:
            if re.fullmatch(r'[\d.]+', item):
                if grow is None:
                    grow = item
            else:
                basis = item
        return [('flex-grow', grow or '1'), ('flex-basis', basis or '0%')]
    if name == 'flex-flow':
        out = []
        for p in parts(value):
            out.append(('flex-wrap' if 'wrap' in p else 'flex-direction', p))
        return out
    if name in ('gap', 'grid-gap'):
        p = parts(value)
        if not p:
            return []
        return [('row-gap', p[0]), ('column-gap', p[1] if len(p) > 1 else p[0])]
    if name in ('grid-row-gap', 'grid-column-gap'):
        return [(name[5:], value)]
    if name in ('grid-column', 'grid-row'):
        start, _, end = value.partition('/')
        start = start.strip()
        if not end and not start.startswith('span') and not start.lstrip('-').isdigit():
            end = start  # a named line applies to start and end
        return [(name + '-start', start), (name + '-end', end.strip() or 'auto')]
    if name == 'grid-area':
        p = [x.strip() for x in value.split('/')]
        if len(p) == 1:
            p = p * 4
        while len(p) < 4:
            p.append('auto')
        return [('grid-row-start', p[0]), ('grid-column-start', p[1]),
                ('grid-row-end', p[2]), ('grid-column-end', p[3])]
    if name == 'place-items':
        p = parts(value)
        return [('align-items', p[0])] if p else []
    if name == 'font':
        return _expand_font(value)
    if name == 'list-style':
        return [('list-style-type', 'none')] if 'none' in parts(value) else []
    return [(name, value)]


def _expand_font(value):
    toks = parts(value)
    for i, p in enumerate(toks):
        size = p.split('/')[0]
        if size[:1].isdigit() or size in ('small', 'medium', 'large', 'x-large',
                                           'xx-large', 'x-small', 'xx-small'):
            out = [('font-size', size), ('font-style', 'normal'), ('font-weight', 'normal')]
            for before in toks[:i]:
                if before in ('italic', 'oblique'):
                    out.append(('font-style', before))
                elif before in ('bold', 'bolder') or before.isdigit():
                    out.append(('font-weight', before))
            j = i + 3 if i + 1 < len(toks) and toks[i + 1] == '/' else i + 1
            family = ' '.join(toks[j:]).replace(' ,', ',')
            if family:
                out.append(('font-family', family))
            return out
    return []


VAR_RE = re.compile(r'var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)')


def substitute(value, custom):
    """Replace var(--name, fallback) with the value of the custom property."""
    for _ in range(8):
        if 'var(' not in value:
            break
        value = VAR_RE.sub(lambda m: custom.get(m.group(1), m.group(2) or ''), value)
    return value.strip()


def declarations(content):
    """Declarations of a rule block or style attribute as (name, value, important)."""
    out = []
    for d in tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True):
        if d.type != 'declaration':
            continue
        name = d.name if d.name.startswith('--') else d.lower_name
        out.append((name, tinycss2.serialize(d.value).strip(), d.important))
    return out


class StyleResolver:
    """Matches the CSS rules of a document to its elements."""

    def __init__(self, root, viewport_width=800, load_stylesheet=None):
        self.viewport = viewport_width
        self.load = load_stylesheet
        self.matcher = cssselect2.Matcher()
        self.computed = {}
        self._add_css(UA_CSS, origin=0)
        for el in root.iter('style', 'link'):
            media = el.get('media')
            if media and not media_matches(media, self.viewport):
                continue
            if el.tag == 'style':
                self._add_css(el.text or '', origin=1)
            elif 'stylesheet' in (el.get('rel') or '').lower().split() and el.get('href'):
                self._import(el.get('href'))
        self._compute(root)

    def style(self, el):
        return self.computed.get(el) or Style()

    def _import(self, href, base=None):
        if self.load is None:
            return
        url = urljoin(base, href) if base else href
        css = self.load(url)
        if css:
            self._add_css(css, origin=1, base=url)

    def _add_css(self, css, origin, base=None):
        rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
        self._add_rules(rules, origin, base)

    def _add_rules(self, rules, origin, base):
        for rule in rules:
            if rule.type == 'qualified-rule':
                try:
                    selectors = cssselect2.compile_selector_list(rule.prelude)
                except cssselect2.SelectorError:
                    continue
                decls = declarations(rule.content)
                for selector in selectors:
                    if decls and not selector.pseudo_element:
                        self.matcher.add_selector(selector, (origin, decls))
            elif rule.type == 'at-rule':
                keyword = rule.lower_at_keyword
                if rule.content is not None and (
                        keyword in ('supports', 'layer') or
                        keyword == 'media' and media_matches(tinycss2.serialize(rule.prelude), self.viewport)):
                    nested = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
                    self._add_rules(nested, origin, base)
                elif keyword == 'import':
                    self._at_import(rule, base)

    def _at_import(self, rule, base):
        toks = tokens(rule.prelude)
        if not toks:
            return
        t = toks[0]
        href = t.value if t.type in ('string', 'url') else None
        if t.type == 'function' and t.lower_name == 'url':
            args = tokens(t.arguments)
            href = args[0].value if args else None
        rest = tinycss2.serialize(rule.prelude[rule.prelude.index(t) + 1:])
        if href and media_matches(rest, self.viewport):
            self._import(href, base)

    def _compute(self, root):
        wrapper = cssselect2.ElementWrapper.from_html_root(root)
        for w in wrapper.iter_subtree():
            el = w.etree_element
            candidates = []
            for specificity, order, pseudo, (origin, decls) in self.matcher.match(w):
                if pseudo is None:
                    for i, (name, value, important) in enumerate(decls):
                        candidates.append(((important, origin, specificity, order, i), name, value))
            if el.get('style'):
                for i, (name, value, important) in enumerate(declarations(el.get('style'))):
                    candidates.append(((important, 2, (0, 0, 0), 0, i), name, value))
            candidates.sort(key=lambda c: c[0])
            parent = el.getparent()
            self.computed[el] = self._resolve(candidates, self.computed.get(parent))

    def _resolve(self, candidates, parent):
        style = Style()
        custom = dict(parent.custom) if parent is not None else {}
        for _, name, value in candidates:
            if name.startswith('--'):
                custom[name] = value
        for name in list(custom):
            custom[name] = substitute(custom[name], custom)
        style.custom = custom

        declared = {}
        for _, name, value in candidates:
            if name.startswith('--'):
                continue
            value = substitute(value, custom)
            for longhand, v in expand(name, value):
                declared[longhand] = v

        parent_size = parent.font_size if parent is not None else 16.0
        for name in INHERITED:
            if parent is not None:
                style[name] = parent[name]
        for name, value in declared.items():
            low = value.lower()
            if low == 'inherit' or (low == 'unset' and name in INHERITED):
                if parent is not None:
                    style[name] = parent[name]
            elif low in ('initial', 'unset'):
                style.pop(name, None)
            elif name != 'font-size':
                style[name] = value
        size = declared.get('font-size')
        style.font_size = font_size(size, parent_size) if size and size.lower() not in (
            'inherit', 'unset', 'initial') else parent_size
        style['font-size'] = '%gpx' % style.font_size
        return style
