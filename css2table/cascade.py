"""CSS cascade: read stylesheets, match rules, compute values per element.

Deliberately simple: there is no layout computation, only the values
the converter needs to map the page onto tables.
"""

import re
from functools import lru_cache
from urllib.parse import urljoin

import cssselect2
import tinycss2

from .values import ROOT_FONT_SIZE, first_color, font_size, media_matches, parts, tokens

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
p { margin-top: 1em; margin-bottom: 1em }
h1 { margin-top: 0.67em; margin-bottom: 0.67em }
h2 { margin-top: 0.83em; margin-bottom: 0.83em }
h3 { margin-top: 1em; margin-bottom: 1em }
h4 { margin-top: 1.33em; margin-bottom: 1.33em }
h5 { margin-top: 1.67em; margin-bottom: 1.67em }
h6 { margin-top: 2.33em; margin-bottom: 2.33em }
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

# Quirks mode (old doctypes or none): tables do not inherit font and
# alignment from outside, as in browsers of the time
QUIRKS_CSS = """
table { font-size: initial; font-weight: initial; font-style: initial;
        white-space: initial; text-align: initial }
"""

QUIRKS_PUBLIC_IDS = (
    '-//w3c//dtd html 4.0 transitional', '-//w3c//dtd html 4.0 frameset',
    '-//w3c//dtd html 3', '-//w3c//dtd html 2', '-//w3c//dtd w3 html',
    '-//w3c//dtd html experimental', '-//w3o//', '-//ietf//', '-//netscape comm. corp.//',
    '-//microsoft//', '-//softquad', '-//spyglass//', '-//webtechs//', '-//as//',
    '-//metrius//', "-//o'reilly", '-//sun microsystems', '-//sq//', '-//silmaril//',
    '-//advasoft', '-//hotmetal', '-//ms//',
)
LOOSE_PUBLIC_IDS = ('-//w3c//dtd html 4.01 transitional', '-//w3c//dtd html 4.01 frameset')

# Presentational attributes and the CSS properties they stand for
ALIGN_HINT_TAGS = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'tr',
                   'thead', 'tbody', 'tfoot', 'caption', 'center'}
BGCOLOR_HINT_TAGS = {'body', 'table', 'tr', 'td', 'th'}
FONT_SIZE_STEPS = ('10px', '13px', '16px', '18px', '24px', '32px', '48px')


def quirks_mode(root):
    """Whether browsers show the document in quirks mode (see the HTML spec)."""
    info = root.getroottree().docinfo
    if not info.doctype or not info.doctype.lower().startswith('<!doctype html'):
        return True
    public = (info.public_id or '').lower()
    if public.startswith(QUIRKS_PUBLIC_IDS):
        return True
    return public.startswith(LOOSE_PUBLIC_IDS) and not info.system_url


def font_size_hint(value):
    """<font size>: 1 to 7, or relative to the default size 3."""
    value = (value or '').strip()
    try:
        step = int(value)
    except ValueError:
        return None
    if value[0] in '+-':
        step += 3
    return FONT_SIZE_STEPS[min(7, max(1, step)) - 1]


def hints(el, link_color):
    """CSS declarations for the presentational attributes of an element."""
    tag = el.tag.lower() if isinstance(el.tag, str) else ''
    out = []
    if tag == 'font':
        if el.get('color'):
            out.append(('color', el.get('color').strip()))
        if el.get('face'):
            out.append(('font-family', el.get('face').strip()))
        size = font_size_hint(el.get('size'))
        if size:
            out.append(('font-size', size))
    elif tag == 'body':
        if el.get('text'):
            out.append(('color', el.get('text').strip()))
    elif tag == 'a' and link_color and el.get('href') is not None:
        out.append(('color', link_color))
    if tag in BGCOLOR_HINT_TAGS and el.get('bgcolor'):
        out.append(('background-color', el.get('bgcolor').strip()))
    align = (el.get('align') or '').strip().lower()
    if tag in ALIGN_HINT_TAGS and align in ('left', 'right', 'center', 'justify'):
        out.append(('text-align', align))
    if tag in ('td', 'th') and el.get('nowrap') is not None:
        out.append(('white-space', 'nowrap'))
    return out


