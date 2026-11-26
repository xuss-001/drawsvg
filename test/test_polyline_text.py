'''Tests for distance-positioned, route-oriented polyline labels.

Run from the repository root:  ``python -m pytest test/ -q``
'''

import math

import pytest

import drawsvg as draw
from drawsvg.polyline_text import (
    InsufficientSpaceForLabelError,
    LabelPlacementError,
    PolylineGeometry,
    layout_polyline_label,
)


def rect_endpoint_distance(placement, endpoint):
    return PolylineGeometry.point_rectangle_distance(
        endpoint[0], endpoint[1], placement.center, placement.axis,
        placement.width, placement.height)


def assert_clears_endpoints(placement, points, clearance):
    r0, r1 = placement.clearance_radii
    assert rect_endpoint_distance(placement, points[0]) >= r0 - 1e-6
    assert rect_endpoint_distance(placement, points[-1]) >= r1 - 1e-6
    # Every reported corner is outside both disks too.
    for radius, endpoint in ((r0, points[0]), (r1, points[-1])):
        for cx, cy in placement.corners:
            assert math.hypot(cx - endpoint[0], cy - endpoint[1]) >= radius - 1e-6


# ---------------------------------------------------------------------------
# Center / orientation
# ---------------------------------------------------------------------------

def test_target_locates_center_on_straight_route():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'Road', 40, 12, 50, clearance=5)
    assert p.center == pytest.approx((50.0, 0.0), abs=1e-9)
    assert p.distance == pytest.approx(50.0, abs=1e-9)
    assert p.adjusted is False
    assert p.angle_deg == pytest.approx(0.0, abs=1e-9)


def test_center_follows_segment_and_tangent_angle():
    pts = [(0.0, 0.0), (40.0, 0.0), (60.0, 30.0), (120.0, 30.0)]
    p = layout_polyline_label(pts, 'R9', 30, 12, 70, clearance=2)
    seg_len = math.hypot(20, 30)
    u = (70 - 40) / seg_len
    expect_x = 40 + u * 20
    expect_y = u * 30
    assert p.center == pytest.approx((expect_x, expect_y), abs=1e-8)
    assert p.angle_deg == pytest.approx(math.degrees(math.atan2(30, 20)),
                                        abs=1e-8)


def test_vertical_and_negative_coordinates():
    pts = [(-20.0, -40.0), (-20.0, 60.0)]
    p = layout_polyline_label(pts, 'N-S', 30, 10, 50, clearance=0)
    assert p.center == pytest.approx((-20.0, 10.0), abs=1e-9)
    assert p.angle_deg == pytest.approx(90.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Endpoint clearance + nearest adjustment
# ---------------------------------------------------------------------------

def test_moves_inward_to_meet_start_clearance():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'ABC', 40, 12, 5, clearance=10)
    # Nearest feasible center: s >= clearance + width/2 = 30.
    assert p.distance == pytest.approx(30.0, abs=1e-5)
    assert p.center == pytest.approx((30.0, 0.0), abs=1e-5)
    assert p.adjusted is True
    assert p.shift == pytest.approx(25.0, abs=1e-5)
    assert_clears_endpoints(p, pts, 10)


def test_moves_inward_to_meet_end_clearance():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'ABC', 40, 12, 95, clearance=10)
    assert p.distance == pytest.approx(70.0, abs=1e-5)
    assert p.adjusted is True
    assert_clears_endpoints(p, pts, 10)


def test_centered_target_is_not_moved():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'ABC', 40, 12, 50, clearance=10)
    assert p.distance == pytest.approx(50.0, abs=1e-9)
    assert p.adjusted is False
    assert p.shift == pytest.approx(0.0, abs=1e-9)


def test_exact_fit_route_places_at_midpoint():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'ABCD', 80, 12, 50, clearance=10)
    assert p.distance == pytest.approx(50.0, abs=1e-5)
    assert_clears_endpoints(p, pts, 10)


