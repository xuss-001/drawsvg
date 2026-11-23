import copy
import dataclasses
import itertools
import re

from .types import (
    DrawingBasicElement,
    DrawingElement,
    DrawingParentElement,
    LocalContext,
)


_layer_id_counter = itertools.count()
_URL_REF_RE = re.compile(
    r'url\(\s*(["\']?)#([^)"\'\s]+)\1\s*\)')
_HREF_REF_RE = re.compile(r'^(#[^)\s]+)$')


def _iter_reachable_elements(roots):
    '''Iterate over all drawing elements reachable from `roots`.

    References in element arguments (for example, gradients, clip paths, and
    use targets) are included even when they are not attached to a drawing.
    Shared elements are yielded only once.
    '''
    stack = list(roots)
    seen = set()
    while stack:
        element = stack.pop()
        if not isinstance(element, DrawingElement):
            continue
        element_id = id(element)
        if element_id in seen:
            continue
        seen.add(element_id)
        yield element
        if isinstance(element, DrawingBasicElement):
            for value in element.args.values():
                if isinstance(value, DrawingElement):
                    stack.append(value)
            stack.extend(element.children)
            for children in element.ordered_children.values():
                stack.extend(children)
        attached_defs = getattr(element, 'defs', None)
        if isinstance(attached_defs, (list, tuple)):
            stack.extend(
                item for item in attached_defs
                if isinstance(item, DrawingElement))


def _rewrite_references(name, value, id_map):
    if not isinstance(value, str):
        return value

    def replace_url(match):
        quote, old_id = match.group(1), match.group(2)
        new_id = id_map.get(old_id)
        if new_id is None:
            return match.group(0)
        return 'url({}#{}{})'.format(quote, new_id, quote)

    value = _URL_REF_RE.sub(replace_url, value)
    if name in ('xlink:href', 'href'):
        href_match = _HREF_REF_RE.match(value)
        if href_match is not None:
            old_id = href_match.group(1)[1:]
            new_id = id_map.get(old_id)
            if new_id is not None:
                value = '#' + new_id
    return value


