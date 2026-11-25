'''Auto-fit the SVG viewBox to the transformed geometry.

Run from the repository root:

    python examples/auto_viewbox.py

A Bezier curve that bulges far beyond its endpoints is put through two nested
groups (non-uniform scale + reflection, then rotation + translation).  The
script then computes a tight viewBox with equal padding on every side and
writes ``examples/auto_viewbox_demo.svg`` / ``.png``.
'''

import os

import drawsvg as draw


PADDING = 24


def build_drawing():
    d = draw.Drawing(400, 400)

    # A symmetric cubic hump plus a quadratic "leaf".  Endpoints sit on
    # y=0 while the cubic reaches y=75 (control points at y=100).
    curve = draw.Path(fill='none', stroke='#1f77b4', stroke_width=3)
    curve.M(0, 0)
    curve.C(0, 100, 100, 100, 100, 0)
    curve.Q(50, -40, 0, 0)
    curve.Z()

    # Reference dots at the untransformed control/end points.  They live in
    # the SAME nested groups as the curve so they share every transform.
    anchors = draw.Group()
    for x, y, r in ((0, 0, 3), (100, 0, 3),
                    (0, 100, 2.5), (100, 100, 2.5), (50, -40, 2.5)):
        anchors.append(draw.Circle(x, y, r, fill='#d62728'))

    reflected = draw.Group(transform='scale(1.2, -0.8)')
    reflected.append(curve)
    reflected.append(anchors)

    rotated = draw.Group(transform='translate(150, 120) rotate(25)')
    rotated.append(reflected)
    d.append(rotated)
    return d


def main():
    d = build_drawing()

    raw = d.get_bounding_box()
    print('Transformed geometry extents (xmin, ymin, xmax, ymax):')
    print('  ', tuple(round(v, 3) for v in raw))

    vb = d.fit_view_box(padding=PADDING)
    print(f'Fitted viewBox with padding={PADDING} on every side:')
    print('  ', tuple(round(v, 3) for v in vb))

    # Every side must move out by exactly PADDING.
    assert abs(vb.xmin - (raw.xmin - PADDING)) < 1e-9
    assert abs(vb.ymin - (raw.ymin - PADDING)) < 1e-9
    assert abs(vb.xmax - (raw.xmax + PADDING)) < 1e-9
    assert abs(vb.ymax - (raw.ymax + PADDING)) < 1e-9

    # Visual guide: the tight geometry box (green dashed).  Added after the
    # fit so it cannot affect the computed bounds.
    frame = draw.Rectangle(
            raw.xmin, raw.ymin, raw.width, raw.height,
            fill='none', stroke='#2ca02c', stroke_width=1.2,
            stroke_dasharray='7 5')
    d.insert(0, frame)  # render behind the curve/anchors

    # Match the viewport aspect ratio to the fitted viewBox so the equal
    # padding is rendered evenly on all sides.
    d.width = vb.width
    d.height = vb.height

    here = os.path.dirname(os.path.abspath(__file__))
    svg_path = os.path.join(here, 'auto_viewbox_demo.svg')
    d.save_svg(svg_path)
    print('Wrote', os.path.relpath(svg_path))

    try:
        d.set_pixel_scale(4)
        png_path = os.path.join(here, 'auto_viewbox_demo.png')
        d.save_png(png_path)
        print('Wrote', os.path.relpath(png_path))
    except Exception as exc:  # Cairo / system libs are optional
        print('PNG render skipped ({}): {}'.format(type(exc).__name__, exc))


if __name__ == '__main__':
    main()