# The properties of ::before and ::after that decide whether their text shows
PSEUDO_PROPERTIES = {'content', 'display', 'position', 'visibility', 'font-size', 'font-family'}
ICON_FONT_WORDS = ('icon', 'awesome', 'glyph', 'symbol', 'material', 'dashicons')


def content_text(value, el):
    """The text of a `content` value: strings and attr(); None for anything else
    (images, counters, icon font glyphs)."""
    text = []
    for t in tokens(value):
        if t.type == 'string':
            text.append(t.value)
        elif t.type == 'function' and t.lower_name == 'attr':
            args = [a for a in t.arguments if a.type == 'ident']
            text.append(el.get(args[0].value, '') if args else '')
        elif t.type not in ('whitespace', 'comment'):
            return None
    text = ''.join(text)
    # Icon fonts put their glyphs into the private use area
    if not text.strip() or any('\ue000' <= c <= '\uf8ff' or c >= '\U000f0000' for c in text):
        return None
    return text


INHERITED = {'color', 'font-family', 'font-size', 'font-weight', 'font-style',
             'text-align', 'text-transform', 'white-space', 'visibility', 'list-style-type'}

INITIAL = {
    'display': 'inline', 'position': 'static', 'float': 'none',
    'visibility': 'visible', 'color': 'black', 'font-family': 'Times New Roman',
    'font-size': '16px', 'font-weight': 'normal', 'font-style': 'normal',
    'text-align': 'left', 'text-transform': 'none', 'white-space': 'normal', 'list-style-type': 'disc',
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
        self.pseudo = {}  # text of ::before and ::after

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


@lru_cache(maxsize=None)
def expand(name, value):
    """Expand shorthand properties into longhands (cached: values repeat a lot)."""
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
    if name == 'inset':
        sides = _four(value)
        return list(zip(('top', 'right', 'bottom', 'left'), sides)) if sides else []
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
        self.quirks = quirks_mode(root)
        if self.quirks:
            self._add_css(QUIRKS_CSS, origin=0)
        body = root.find('body')
        self.link_color = (body.get('link') or '').strip() or None if body is not None else None
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
        # Compiled stylesheets are cached: sites use the same CSS on every
        # page, and selector compilation is a large part of the run time
        for kind, a, b in compile_css(css, origin, base, self.viewport):
            if kind == 'selector':
                self.matcher.add_selector(a, b)
            else:
                self._import(a, b)

    def _compute(self, root):
        ROOT_FONT_SIZE.set(16.0)  # `rem` on the root element itself uses the initial size
        wrapper = cssselect2.ElementWrapper.from_html_root(root)
        for w in wrapper.iter_subtree():
            el = w.etree_element
            candidates = []
            pseudo_candidates = {}
            for specificity, order, pseudo, (origin, decls) in self.matcher.match(w):
                target = candidates if pseudo is None else pseudo_candidates.setdefault(pseudo, [])
                for i, (name, value, important) in enumerate(decls):
                    target.append(((important, origin, specificity, order, i), name, value))
            # Presentational attributes come before all author rules
            for i, (name, value) in enumerate(hints(el, self.link_color)):
                candidates.append(((False, 1, (-1, 0, 0), 0, i), name, value))
            if el.get('style'):
                for i, (name, value, important) in enumerate(declarations(el.get('style'))):
                    candidates.append(((important, 2, (0, 0, 0), 0, i), name, value))
            candidates.sort(key=lambda c: c[0])
            parent = el.getparent()
            style = self.computed[el] = self._resolve(candidates, self.computed.get(parent))
            for pseudo, decls in pseudo_candidates.items():
                text = self._pseudo_text(decls, style, el)
                if text:
                    style.pseudo[pseudo] = text
            if parent is None:
                ROOT_FONT_SIZE.set(self.computed[el].font_size)

    def _pseudo_text(self, candidates, style, el):
        """The text that ::before or ::after adds, if it is shown in the flow."""
        declared = {}
        for _, name, value in sorted(candidates, key=lambda c: c[0]):
            if 'var(' in value:
                value = substitute(value, style.custom)
            declared[name] = value.strip()
        if (declared.get('display') == 'none' or declared.get('visibility') == 'hidden'
                or declared.get('position') in ('absolute', 'fixed')
                or declared.get('font-size') in ('0', '0px')):
            return None
        text = content_text(declared.get('content', ''), el)
        family = declared.get('font-family', '').lower()
        # Icon fonts that draw letters: `content: "v"` with their own font
        if text and family and (any(w in family for w in ICON_FONT_WORDS)
                                or (len(text.strip()) == 1 and text.strip().isalnum())):
            return None
        return text

    def _resolve(self, candidates, parent):
        style = Style()
        # Inherited custom properties are already substituted; only the ones
        # declared here need it. Without any, the parent's dict is shared.
        custom = parent.custom if parent is not None else {}
        # Utility CSS often redeclares the same custom properties on every
        # element (`* { --tw-shadow: 0 0 #0000 }`): unchanged ones are skipped
        own = {name: value for _, name, value in candidates if name.startswith('--')}
        own = [(name, value) for name, value in own.items()
               if custom.get(name) != value or 'var(' in value]
        if own:
            custom = dict(custom)
            for name, value in own:
                custom[name] = value
            for name in dict(own):
                custom[name] = substitute(custom[name], custom)
        style.custom = custom

        declared = {}
        user_agent = {}  # declarations from the UA stylesheet, for `revert`
        for (_, origin, *_), name, value in candidates:
            if name.startswith('--'):
                continue
            if 'var(' in value:
                value = substitute(value, custom)
            keyword = value.lower()
            if name == 'all':
                # Reset everything declared so far (CSS resets often use `all: unset`)
                if keyword in ('revert', 'revert-layer'):
                    declared = dict(user_agent)
                elif keyword in ('initial', 'unset', 'inherit'):
                    declared = {}
                continue
            for longhand, v in expand(name, value):
                if v.lower() in ('revert', 'revert-layer'):
                    if longhand in user_agent:
                        declared[longhand] = user_agent[longhand]
                    else:
                        declared.pop(longhand, None)
                    continue
                declared[longhand] = v
                if origin == 0:
                    user_agent[longhand] = v

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
        if size and size.lower() == 'initial':
            style.font_size = 16.0
        else:
            style.font_size = font_size(size, parent_size) if size and size.lower() not in (
                'inherit', 'unset') else parent_size
        style['font-size'] = '%gpx' % style.font_size
        return style


@lru_cache(maxsize=64)
def compile_css(css, origin, base, viewport):
    """Selectors and @imports of a stylesheet, in order, as a tuple of
    ('selector', selector, (origin, declarations)) and ('import', href, base)."""
    out = []
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    _compile_rules(rules, origin, base, viewport, out)
    return tuple(out)


def _compile_rules(rules, origin, base, viewport, out):
    for rule in rules:
        if rule.type == 'qualified-rule':
            try:
                selectors = cssselect2.compile_selector_list(rule.prelude)
            except cssselect2.SelectorError:
                continue
            decls = declarations(rule.content)
            pseudo_decls = None
            for selector in selectors:
                if decls and not selector.pseudo_element:
                    out.append(('selector', selector, (origin, decls)))
                elif selector.pseudo_element in ('before', 'after'):
                    if pseudo_decls is None:
                        pseudo_decls = [d for d in decls if d[0] in PSEUDO_PROPERTIES]
                    if pseudo_decls:
                        out.append(('selector', selector, (origin, pseudo_decls)))
        elif rule.type == 'at-rule':
            keyword = rule.lower_at_keyword
            if rule.content is not None and (
                    keyword in ('supports', 'layer') or
                    keyword == 'media' and media_matches(tinycss2.serialize(rule.prelude), viewport)):
                nested = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
                _compile_rules(nested, origin, base, viewport, out)
            elif keyword == 'import':
                href = _import_href(rule, viewport)
                if href:
                    out.append(('import', href, base))


def _import_href(rule, viewport):
    toks = tokens(rule.prelude)
    if not toks:
        return None
    t = toks[0]
    href = t.value if t.type in ('string', 'url') else None
    if t.type == 'function' and t.lower_name == 'url':
        args = tokens(t.arguments)
        href = args[0].value if args else None
    rest = tinycss2.serialize(rule.prelude[rule.prelude.index(t) + 1:])
    return href if media_matches(rest, viewport) else None
