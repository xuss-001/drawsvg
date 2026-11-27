import dataclasses
from io import StringIO
from collections import defaultdict
import math
import random
import string
import xml.sax.saxutils as xml

from . import (
    types, elements as elements_module, raster, video, jupyter,
    native_animation, font_embed, geometry,
)


XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
SVG_START = ('<svg xmlns="http://www.w3.org/2000/svg" '
             'xmlns:xlink="http://www.w3.org/1999/xlink"\n    ')
SVG_END = '</svg>'
SVG_CSS_FMT = '<style>/*<![CDATA[*/{}/*]]>*/</style>'
SVG_JS_FMT = '<script>/*<![CDATA[*/{}/*]]>*/</script>'


class Drawing:
    '''
    A vector drawing.

    Append shapes and other elements with `.append()`.  The default coordinate
    system origin is at the top-left corner with x-values increasing to the
    right and y-values increasing downward.

    Supports Jupyter: If a Drawing is the last line of a cell, it will be
    displayed as an SVG below.
    '''
    def __init__(self, width=None, height=None, origin=(0,0),
                 context: types.Context=None,
                 animation_config: native_animation.SyncedAnimationConfig | None=None,
                 id_prefix='d', unit='', auto_viewbox=False, padding=0,
                 auto_view_box=None, viewbox_padding=None,
                 view_box_padding=None, **svg_args):
        '''
        Args:
            width: The width of the SVG canvas, in units of pixels by default.
            height: The height of the SVG canvas, in units of pixels by default.
            origin: Either the string 'center' or a tuple of two floats.  If 'center', a shape drawn
                at x=0, y=0 will appear in the center of the image.  If `(-5, -10)`, a shape drawn
                at x=0, y=0 will appear 5 units down from the top of the image (or up from the
                bottom if y-inverted) and 10 units from the left edge of the image.
            context: A global configuration that may affect how elements are displayed.
            animation_config: Optional configuration of SVG-native animation in your drawing along
                with UI controls for that animation.
            id_prefix: When elements reference other elements, an id attribute is auto-assigned in
                the produced SVG using this string prefix and a number.
            unit: Any supported SVG unit, such as 'px' or 'mm', to be used in the `width` and
                `height` attributes of the `<svg>` tag.  All position and size values in this
                drawing will be in this unit.
            auto_viewbox: If True, calculate the viewBox from the drawing's
                geometry when it is used.  Text, images, strokes, filters, and
                external resources are not included.
            padding: Equal empty space added on all four sides of an
                automatically calculated viewBox.
        '''
        if auto_view_box is not None:
            auto_viewbox = auto_view_box
        if viewbox_padding is not None:
            padding = viewbox_padding
        if view_box_padding is not None:
            padding = view_box_padding
        if isinstance(origin, str) and origin.lower() in ('auto', 'fit'):
            auto_viewbox = True
            origin = 'top-left'
        if (isinstance(svg_args.get('viewBox'), str)
                and svg_args['viewBox'].strip().lower() in ('auto', 'fit')):
            auto_viewbox = True
            del svg_args['viewBox']
        auto_width = width is None
        auto_height = height is None
        if auto_viewbox and width is None and height is None:
            width = height = 0
        if width is None or height is None:
            raise TypeError(
                'width and height are required unless auto_viewbox=True is '
                'used without either dimension')
        padding = float(padding)
        if not math.isfinite(padding) or padding < 0:
            raise ValueError('padding must be a finite, non-negative number')
        if context is None:
            context = types.Context()
        if animation_config is not None:
            context = dataclasses.replace(
                    context, animation_config=animation_config)
        self.width = width
        self.height = height
        if isinstance(origin, str):
            if context.invert_y and origin.startswith('bottom-'):
                origin = origin.replace('bottom-', 'top-')
            elif context.invert_y and origin.startswith('top-'):
                origin = origin.replace('top-', 'bottom-')
            self.view_box = {
                'center': (-width/2, -height/2, width, height),
                'top-left': (0, 0, width, height),
                'top-right': (-width, 0, width, height),
                'bottom-left': (0, -height, width, height),
                'bottom-right': (-width, -height, width, height),
            }[origin]
        else:
            origin = tuple(origin)
            if len(origin) != 2:
                raise ValueError(
                        "origin must be the string 'center', 'top-left', ..., "
                        "'bottom-right' or a tuple (x, y)")
            self.view_box = origin + (width, height)
        self.elements = []
        self.ordered_elements = defaultdict(list)
        self.other_defs = []
        self.css_list = []
        self.js_list = []
        self.pixel_scale = 1
        self.render_width = None
        self.render_height = None
        self.context = context
        self.id_prefix = str(id_prefix)
        self.unit = unit
        self._auto_viewbox = bool(auto_viewbox)
        self._viewbox_padding = padding
        self._auto_width = auto_width
        self._auto_height = auto_height
        self.svg_args = {}
        self._cached_context = None
        self._cached_extra_prepost_with_context = None
        for k, v in svg_args.items():
            k = k.replace('__', ':')
            k = k.replace('_', '-')
            if k[-1] == '-':
                k = k[:-1]
            self.svg_args[k] = v
    @property
    def view_box(self):
        '''The current viewBox, calculated from geometry when auto-fitting.'''
        if self._auto_viewbox:
            return self.calc_view_box(self._viewbox_padding)
        return self._manual_view_box
    @view_box.setter
    def view_box(self, value):
        self._manual_view_box = tuple(value)
        self._auto_viewbox = False
    viewbox = view_box
    @property
    def auto_viewbox(self):
        return self._auto_viewbox
    @auto_viewbox.setter
    def auto_viewbox(self, value):
        self._auto_viewbox = bool(value)
    @property
    def auto_view_box(self):
        return self._auto_viewbox
    @auto_view_box.setter
    def auto_view_box(self, value):
        self._auto_viewbox = bool(value)
    @property
    def padding(self):
        return self._viewbox_padding
    @padding.setter
    def padding(self, value):
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError('padding must be a finite, non-negative number')
        self._viewbox_padding = value
    viewbox_padding = padding
    view_box_padding = padding
    def calc_view_box(self, padding=None):
        '''Return a viewBox fitted to all supported geometry.

        Args:
            padding: Equal space to add on every side.  Defaults to the
                drawing's configured padding.
        '''
        if padding is None:
            padding = self._viewbox_padding
        padding = float(padding)
        if not math.isfinite(padding) or padding < 0:
            raise ValueError('padding must be a finite, non-negative number')
        drawing_elements = list(self.elements)
        for z in sorted(self.ordered_elements):
            drawing_elements.extend(self.ordered_elements[z])
        bounds = geometry.drawing_bounds(
            drawing_elements, transform=self.svg_args.get('transform'))
        view_box = bounds.as_tuple(padding)
        if self._auto_width:
            self.width = view_box[2]
        if self._auto_height:
            self.height = view_box[3]
        return view_box
    calc_viewbox = calc_view_box
    calculate_view_box = calc_view_box
    def set_auto_viewbox(self, padding=None):
        '''Enable automatic viewBox fitting, optionally setting padding.'''
        if padding is not None:
            self.padding = padding
        self._auto_viewbox = True
        return self
    set_auto_view_box = set_auto_viewbox
    def set_manual_view_box(self, view_box):
        '''Use a fixed viewBox and disable automatic fitting.'''
        self.view_box = view_box
        return self
    def set_view_box(self, view_box=None, *, auto=False, padding=None):
        '''Set a fixed viewBox, or enable fitting with ``auto=True``.'''
        if auto or (isinstance(view_box, str)
                    and view_box.lower() in ('auto', 'fit')):
            return self.set_auto_viewbox(padding)
        if view_box is None:
            return self.fit_view_box(padding)
        return self.set_manual_view_box(view_box)
    set_viewbox = set_view_box
    def fit_view_box(self, padding=None):
        '''Calculate the fitted viewBox and store it as a fixed viewBox.'''
        view_box = self.calc_view_box(padding)
        self.view_box = view_box
        return self
    fit_viewbox = fit_view_box
    fit_to_contents = fit_view_box
    set_view_box_to_contents = fit_view_box
    set_viewbox_to_contents = fit_view_box
    def set_render_size(self, w=None, h=None):
        self.render_width = w
        self.render_height = h
        return self
    def set_pixel_scale(self, s=1):
        self.render_width = None
        self.render_height = None
        self.pixel_scale = s
        return self
    def calc_render_size(self):
        base_width, base_height = self.width, self.height
        if self._auto_viewbox and (self._auto_width or self._auto_height):
            auto_view_box = self.calc_view_box()
            if self._auto_width:
                base_width = auto_view_box[2]
            if self._auto_height:
                base_height = auto_view_box[3]
        if self.render_width is None and self.render_height is None:
            return (base_width * self.pixel_scale,
                    base_height * self.pixel_scale)
        elif self.render_width is None:
            s = self.render_height / base_height
            return base_width * s, self.render_height
        elif self.render_height is None:
            s = self.render_width / base_width
            return self.render_width, base_height * s
        else:
            return self.render_width, self.render_height
    def draw(self, obj, *, z=None, **kwargs):
        '''Add any object that knows how to draw itself to the drawing.

        This object must implement the `to_drawables(**kwargs)` method
        that returns a `DrawingElement` or list of elements.
        '''
        if obj is None:
            return
        if not hasattr(obj, 'write_svg_element'):
            elements = obj.to_drawables(**kwargs)
        else:
            if len(kwargs) > 0:
                raise ValueError('unexpected kwargs')
            elements = obj
        if hasattr(elements, 'write_svg_element'):
            self.append(elements, z=z)
        else:
            self.extend(elements, z=z)
    def append(self, element, *, z=None):
        '''Add any `DrawingElement` to the drawing.

        Do not append a `DrawingDef` referenced by other elements.  These are
        included automatically.  Use `.append_def()` for an unreferenced
        `DrawingDef`.
        '''
        if z is not None:
            self.ordered_elements[z].append(element)
        else:
            self.elements.append(element)
    def extend(self, iterable, *, z=None):
        if z is not None:
            self.ordered_elements[z].extend(iterable)
        else:
            self.elements.extend(iterable)
    def insert(self, i, element):
        '''Inserts a top-level element at the given array index.'''
        self.elements.insert(i, element)
    def remove(self, element):
        '''Removes a top-level element (except those with a z-index).'''
        self.elements.remove(element)
    def clear(self):
        '''Clears all drawing elements, with or without a z-index, but keeps
        defs-type elements added with `append_def()`.
        '''
        self.elements.clear()
        self.ordered_elements.clear()
    def index(self, *args, **kwargs):
        '''Finds the array-index of a top-level element (except those with a
        z-index).
        '''
        return self.elements.index(*args, **kwargs)
    def count(self, element):
        '''Counts the number of top-level elements (except those with a z-index
        ).
        '''
        return self.elements.count(element)
    def reverse(self):
        '''Reverses the order of all elements (except those with a z-index).'''
        self.elements.reverse()
    def draw_def(self, obj, **kwargs):
        if not hasattr(obj, 'write_svg_element'):
            elements = obj.to_drawables(**kwargs)
        else:
            if len(kwargs) > 0:
                raise ValueError('unexpected kwargs')
            elements = obj
        if hasattr(elements, 'write_svg_element'):
            self.append_def(elements)
        else:
            self.other_defs.extend(elements)
    def append_def(self, element):
        self.other_defs.append(element)
    def append_title(self, text, **kwargs):
        self.append(elements_module.Title(text, **kwargs))
    def append_css(self, css_text):
        self.css_list.append(css_text)
    def embed_google_font(self, family, text=None, display='swap', **kwargs):
        '''Download SVG-embeddable CSS from Google fonts.

        Args:
            family: Name of font family or list of font families.
            text: The set of characters required from the font.  Only a font
                subset with these characters will be downloaded.
            display: The font-display CSS value.
            **kwargs: Other URL parameters sent to
                https://fonts.googleapis.com/css?...
        '''
        self.append_css(font_embed.download_google_font_css(
                family, text=text, display=display, **kwargs))
    def append_javascript(self, js_text, onload=None):
        if onload:
            if self.svg_args.get('onload'):
                self.svg_args['onload'] = f'{self.svg_args["onload"]};{onload}'
            else:
                self.svg_args['onload'] = onload
        self.js_list.append(js_text)
    def all_elements(self, context=None):
        '''Return self.elements, self.ordered_elements, and extras as a single
        list.
        '''
        extra_pre, extra_post = (
                self._extra_prepost_with_context_avoid_recompute(
                    context=context))
        output = list(extra_pre)
        output.extend(self.elements)
        for z in sorted(self.ordered_elements):
            output.extend(self.ordered_elements[z])
        output.extend(extra_post)
        return output
    def _extra_prepost_with_context_avoid_recompute(self, context=None):
        if (self._cached_extra_prepost_with_context is not None
                and self._cached_context == context):
            return self._cached_extra_prepost_with_context
        self._cached_context = context
        self._cached_extra_prepost_with_context = (
                self._extra_prepost_children_with_context(context))
        return self._cached_extra_prepost_with_context
    def _extra_prepost_children_with_context(self, context=None):
        if context is None:
            context = self.context
        return context.extra_prepost_drawing_elements(self)
    def all_css(self, context=None):
        if context is None:
            context = self.context
        return list(context.extra_css(self)) + self.css_list
    def all_javascript(self, context=None):
        if context is None:
            context = self.context
        return list(context.extra_javascript(self)) + self.js_list
    def as_svg(self, output_file=None, randomize_ids=False, header=XML_HEADER,
               skip_js=False, skip_css=False, context=None):
        if output_file is None:
            with StringIO() as f:
                self.as_svg(
                        f, randomize_ids=randomize_ids, header=header,
                        skip_js=skip_js, skip_css=skip_css, context=context)
                return f.getvalue()
        if context is None:
            context = self.context
        output_file.write(header)
        img_width, img_height = self.calc_render_size()
        if self.unit:
            img_width = f'{img_width}{self.unit}'
            img_height = f'{img_height}{self.unit}'
        if 'viewBox' in self.svg_args:
            view_box = self.svg_args['viewBox']
        else:
            view_box = self.view_box
        svg_args = dict(
                width=img_width, height=img_height,
                viewBox=' '.join(map(str, view_box)))
        svg_args.update(self.svg_args)
        output_file.write(SVG_START)
        context.write_svg_document_args(self, svg_args, output_file)
        output_file.write('>\n')
        css_list = self.all_css(context)
        if css_list and not skip_css:
            output_file.write(SVG_CSS_FMT.format(elements_module.escape_cdata(
                    '\n'.join(css_list))))
            output_file.write('\n')
        output_file.write('<defs>\n')
        # Write definition elements
        id_prefix = self.id_prefix
        id_prefix = self._random_id() if randomize_ids else self.id_prefix
        id_index = 0
        def id_gen(base=''):
            nonlocal id_index
            id_str = f'{id_prefix}{base}{id_index}'
            id_index += 1
            return id_str
        id_map = defaultdict(id_gen)
        prev_set = set()
        def is_duplicate(obj):
            nonlocal prev_set
            dup = id(obj) in prev_set
            prev_set.add(id(obj))
            return dup
        for element in self.other_defs:
            if hasattr(element, 'write_svg_element'):
                local = types.LocalContext(
                        context, element, self, self.other_defs)
                element.write_svg_element(
                        id_map, is_duplicate, output_file, local, False)
                output_file.write('\n')
        all_elements = self.all_elements(context=context)
        for element in all_elements:
            if hasattr(element, 'write_svg_defs'):
                local = types.LocalContext(context, element, self, all_elements)
                element.write_svg_defs(
                        id_map, is_duplicate, output_file, local, False)
        output_file.write('</defs>\n')
        # Generate ids for normal elements
        prev_def_set = set(prev_set)
        for element in all_elements:
            if hasattr(element, 'write_svg_element'):
                local = types.LocalContext(context, element, self, all_elements)
                element.write_svg_element(
                        id_map, is_duplicate, output_file, local, True)
        prev_set = prev_def_set
        # Write normal elements
        for element in all_elements:
            if hasattr(element, 'write_svg_element'):
                local = types.LocalContext(context, element, self, all_elements)
                element.write_svg_element(
                        id_map, is_duplicate, output_file, local, False)
                output_file.write('\n')
        js_list = self.all_javascript(context)
        if js_list and not skip_js:
            output_file.write(SVG_JS_FMT.format(elements_module.escape_cdata(
                    '\n'.join(js_list))))
            output_file.write('\n')
        output_file.write(SVG_END)
    def as_html(self, output_file=None, title=None, randomize_ids=False,
                context=None, fix_embed_iframe=False):
        if output_file is None:
            with StringIO() as f:
                self.as_html(
                        f, title=title, randomize_ids=randomize_ids,
                        context=context, fix_embed_iframe=fix_embed_iframe)
                return f.getvalue()
        output_file.write('<!DOCTYPE html>\n')
        output_file.write('<head>\n')
        output_file.write('<meta charset="utf-8">\n')
        if title is not None:
            output_file.write(f'<title>{xml.escape(title)}</title>\n')
        # Prevent iframe scroll bar
        if fix_embed_iframe:
            fix = self.calc_render_size()[1] / 2
            output_file.write(f'''<style>
html,body {{
  margin: 0;
  height: 100%;
}}
svg {{
  margin-bottom: {-fix}px;
}}
</style>''')
        output_file.write('</head>\n<body>\n')
        self.as_svg(
                output_file, randomize_ids=randomize_ids, header="",
                skip_css=False, skip_js=False, context=context)
        output_file.write('\n</body>\n</html>\n')
    @staticmethod
    def _random_id(length=8):
        return (random.choice(string.ascii_letters)
                + ''.join(random.choices(
                    string.ascii_letters+string.digits, k=length-1)))
    def save_svg(self, fname, encoding='utf-8', context=None):
        with open(fname, 'w', encoding=encoding) as f:
            self.as_svg(output_file=f, context=context)
    def save_html(self, fname, title=None, encoding='utf-8', context=None):
        with open(fname, 'w', encoding=encoding) as f:
            self.as_html(output_file=f, title=title, context=context)
    def save_png(self, fname, context=None):
        self.rasterize(to_file=fname, context=context)
    def rasterize(self, to_file=None, context=None):
        if to_file is not None:
            return raster.Raster.from_svg_to_file(
                    self.as_svg(context=context), to_file)
        else:
            return raster.Raster.from_svg(self.as_svg(context=context))
    def as_animation_frames(self, fps=10, duration=None, context=None):
        '''Returns a list of synced animation frames that can be converted to a
        video.'''
        if context is None:
            context = self.context
        config = context.animation_config
        if duration is None and config is not None:
            duration = config.duration
        if duration is None:
            raise ValueError('unknown animation duration, specify duration')
        if config is None:
            config = native_animation.SyncedAnimationConfig(duration)
        frames = []
        for i in range(int(duration * fps + 1)):
            time = i / fps
            frame_context = dataclasses.replace(
                    context,
                    animation_config=dataclasses.replace(
                        config,
                        freeze_frame_at=time,
                        show_playback_controls=False))
            frames.append(self.display_inline(context=frame_context))
        return frames
    def save_video(self, fname, fps=10, duration=None, mime_type=None,
                   file_type=None, context=None, verbose=False):
        self.as_video(
                fname, fps=fps, duration=duration, mime_type=mime_type,
                file_type=file_type, context=context, verbose=verbose)
    def save_gif(self, fname, fps=10, duration=None, context=None,
                 verbose=False):
        self.as_gif(
                fname, fps=fps, duration=duration, context=context,
                verbose=verbose)
    def save_mp4(self, fname, fps=10, duration=None, context=None,
                 verbose=False):
        self.as_mp4(
                fname, fps=fps, duration=duration, context=context,
                verbose=verbose)
    def save_spritesheet(self, fname, fps=10, duration=None, context=None,
                         row_length=None, verbose=False):
        self.as_spritesheet(
                fname, fps=fps, duration=duration, context=context,
                row_length=row_length, verbose=verbose)
    def as_video(self, to_file=None, fps=10, duration=None,
                 mime_type=None, file_type=None, context=None, verbose=False):
        if file_type is None and mime_type is None:
            if to_file is None or '.' not in str(to_file):
                file_type = 'mp4'
            else:
                file_type = str(to_file).split('.')[-1]
        if file_type is None:
            file_type = mime_type.split('/')[-1]
        elif mime_type is None:
            mime_type = f'video/{file_type}'
        frames = self.as_animation_frames(
                fps=fps, duration=duration, context=context)
        return video.RasterVideo.from_frames(
                frames, to_file=to_file, fps=fps, mime_type=mime_type,
                file_type=file_type, verbose=verbose)
    def as_gif(self, to_file=None, fps=10, duration=None, context=None,
               verbose=False):
        return self.as_video(
                to_file=to_file, fps=fps, duration=duration, context=context,
                mime_type='image/gif', file_type='gif', verbose=verbose)
    def as_mp4(self, to_file=None, fps=10, duration=None, context=None,
               verbose=False):
        return self.as_video(
                to_file=to_file, fps=fps, duration=duration, context=context,
                mime_type='video/mp4', file_type='mp4', verbose=verbose)
    def as_spritesheet(self, to_file=None, fps=10, duration=None, context=None,
               row_length=None, verbose=False):
        frames = self.as_animation_frames(
                fps=fps, duration=duration, context=context)
        sheet = video.render_spritesheet(
                frames, row_length=row_length, verbose=verbose)
        return raster.Raster.from_arr(sheet, out_file=to_file)
    def _repr_svg_(self):
        '''Display in Jupyter notebook.'''
        return self.as_svg(randomize_ids=True)
    def display_inline(self, context=None):
        '''Display inline in the Jupyter web page.'''
        return jupyter.JupyterSvgInline(self.as_svg(
                randomize_ids=True, context=context))
    def display_iframe(self, context=None):
        '''Display within an iframe the Jupyter web page.'''
        w, h = self.calc_render_size()
        html = self.as_html(fix_embed_iframe=True, context=context)
        return jupyter.JupyterSvgFrame(html, w, h, mime='text/html')
    def display_image(self, context=None):
        '''Display within an img in the Jupyter web page.'''
        return jupyter.JupyterSvgImage(self.as_svg(context=context))
