# -*- coding: utf-8 -*-
'''Distance-positioned route labels along polylines for drawsvg.

Run from the repository root::

    python examples/polyline_labels.py

This writes ``examples/polyline-labels.svg`` and
``examples/polyline-labels.png`` and prints a numeric verification report.

The figure exercises:
  * combinations of long and very short segments,
  * forward vs. reversed routes (text stays upright, never upside down),
  * a polyline nested inside translate/rotate/non-uniform-scale groups,
  * nearest along-route adjustment for endpoint clearance,
  * the direction rule used when a label center sits exactly at a corner,
  * the explicit error raised when no position can fit.

Geometry convention
-------------------
All placement math is done in *final canvas coordinates*.  The full transform
chain is applied to the polyline first, so arc length and tangents reflect
nested translation, rotation and non-uniform scaling.  The returned label is a
``<g translate(cx,cy) rotate(angle)>`` in those canvas coordinates and should be
appended to the drawing root (not back inside the transformed source group).

Corner direction
----------------
A straight label has one orientation.  When its center is exactly at a
polyline vertex the default rule (``corner_direction='outgoing'``) uses the
tangent of the segment leaving that vertex (the final endpoint uses the last
segment).  ``'incoming'``, ``'bisector'`` (angle bisector, reversal symmetric),
``'longer'`` and ``'auto'`` (best clearance) are also available.
'''

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drawsvg as draw  # noqa: E402
from drawsvg.polyline_text import (  # noqa: E402
    InsufficientSpaceForLabelError,
    PolylineGeometry,
    layout_polyline_label,
)

HERE = os.path.dirname(os.path.abspath(__file__))

W = 1080
PANEL_H = 168
TOP0 = 64
GAP = 16
N_PANELS = 6
H = TOP0 + N_PANELS * (PANEL_H + GAP) + 24

GREEN = '#2ca02c'
RED = '#d62728'
BLUE = '#1f77b4'
GRAY = '#9aa0a6'

report = []


def check(name, condition, detail=''):
    report.append((name, bool(condition), detail))
    line = ('PASS ' if condition else 'FAIL ') + name
    if detail:
        line += '  [' + detail + ']'
    print(line)
    assert condition, name


def dist_rect(placement, endpoint):
    return PolylineGeometry.point_rectangle_distance(
            endpoint[0], endpoint[1], placement.center, placement.axis,
            placement.width, placement.height)


def panel(d, index, title, subtitle=''):
    top = TOP0 + index * (PANEL_H + GAP)
    d.append(draw.Rectangle(16, top, W - 32, PANEL_H, rx=10, ry=10,
                            fill='#fafbfc', stroke='#e3e6e8', stroke_width=1))
    d.append(draw.Text(title, 17, 34, top + 25, fill='#111',
                       font_weight='bold', text_anchor='start',
                       dominant_baseline='central'))
    if subtitle:
        d.append(draw.Text(subtitle, 12.5, 34, top + 46, fill='#5f6368',
                           text_anchor='start', dominant_baseline='central'))
    return top


def clearance_disks(d, points, radius):
    for ex, ey in (points[0], points[-1]):
        d.append(draw.Circle(ex, ey, radius, fill=GREEN, fill_opacity=0.10,
                             stroke=GREEN, stroke_width=1.4,
                             stroke_dasharray='5 4'))
        d.append(draw.Circle(ex, ey, 3.2, fill='#111'))


def vertex_dots(d, points):
    for x, y in points:
        d.append(draw.Circle(x, y, 2.6, fill='white', stroke=GRAY,
                             stroke_width=1.4))


def add_label(d, points, text, w, h, distance, radius, **kw):
    label = draw.PolylineLabel(
            points, text, w, h, distance, radius,
            show_bounds=True, center_marker=True,
            font_size=kw.pop('font_size', 15),
            fill=kw.pop('fill', BLUE), font_weight='bold',
            bounds_kwargs=kw.pop(
                    'bounds_kwargs',
                    dict(fill='white', fill_opacity=0.92, stroke=RED,
                         stroke_width=1.5)),
            **kw)
    d.append(label)
    return label