def test_out_of_range_distance_is_clamped_then_adjusted():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(pts, 'ABC', 40, 12, -999, clearance=10)
    assert p.distance == pytest.approx(30.0, abs=1e-5)
    p2 = layout_polyline_label(pts, 'ABC', 40, 12, 999, clearance=10)
    assert p2.distance == pytest.approx(70.0, abs=1e-5)


def test_insufficient_space_raises_clear_error():
    pts = [(0.0, 0.0), (100.0, 0.0)]
    # width 90 + 2*clearance 20 = 130 > length 100
    with pytest.raises(InsufficientSpaceForLabelError):
        layout_polyline_label(pts, 'X' * 12, 90, 14, 50, clearance=20)
    # Also catchable as ValueError and RuntimeError.
    with pytest.raises(ValueError):
        layout_polyline_label(pts, 'X', 200, 14, 50, clearance=5)
    with pytest.raises(RuntimeError):
        layout_polyline_label(pts, 'X', 90, 14, 50, clearance=20)


def test_zero_clearance_never_blocks_placement():
    # A zero-radius keep-out is vacuous, so even an oversized box is placed.
    p = layout_polyline_label([(0, 0), (10, 0)], 'X', 200, 14, 5,
                              clearance=0)
    assert p.valid is True


def test_error_is_named_alias_family():
    assert issubclass(draw.InsufficientSpaceError, ValueError)
    assert issubclass(draw.LabelFitError, LabelPlacementError)


# ---------------------------------------------------------------------------
# Repeated points
# ---------------------------------------------------------------------------

def test_duplicate_points_do_not_break_length_or_position():
    pts = [(0, 0), (0, 0), (50, 0), (50, 0), (100, 0), (100, 0)]
    p = layout_polyline_label(pts, 'ABC', 40, 12, 50, clearance=10)
    assert p.total_length == pytest.approx(100.0, abs=1e-9)
    assert p.center == pytest.approx((50.0, 0.0), abs=1e-8)
    assert math.isfinite(p.angle_deg)


def test_all_duplicate_points_zero_clearance_is_horizontal():
    pts = [(7.0, 9.0), (7.0, 9.0), (7.0, 9.0)]
    p = layout_polyline_label(pts, 'X', 10, 8, 0, clearance=0)
    assert p.total_length == pytest.approx(0.0, abs=1e-9)
    assert p.center == pytest.approx((7.0, 9.0), abs=1e-9)
    assert p.angle_deg == pytest.approx(0.0, abs=1e-9)
    assert all(math.isfinite(v) for c in p.corners for v in c)


def test_all_duplicate_points_positive_clearance_raises_not_crash():
    pts = [(7.0, 9.0), (7.0, 9.0)]
    with pytest.raises(LabelPlacementError):
        layout_polyline_label(pts, 'X', 10, 8, 0, clearance=5)


# ---------------------------------------------------------------------------
# Upright orientation / route reversal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('pts', [
    [(0, 0), (100, 0)],
    [(0, 0), (100, 40)],
    [(0, 0), (-100, 40)],
    [(0, 0), (100, -40)],
    [(0, 0), (-100, -40)],
])
def test_text_is_always_upright(pts):
    p = layout_polyline_label(pts, 'ABC', 30, 10, 30, clearance=0)
    assert -90.0 < p.angle_deg <= 90.0


def test_reversed_route_is_not_upside_down():
    fwd_pts = [(0.0, 0.0), (100.0, 40.0)]
    rev_pts = list(reversed(fwd_pts))
    mid = PolylineGeometry(fwd_pts).total_length / 2.0
    fwd = layout_polyline_label(fwd_pts, 'ABC', 30, 10, mid, clearance=0)
    rev = layout_polyline_label(rev_pts, 'ABC', 30, 10, mid, clearance=0)
    # Midpoint is geometrically identical and the upright angle matches.
    assert rev.center == pytest.approx(fwd.center, abs=1e-8)
    assert rev.angle_deg == pytest.approx(fwd.angle_deg, abs=1e-8)
    assert abs(rev.angle_deg) <= 90.0


