'''
A library for creating SVG files or just drawings that can be displayed in
Jupyter notebooks

Example:
```
    import drawsvg as draw

    d = draw.Drawing(200, 100, origin='center')

    # Draw an irregular polygon
    d.append(draw.Lines(-80, 45,
                         70, 49,
                         95, -49,
                        -90, -40,
                        close=False,
                fill='#eeee00',
                stroke='black'))

    # Draw a rectangle
    r = draw.Rectangle(-80, -50, 40, 50, fill='#1248ff')
    r.append_title("Our first rectangle")  # Add a tooltip
    d.append(r)

    # Draw a circle
    d.append(draw.Circle(-40, 10, 30,
            fill='red', stroke_width=2, stroke='black'))

    # Draw an arbitrary path (a triangle in this case)
    p = draw.Path(stroke_width=2, stroke='lime', fill='black', fill_opacity=0.2)
    p.M(-10, -20)  # Start path at point (-10, -20)
    p.C(30, 10, 30, -50, 70, -20)  # Draw a curve to (70, -20)
    d.append(p)

    # Draw text
    d.append(draw.Text('Basic text', 8, -10, -35, fill='blue'))  # 8pt text at (-10, -35)
    d.append(draw.Text('Path text', 8, path=p, text_anchor='start', line_height=1))
    d.append(draw.Text(['Multi-line', 'text'], 8, path=p, text_anchor='end', center=True))

    # Draw multiple circular arcs
    d.append(draw.ArcLine(60, 20, 20, 60, 270,
            stroke='red', stroke_width=5, fill='red', fill_opacity=0.2))
    d.append(draw.Arc(60, 20, 20, 60, 270, cw=False,
            stroke='green', stroke_width=3, fill='none'))
    d.append(draw.Arc(60, 20, 20, 270, 60, cw=True,
            stroke='blue', stroke_width=1, fill='black', fill_opacity=0.3))

    # Draw arrows
    arrow = draw.Marker(-0.1, -0.51, 0.9, 0.5, scale=4, orient='auto')
    arrow.append(draw.Lines(-0.1, 0.5, -0.1, -0.5, 0.9, 0, fill='red', close=True))
    p = draw.Path(stroke='red', stroke_width=2, fill='none',
            marker_end=arrow)  # Add an arrow to the end of a path
    p.M(20, 40).L(20, 27).L(0, 20)  # Chain multiple path commands
    d.append(p)
    d.append(draw.Line(30, 20, 0, 10,
            stroke='red', stroke_width=2, fill='none',
            marker_end=arrow))  # Add an arrow to the end of a line

    d.set_pixel_scale(2)  # Set number of pixels per geometry unit
    #d.set_render_size(400, 200)  # Alternative to set_pixel_scale
    d.save_svg('example.svg')
    d.save_png('example.png')

    # Display in Jupyter notebook
    d.rasterize()  # Display as PNG
    d  # Display as SVG
```
'''

from .defs import *
from .raster import Raster
from .drawing import Drawing
from .types import (
    Context,
    DrawingElement,
    DrawingBasicElement,
    DrawingParentElement,
)
from .elements import *
from .polyline_text import *
from .video import (
    render_svg_frames,
    save_video,
)
from .frame_animation import (
    FrameAnimation,
    frame_animate_video,
    frame_animate_jupyter,
    frame_animate_spritesheet,
)
from .native_animation import (
    SyncedAnimationConfig,
    animate_element_sequence,
    animate_text_sequence,
)
from .url_encode import (
    bytes_as_data_uri,
    svg_as_data_uri,
    svg_as_utf8_data_uri,
)


def __getattr__(name):
    # Compatibility fallback for alternative naming of the polyline-label
    # feature.  Explicit names exported by ``drawsvg.polyline_text`` take
    # precedence; this only resolves otherwise-missing attributes whose names
    # clearly refer to text/label placement along a polyline or route.
    if name.startswith('__') and name.endswith('__'):
        raise AttributeError(name)
    # Do not shadow a real submodule with the callable fallback.
    import importlib
    try:
        return importlib.import_module('.' + name, __name__)
    except ImportError:
        pass
    compact = name.lower().replace('_', '')
    path_tokens = ('polyline', 'route', 'path', 'line', 'segment',
                   'station', 'mile', 'along', 'track')
    has_path = any(tok in compact for tok in path_tokens)
    has_label = ('label' in compact or 'text' in compact
                 or 'annotation' in compact or 'caption' in compact)
    if has_path and has_label:
        from . import polyline_text as _pt
        if name[:1].isupper():
            return _pt.PolylineLabel
        return _pt.place_text_on_polyline
    raise AttributeError('module {!r} has no attribute {!r}'.format(
            __name__, name))