d = draw.Drawing(W, H, origin=(0, 0))
d.append(draw.Rectangle(0, 0, W, H, fill='white'))
d.append(draw.Text('Polyline route labels: distance positioning, orientation '
                   'and endpoint clearance', 22, 24, 28, fill='#111',
                   font_weight='bold', text_anchor='start',
                   dominant_baseline='central'))

# ---------------------------------------------------------------------------
# Panel 1: long + short segment combination
# ---------------------------------------------------------------------------
top = panel(d, 0, '1. Long + short segments',
            'Center at target arc distance; tangent follows the segment under '
            'the center. Green disks = endpoint clearance regions.')
pts1 = [(70, top + 120), (330, top + 120), (344, top + 128),
        (348, top + 150), (600, top + 150), (905, top + 98)]
d.append(draw.Lines(*[v for xy in pts1 for v in xy], fill='none',
                    stroke='#7a7f85', stroke_width=2.4,
                    stroke_linejoin='round'))
vertex_dots(d, pts1)
R1 = 16
clearance_disks(d, pts1, R1)
lab1 = add_label(d, pts1, 'LONG-SHORT', 118, 24, 150, R1)
check('p1 center at target s=150',
      abs(lab1.distance - 150) < 1e-6 and not lab1.adjusted,
      'center=%s angle=%.1f deg' % (tuple(round(v, 1) for v in lab1.center),
                                    lab1.angle_deg))
check('p1 clears endpoints',
      all(dist_rect(lab1, e) >= R1 - 1e-6 for e in (pts1[0], pts1[-1])))

# ---------------------------------------------------------------------------
# Panel 2: forward vs reversed routes (upright, not upside down)
# ---------------------------------------------------------------------------
top = panel(d, 1, '2. Forward vs. reversed route',
            'The same sloped segment in forward and reversed point order; '
            'upright normalization yields the same readable angle.')
y_hi, y_lo = top + 84, top + 126
fwd_geom = [(120, y_hi), (470, y_lo)]
fwd_pts = fwd_geom
rev_geom = [(610, y_hi), (960, y_lo)]
rev_pts = list(reversed(rev_geom))
d.append(draw.Line(fwd_geom[0][0], fwd_geom[0][1],
                   fwd_geom[1][0], fwd_geom[1][1],
                   stroke=GRAY, stroke_width=2.4))
d.append(draw.Line(rev_geom[0][0], rev_geom[0][1],
                   rev_geom[1][0], rev_geom[1][1],
                   stroke=GRAY, stroke_width=2.4))
mid_f = PolylineGeometry(fwd_pts).total_length / 2
mid_r = PolylineGeometry(rev_pts).total_length / 2
lf = add_label(d, fwd_pts, 'FORWARD', 96, 22, mid_f, 8)
lr = add_label(d, rev_pts, 'REVERSED', 104, 22, mid_r, 8)
d.append(draw.Text('travel ->', 12.5, 295, top + 150, fill=GRAY,
                   text_anchor='middle'))
d.append(draw.Text('travel <- (point list reversed)', 12.5, 785, top + 150,
                   fill=GRAY, text_anchor='middle'))
check('p2 forward upright', -90 < lf.angle_deg <= 90,
      '%.2f deg' % lf.angle_deg)
check('p2 reversed upright', -90 < lr.angle_deg <= 90,
      '%.2f deg' % lr.angle_deg)
check('p2 reversal keeps the same upright angle',
      abs(lf.angle_deg - lr.angle_deg) < 1e-6,
      'fwd=%.2f rev=%.2f' % (lf.angle_deg, lr.angle_deg))

# ---------------------------------------------------------------------------
# Panel 3: nested transforms
# ---------------------------------------------------------------------------
top = panel(d, 2, '3. Nested translate / rotate / non-uniform scale',
            'Length and tangent use the full transformed geometry; the label '
            'is an unscaled canvas box appended at the drawing root.')