def test_reversal_at_corresponding_station_multisegment():
    pts = [(0, 0), (40, 0), (60, 30), (120, 30)]
    length = PolylineGeometry(pts).total_length
    s = 55.0  # interior of the diagonal segment (not a corner)
    fwd = layout_polyline_label(pts, 'ABC', 24, 10, s, clearance=0)
    rev = layout_polyline_label(pts[::-1], 'ABC', 24, 10,
                                length - s, clearance=0)
    assert rev.center == pytest.approx(fwd.center, abs=1e-7)
    assert rev.angle_deg == pytest.approx(fwd.angle_deg, abs=1e-7)


# ---------------------------------------------------------------------------
# Corner direction rule
# ---------------------------------------------------------------------------

L_CORNER = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0)]


def test_corner_default_is_outgoing_segment():
    p = layout_polyline_label(L_CORNER, 'X', 10, 8, 40, clearance=0)
    assert p.corner_detail == 'outgoing'
    assert p.angle_deg == pytest.approx(90.0, abs=1e-8)


def test_corner_incoming_rule():
    p = layout_polyline_label(L_CORNER, 'X', 10, 8, 40, clearance=0,
                              corner_direction='incoming')
    assert p.angle_deg == pytest.approx(0.0, abs=1e-8)


def test_corner_bisector_rule():
    p = layout_polyline_label(L_CORNER, 'X', 10, 8, 40, clearance=0,
                              corner_direction='bisector')
    assert p.angle_deg == pytest.approx(45.0, abs=1e-8)


# ---------------------------------------------------------------------------
# Transforms (nested translate / rotate / non-uniform scale)
# ---------------------------------------------------------------------------

def test_nonuniform_scale_changes_actual_length():
    local = [(0.0, 0.0), (100.0, 0.0)]
    p = layout_polyline_label(local, 'ABC', 40, 12, 100, clearance=0,
                              transform='scale(2, 0.5)')
    assert p.total_length == pytest.approx(200.0, abs=1e-6)
    assert p.center == pytest.approx((100.0, 0.0), abs=1e-6)


def test_rotation_transform_maps_center_and_angle():
    p = layout_polyline_label([(0, 0), (100, 0)], 'ABC', 30, 10, 50,
                              clearance=0,
                              transform='translate(10, 20) rotate(90)')
    assert p.center == pytest.approx((10.0, 70.0), abs=1e-6)
    assert p.angle_deg == pytest.approx(90.0, abs=1e-6)


def test_nested_group_transform_chain():
    inner = draw.Group(transform='rotate(90)')
    line = draw.Lines(0, 0, 100, 0, fill='none', stroke='black')
    inner.append(line)
    outer = draw.Group(transform='translate(30, 40) scale(2, 1)')
    outer.append(inner)

    p = layout_polyline_label(line, 'ABC', 40, 12, 50, clearance=0,
                              root=outer)
    assert p.center == pytest.approx((30.0, 90.0), abs=1e-6)
    assert p.angle_deg == pytest.approx(90.0, abs=1e-6)


def test_drawing_then_line_call_style_and_container_lookup():
    drawing = draw.Drawing(300, 200)
    group = draw.Group(transform='translate(20, 30) scale(1.5, 1)')
    line = draw.Lines(0, 0, 100, 0)
    group.append(line)
    drawing.append(group)
    # (drawing/root, line, text, w, h, distance, clearance)
    p = layout_polyline_label(drawing, line, 'ABC', 40, 12, 50, 0)
    assert p.total_length == pytest.approx(150.0, abs=1e-6)
    assert p.center == pytest.approx((70.0, 30.0), abs=1e-6)
    # Passing only the container group discovers the descendant line + CTM.
    p2 = layout_polyline_label(group, 'ABC', 40, 12, 50, 0)
    assert p2.center == pytest.approx((70.0, 30.0), abs=1e-6)