class DrawingLayer(DrawingParentElement):
    '''A snapshot of a `Drawing` embedded as an independent SVG layer.

    The layer is rendered as a nested `<svg>` element. Its `x`, `y`, `width`,
    and `height` attributes place it in the parent drawing while its `viewBox`
    preserves the source drawing's coordinate system.

    Explicit element ids in the source drawing are rewritten with a
    layer-specific prefix. This keeps equal ids in different layers separate
    while object references (and references to shared source resources) within
    one layer still resolve to the same id.

    The source drawing is deep-copied. Combining layers and exporting the
    combined drawing never modify the source drawings.

    Only drawsvg elements and drawsvg-internal references are supported.
    Arbitrary XML in `Raw` content, external resources, and animations are not
    rewritten or otherwise interpreted.
    '''
    TAG_NAME = 'svg'

    def __init__(self, drawing, x=0, y=0, width=None, height=None,
                 id_prefix=None, **kwargs):
        if width is None:
            width = drawing.width
        if height is None:
            height = drawing.height
        if id_prefix is None:
            id_prefix = '{}L{}_'.format(
                drawing.id_prefix, next(_layer_id_counter))
        self.id_prefix = str(id_prefix)
        self._content_context = dataclasses.replace(
            drawing.context, animation_config=None)
        view_box = ' '.join(map(str, drawing.view_box))
        view_box = drawing.context.override_view_box(view_box)
        if not isinstance(view_box, str):
            view_box = ' '.join(map(str, view_box))
        self._view_box = view_box

        elements_copy, ordered_children, defs_copy = copy.deepcopy((
            list(drawing.elements),
            {z: list(v) for z, v in drawing.ordered_elements.items()},
            list(drawing.other_defs),
        ))
        self.defs = list(defs_copy)

        roots = list(elements_copy)
        for z in sorted(ordered_children):
            roots.extend(ordered_children[z])
        roots.extend(self.defs)
        self._rename_ids(roots, self.id_prefix)

        svg_args = dict(
            x=x,
            y=y,
            width=width,
            height=height,
            viewBox=self._view_box,
        )
        svg_args.update(kwargs)
        super().__init__(
            children=elements_copy,
            ordered_children=ordered_children,
            **svg_args)

    def _rename_ids(self, roots, id_prefix):
        reachable = list(_iter_reachable_elements(roots))
        id_map = {}
        used_new_ids = set()
        for element in reachable:
            if not isinstance(element, DrawingBasicElement):
                continue
            # Copied elements may carry caches from the source drawing that
            # refer to the source context. Let them be recomputed for the
            # containing drawing.
            element._cached_context = None
            element._cached_extra_children_with_context = None
            old_id = element.args.get('id')
            if old_id is None:
                continue
            old_id = str(old_id)
            new_id = id_prefix + old_id
            suffix = 0
            while new_id in used_new_ids:
                suffix += 1
                new_id = '{}{}_{}'.format(id_prefix, old_id, suffix)
            used_new_ids.add(new_id)
            id_map.setdefault(old_id, new_id)
            element.args['id'] = new_id
        for element in reachable:
            if not isinstance(element, DrawingBasicElement):
                continue
            for name, value in list(element.args.items()):
                if name != 'id':
                    element.args[name] = _rewrite_references(
                        name, value, id_map)

    def write_svg_defs(self, id_map, is_duplicate, output_file, lcontext,
                       dry_run):
        for definition in self.defs:
            if is_duplicate(definition):
                continue
            local = LocalContext(
                self._content_context, definition, self, ())
            definition.write_svg_defs(
                id_map, is_duplicate, output_file, local, dry_run)
            if definition.id is None:
                id_map[id(definition)]
            definition.write_svg_element(
                id_map, is_duplicate, output_file, local, dry_run,
                force_dup=True)
            if not dry_run:
                output_file.write('\n')
        children = self.all_children(lcontext=LocalContext(
            self._content_context, self, lcontext.parent, lcontext.siblings))
        for child in children:
            local = LocalContext(
                self._content_context, child, self, children)
            child.write_svg_defs(
                id_map, is_duplicate, output_file, local, dry_run)

    def write_svg_element(self, id_map, is_duplicate, output_file, lcontext,
                          dry_run, force_dup=False):
        children = self.all_children(lcontext=LocalContext(
            self._content_context, self, lcontext.parent, lcontext.siblings))
        if dry_run:
            if is_duplicate(self) and self.id is None:
                id_map[id(self)]
            if self.has_content:
                self.write_content(
                    id_map, is_duplicate, output_file, lcontext, dry_run)
            if children:
                self.write_children_content(
                    id_map, is_duplicate, output_file, lcontext, dry_run)
            return
        if is_duplicate(self) and not force_dup:
            mapped_id = self.id
            if id_map is not None and id(self) in id_map:
                mapped_id = id_map[id(self)]
            output_file.write('<use xlink:href="#{}" />'.format(mapped_id))
            return
        output_file.write('<')
        output_file.write(self.TAG_NAME)
        override_args = self.args
        if id(self) in id_map:
            override_args = dict(override_args)
            override_args['id'] = id_map[id(self)]
        override_args = lcontext.context.override_args(override_args)
        # The viewBox was already resolved using the source drawing's context.
        override_args['viewBox'] = self._view_box
        lcontext.context._write_tag_args(
            override_args, output_file, id_map=id_map)
        output_file.write('>')
        if self.has_content:
            self.write_content(
                id_map, is_duplicate, output_file, lcontext, dry_run)
        if children:
            self.write_children_content(
                id_map, is_duplicate, output_file, lcontext, dry_run)
        output_file.write('</')
        output_file.write(self.TAG_NAME)
        output_file.write('>')

    def write_children_content(self, id_map, is_duplicate, output_file,
                               lcontext, dry_run):
        children = self.all_children(lcontext=LocalContext(
            self._content_context, self, lcontext.parent, lcontext.siblings))
        if dry_run:
            for child in children:
                local = LocalContext(
                    self._content_context, child, self, children)
                child.write_svg_element(
                    id_map, is_duplicate, output_file, local, dry_run)
            return
        output_file.write('\n')
        for child in children:
            local = LocalContext(
                self._content_context, child, self, children)
            child.write_svg_element(
                id_map, is_duplicate, output_file, local, dry_run)
            output_file.write('\n')


Layer = DrawingLayer