local_line = draw.Lines(0, 0, 220, 0, 260, 42, 360, 42,
                        fill='none', stroke=GRAY, stroke_width=2.4)
inner = draw.Group(transform='rotate(-18)')
inner.append(local_line)
nested = draw.Group(transform='translate(150,%d) scale(1.5,0.85)' % (top + 128))
nested.append(inner)
d.append(nested)
p3 = layout_polyline_label(local_line, 'TRANSFORMED', 132, 24, 150, 14, root=d)
lab3 = draw.PolylineLabel.from_placement(
        p3, show_bounds=True, center_marker=True, font_size=15,
        fill=BLUE, font_weight='bold',
        bounds_kwargs=dict(fill='white', fill_opacity=0.92, stroke=RED,
                           stroke_width=1.5))
d.append(lab3)
clearance_disks(d, p3.geometry.points, 14)
check('p3 ctm resolved from drawing root',
      draw.find_element_ctm(d, local_line) is not None)
check('p3 transformed length exceeds local length',
      p3.total_length > PolylineGeometry(local_line).total_length,
      'L=%.1f center=%s' % (p3.total_length,
                            tuple(round(v, 1) for v in p3.center)))
check('p3 clears transformed endpoints',
      all(dist_rect(p3, e) >= 14 - 1e-6
          for e in (p3.endpoint_start, p3.endpoint_end)))

# ---------------------------------------------------------------------------
# Panel 4: nearest along-route adjustment
# ---------------------------------------------------------------------------
top = panel(d, 3, '4. Automatic nearest adjustment for clearance',
            'Requested center (gray ghost box) intrudes into the start disk, '
            'so the label slides along the route by the minimum amount.')
pts4 = [(110, top + 110), (930, top + 110)]
d.append(draw.Line(pts4[0][0], pts4[0][1], pts4[1][0], pts4[1][1],
                   stroke=GRAY, stroke_width=2.4))
R4, w4, h4, target4 = 22, 120, 24, 40
clearance_disks(d, pts4, R4)
req_x = PolylineGeometry(pts4).point_at(target4)[0]
d.append(draw.Rectangle(req_x - w4 / 2, top + 110 - h4 / 2, w4, h4,
                        fill='#9aa0a6', fill_opacity=0.18, stroke=GRAY,
                        stroke_width=1.4, stroke_dasharray='6 4'))
d.append(draw.Line(req_x, top + 98, req_x, top + 122, stroke=GRAY,
                   stroke_width=2))
d.append(draw.Text('requested s=40', 12, req_x, top + 86, fill='#5f6368',
                   text_anchor='middle'))
lab4 = add_label(d, pts4, 'ADJUSTED', w4, h4, target4, R4, font_size=15)
expect_s = R4 + w4 / 2
check('p4 moved to clearance + width/2',
      abs(lab4.distance - expect_s) < 1e-4 and lab4.adjusted,
      's=%.2f expected=%.2f' % (lab4.distance, expect_s))
check('p4 clears start disk', dist_rect(lab4, pts4[0]) >= R4 - 1e-6)
d.append(draw.Line(req_x, top + 142, lab4.center[0], top + 142,
                   stroke=RED, stroke_width=1.6))
d.append(draw.Circle(req_x, top + 142, 2.4, fill=GRAY))
d.append(draw.Circle(lab4.center[0], top + 142, 2.6, fill=RED))
d.append(draw.Text('+%.0f units' % lab4.shift, 12.5,
                   (req_x + lab4.center[0]) / 2, top + 154, fill=RED,
                   text_anchor='middle'))

# ---------------------------------------------------------------------------
# Panel 5: corner direction
# ---------------------------------------------------------------------------
top = panel(d, 4, '5. Label center exactly at a corner',
            'Default outgoing-segment rule (left) vs. optional angle '
            'bisector (right); both deterministic.')