def test_transformed_diagonal_length_uses_canvas_units():
    # Local unit square diagonal scaled non-uniformly: (1,1)->(2,0.5) vector.
    p = layout_polyline_label([(0, 0), (1, 1)], 'X', 0.2, 0.1, 0,
                              clearance=0, transform='scale(2, 0.5)')
    assert p.total_length == pytest.approx(math.hypot(2, 0.5), abs=1e-9)


# ---------------------------------------------------------------------------
# Original graphic is not modified
# ---------------------------------------------------------------------------

def test_original_element_and_svg_unchanged():
    line = draw.Lines(0, 0, 100, 0, 120, 30, fill='none', stroke='black')
    group = draw.Group(transform='translate(5, 5)')
    group.append(line)
    drawing = draw.Drawing(200, 200)
    drawing.append(group)
    svg_before = drawing.as_svg()
    d_before = line.args['d']
    transform_before = group.args['transform']

    layout_polyline_label(line, 'ABC', 40, 12, 50, 8, root=drawing)
    place = draw.place_text_on_polyline(line, 'ABC', 40, 12, 50, 8,
                                        root=drawing)
    drawing.append(place)

    assert line.args['d'] == d_before
    assert group.args['transform'] == transform_before
    # No children were appended to the source nodes; the label is a new node.
    assert len(group.children) == 1
    assert line.children == []
    assert '<text' in drawing.as_svg()


def test_input_points_list_not_muted():
    pts = [(0, 0), (0, 0), (100, 0)]
    snapshot = list(pts)
    layout_polyline_label(pts, 'A', 10, 8, 10, 2)
    assert pts == snapshot


# ---------------------------------------------------------------------------
# Randomized clearance property
# ---------------------------------------------------------------------------

def test_random_polylines_always_clear_when_placed():
    import random
    rng = random.Random(20261127)
    for _ in range(250):
        n = rng.randint(2, 7)
        pts = [(rng.uniform(-60, 160), rng.uniform(-60, 160))
               for _ in range(n)]
        if rng.random() < 0.4:
            pts.insert(rng.randrange(len(pts)),
                       pts[rng.randrange(len(pts))])
        w = rng.uniform(8, 60)
        h = rng.uniform(6, 24)
        r = rng.uniform(0, 25)
        length = PolylineGeometry(pts).total_length
        dist = rng.uniform(0, length) if length > 1e-9 else 0
        try:
            p = layout_polyline_label(
                    pts, 'T', w, h, dist, r,
                    corner_direction=rng.choice(
                            ['outgoing', 'bisector', 'incoming', 'longer']))
        except InsufficientSpaceForLabelError:
            continue
        assert -90.0 < p.angle_deg <= 90.0
        assert_clears_endpoints(p, pts, r)


# ---------------------------------------------------------------------------
# Flexible API / aliases / SVG element
# ---------------------------------------------------------------------------

def test_positional_and_keyword_calls_equivalent():
    pts = [(0, 0), (100, 0)]
    a = draw.place_text_on_polyline(pts, 'Road', 40, 12, 50, 8)
    b = draw.PolylineLabel(text='Road', width=40, height=12, distance=50,
                           clearance=8, points=pts)
    c = draw.layout_polyline_label(points=pts, text='Road', w=40, h=12,
                                   at=50, padding=8)
    assert a.center == pytest.approx(b.center, abs=1e-9)
    assert c.center == pytest.approx(a.center, abs=1e-9)


def test_reversed_argument_order_text_first():
    pts = [(0, 0), (100, 0)]
    p = draw.layout_polyline_label('Road', 40, 12, 50, 8, pts)
    assert p.center == pytest.approx((50, 0), abs=1e-9)


def test_element_is_appendable_and_contains_text():
    d = draw.Drawing(200, 120)
    label = draw.PolylineLabel([(0, 60), (200, 60)], 'HELLO', 60, 16,
                               100, 8, fill='navy', font_size=14)
    d.append(label)
    svg = d.as_svg()
    assert '<g transform="translate(100,60) rotate(0)"' in svg
    assert 'HELLO' in svg
    assert 'text-anchor="middle"' in svg
    assert label.center == pytest.approx((100, 60), abs=1e-8)