corner_a = [(150, top + 74), (250, top + 74), (322, top + 146)]
d.append(draw.Lines(*[v for xy in corner_a for v in xy], fill='none',
                    stroke=GRAY, stroke_width=2.4, stroke_linejoin='round'))
s_corner_a = PolylineGeometry(corner_a).cum[1]
lab5a = add_label(d, corner_a, 'OUT', 50, 20, s_corner_a, 4, font_size=13)
d.append(draw.Text("corner_direction='outgoing'", 12.5, 240, top + 160,
                   fill='#5f6368', text_anchor='middle'))

corner_b = [(620, top + 74), (720, top + 74), (792, top + 146)]
d.append(draw.Lines(*[v for xy in corner_b for v in xy], fill='none',
                    stroke=GRAY, stroke_width=2.4, stroke_linejoin='round'))
s_corner_b = PolylineGeometry(corner_b).cum[1]
p5b = layout_polyline_label(corner_b, 'BIS', 50, 20, s_corner_b, 4,
                            corner_direction='bisector')
lab5b = draw.PolylineLabel.from_placement(
        p5b, show_bounds=True, center_marker=True, font_size=13,
        fill=BLUE,
        bounds_kwargs=dict(fill='white', fill_opacity=0.92, stroke=RED,
                           stroke_width=1.5))
d.append(lab5b)
d.append(draw.Text("corner_direction='bisector'", 12.5, 710, top + 160,
                   fill='#5f6368', text_anchor='middle'))
out_angle = math.degrees(math.atan2(72, 72))  # outgoing segment (72, 72)
check('p5 outgoing uses leaving segment (45 deg)',
      abs(lab5a.angle_deg - out_angle) < 1e-6,
      '%.1f deg' % lab5a.angle_deg)
check('p5 bisector sits between horizontal and 45 deg',
      0.0 < p5b.angle_deg < 45.0, '%.1f deg' % p5b.angle_deg)

# ---------------------------------------------------------------------------
# Panel 6: insufficient space -> explicit error
# ---------------------------------------------------------------------------
top = panel(d, 5, '6. Insufficient space reports a clear error',
            'Text is never shrunk and the route is never changed; an '
            'InsufficientSpaceForLabelError (a ValueError) is raised.')
short = [(120, top + 106), (260, top + 106)]
d.append(draw.Line(120, top + 106, 260, top + 106,
                   stroke=GRAY, stroke_width=2.4))
R6, w6 = 30, 220
clearance_disks(d, short, R6)
error_message = None
raised = False
try:
    layout_polyline_label(short, 'TOO WIDE', w6, 24, 70, R6)
except InsufficientSpaceForLabelError as exc:
    raised = True
    error_message = str(exc)
check('p6 raises InsufficientSpaceForLabelError', raised)
d.append(draw.Rectangle(360, top + 76, 680, 62, rx=8, ry=8,
                        fill='#fdecea', stroke=RED, stroke_width=1.4))
d.append(draw.Text('raise InsufficientSpaceForLabelError', 15, 378,
                   top + 98, fill='#a50e0e', font_weight='bold',
                   text_anchor='start', dominant_baseline='central'))
d.append(draw.Text('subclass of ValueError / RuntimeError', 12.5, 378,
                   top + 121, fill='#a50e0e', text_anchor='start',
                   dominant_baseline='central'))

svg_path = os.path.join(HERE, 'polyline-labels.svg')
png_path = os.path.join(HERE, 'polyline-labels.png')
d.save_svg(svg_path)
png_ok = True
try:
    d.save_png(png_path)
except Exception as exc:  # Cairo system library missing, etc.
    png_ok = False
    print('PNG render skipped:', repr(exc))

print('\nVerification summary:')
failed = [n for n, ok, _ in report if not ok]
print('  %d/%d geometry checks passed'
      % (len(report) - len(failed), len(report)))
print('  SVG:', svg_path)
if png_ok:
    print('  PNG:', png_path)
if error_message:
    print('  error example:', error_message[:140])
if failed:
    raise SystemExit('failed checks: ' + ', '.join(failed))