def test_layout_result_itself_is_appendable():
    d = draw.Drawing(200, 120)
    placement = layout_polyline_label([(0, 0), (100, 0)], 'X', 30, 10,
                                      50, 0, fill='red')
    d.append(placement)  # LabelPlacement implements write_svg_element
    assert '>X<' in d.as_svg()


def test_alias_modules_importable():
    from drawsvg import labels  # noqa: F401
    from drawsvg import polyline_label  # noqa: F401
    from drawsvg import polyline_labels  # noqa: F401
    from drawsvg import along_polyline  # noqa: F401
    assert labels.PolylineLabel is draw.PolylineLabel
    assert polyline_label.layout_polyline_label is layout_polyline_label


def test_pep562_name_fallback():
    # Alternative descriptive names resolve to the same callables.
    assert draw.place_route_text_at_distance is draw.place_text_on_polyline
    assert draw.MysteryPolylineLabel is draw.PolylineLabel
    with pytest.raises(AttributeError):
        draw.definitely_not_a_thing_xyz


# ---------------------------------------------------------------------------
# Actual rendering (CairoSVG + Pillow)
# ---------------------------------------------------------------------------

def test_render_png_smoke(tmp_path):
    pytest.importorskip('cairosvg')
    from PIL import Image
    d = draw.Drawing(220, 120, origin=(0, 0))
    d.append(draw.Rectangle(0, 0, 220, 120, fill='white'))
    pts = [(20, 60), (200, 60)]
    d.append(draw.Line(20, 60, 200, 60, stroke='#999999', stroke_width=2))
    label = draw.PolylineLabel(pts, 'RENDER', 70, 18, 110, 6,
                               show_bounds=True, font_size=15,
                               fill='#1f77b4', font_weight='bold')
    d.append(label)
    png = tmp_path / 'label.png'
    d.save_png(str(png))
    im = Image.open(png).convert('RGB')
    assert im.size == (220, 120)
    # Some blue label pixels exist.
    px = im.load()
    blue = sum(1 for y in range(0, 120, 2) for x in range(0, 220, 2)
               if px[x, y][2] > 120 and px[x, y][2] > px[x, y][0] + 30)
    assert blue > 10


def test_rendered_label_color_absent_from_clearance_disks(tmp_path):
    pytest.importorskip('cairosvg')
    from PIL import Image
    width, height = 240, 120
    d = draw.Drawing(width, height, origin=(0, 0))
    d.append(draw.Rectangle(0, 0, width, height, fill='white'))
    pts = [(30, 60), (210, 60)]
    radius = 14
    # Comfortably centered -> rectangle is far from both endpoint disks.
    label = draw.PolylineLabel(pts, 'CENTER', 70, 18, 120, radius,
                               show_bounds=True, font_size=15,
                               fill='#d62728', font_weight='bold',
                               bounds_kwargs=dict(stroke='#d62728'))
    d.append(label)
    d.append(draw.Circle(30, 60, radius, fill='none', stroke='#2ca02c'))
    d.append(draw.Circle(210, 60, radius, fill='none', stroke='#2ca02c'))
    png = tmp_path / 'clearance.png'
    d.save_png(str(png))
    im = Image.open(png).convert('RGB')
    px = im.load()

    def label_red(pixel):
        r, g, b = pixel
        return r > 150 and g < 110 and b < 110

    # Check a slightly shrunken disk so anti-aliased boundary pixels cannot
    # make this conservative assertion flaky.
    safe_r = radius - 3
    for cx, cy in (pts[0], pts[-1]):
        for y in range(int(cy - safe_r), int(cy + safe_r) + 1):
            for x in range(int(cx - safe_r), int(cx + safe_r) + 1):
                if 0 <= x < width and 0 <= y < height and \
                        math.hypot(x - cx + 0.5, y - cy + 0.5) <= safe_r:
                    assert not label_red(px[x, y]), (
                        'label color inside endpoint clearance disk', x, y)
