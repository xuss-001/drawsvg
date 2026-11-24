'''Tests for per-interval easing of animated numeric attributes.

Run with pytest.
'''

import copy

import pytest

import drawsvg as draw
from drawsvg.native_animation.easing import (
    CubicBezierEasing, DiscreteEasing, LinearEasing, DISCRETE, LINEAR,
    parse_easing)


def _rect_with_sequence(easings=None, key_frames=None):
    rect = draw.Rectangle(0, 0, 10, 10)
    key_frames = key_frames or [(0, 0), (1, 10), (2, 30)]
    times = [t for t, v in key_frames]
    values = [v for t, v in key_frames]
    rect.add_attribute_key_sequence(
            'x', times, values, easings=easings)
    return rect


def _svg(element):
    drawing = draw.Drawing(100, 100)
    drawing.append(element)
    return drawing.as_svg()


def test_default_easing_is_linear():
    rect = _rect_with_sequence()
    timeline = rect.animation_data.attr_timelines['x']
    assert timeline.interpolate_at_time(0.5) == pytest.approx(5.0)
    assert timeline.interpolate_at_time(1.5) == pytest.approx(20.0)
    svg_text = _svg(rect)
    # Linear is the SVG default, so calcMode is omitted to keep the legacy
    # output.
    assert 'calcMode' not in svg_text
    assert 'keyTimes="0;0.5;1"' in svg_text


def test_linear_easing_matches_legacy_interpolation():
    rect = _rect_with_sequence(easings=[LINEAR, LinearEasing()])
    timeline = rect.animation_data.attr_timelines['x']
    legacy_rect = _rect_with_sequence()
    legacy = legacy_rect.animation_data.attr_timelines['x']
    for at_time in (-1, 0, 0.25, 0.75, 1, 1.5, 2, 3):
        assert timeline.interpolate_at_time(at_time) == pytest.approx(
                legacy.interpolate_at_time(at_time))


def test_discrete_easing_holds_previous_value_until_end():
    rect = _rect_with_sequence(easings=[DISCRETE, DISCRETE])
    timeline = rect.animation_data.attr_timelines['x']
    assert timeline.interpolate_at_time(0) == 0
    assert timeline.interpolate_at_time(0.999) == 0
    assert timeline.interpolate_at_time(1) == 10
    assert timeline.interpolate_at_time(1.999) == 10
    assert timeline.interpolate_at_time(2) == 30
    svg_text = _svg(rect)
    assert 'calcMode="discrete"' in svg_text


def test_asymmetric_bezier_easing_values():
    # Control points produce an asymmetric curve.
    easing = CubicBezierEasing(0.1, 0.8, 0.9, 0.2)
    rect = _rect_with_sequence(easings=[easing, LINEAR])
    timeline = rect.animation_data.attr_timelines['x']
    # Endpoints are exact.
    assert easing(0) == 0.0
    assert easing(1) == 1.0
    # Early progress jumps ahead (y1=0.8), so the value is above the linear
    # 2.5 at t=0.25; late progress lags behind.
    early = timeline.interpolate_at_time(0.25)
    late = timeline.interpolate_at_time(0.75)
    assert early == pytest.approx(10 * easing(0.25))
    assert late == pytest.approx(10 * easing(0.75))
    assert early > 2.5
    assert late < 7.5
    # Monotonic in time.
    samples = [timeline.interpolate_at_time(t / 10) for t in range(11)]
    assert samples == sorted(samples)


def test_horizontal_tangent_endpoints():
    # CSS ease-out: start tangent is horizontal (y1=0).
    ease_out = CubicBezierEasing(0, 0, 0.58, 1)
    # CSS ease-in: end tangent is horizontal (y2=1).
    ease_in = CubicBezierEasing(0.42, 0, 1, 1)
    assert ease_out(0.01) > 0
    assert ease_in(0.99) < 1
    # Ease-out is ahead of linear progress at the midpoint and vice versa.
    assert ease_out(0.5) == pytest.approx(0.685, abs=0.01)
    assert ease_in(0.5) == pytest.approx(0.315, abs=0.01)
    rect = _rect_with_sequence(easings=[ease_out, ease_in])
    timeline = rect.animation_data.attr_timelines['x']
    assert timeline.interpolate_at_time(0.5) == pytest.approx(
            10 * ease_out(0.5))
    assert timeline.interpolate_at_time(1.5) == pytest.approx(
            10 + 20 * ease_in(0.5))


def test_bezier_allows_y_overshoot():
    easing = CubicBezierEasing(0.5, -0.5, 0.5, 1.5)
    midpoint = easing(0.15)
    # y coordinates may leave [0, 1] while x coordinates may not.
    assert midpoint < 0
    assert easing(0.85) > 1
    with pytest.raises(ValueError):
        CubicBezierEasing(-0.01, 0, 0.5, 1)
    with pytest.raises(ValueError):
        CubicBezierEasing(0.5, 0, 1.01, 1)
    # Overshoot easing still anchors at both ends.
    assert easing(0) == 0 and easing(1) == 1


def test_invalid_control_points_raise():
    with pytest.raises(ValueError):
        CubicBezierEasing(float('nan'), 0, 0.5, 1)
    with pytest.raises(ValueError):
        CubicBezierEasing(0, 0, 0.5, float('inf'))
    with pytest.raises(TypeError):
        CubicBezierEasing(True, 0, 0.5, 1)
    with pytest.raises(TypeError):
        CubicBezierEasing('0.5', 0, 0.5, 1)
    with pytest.raises(ValueError):
        parse_easing('bounce')
    with pytest.raises(TypeError):
        parse_easing(123)
    with pytest.raises(TypeError):
        parse_easing((0.1, 0.2, 0.3))


def test_easing_count_must_match_interval_count():
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, x=0)
    rect.add_key_frame(1, x=10)
    rect.add_key_frame(2, x=30)
    timeline = rect.animation_data.attr_timelines['x']
    with pytest.raises(ValueError):
        timeline.set_easings([DISCRETE])
    with pytest.raises(ValueError):
        timeline.set_easings([LINEAR, LINEAR, LINEAR])
    timeline.set_easings([DISCRETE, LINEAR])
    assert timeline.interpolate_at_time(0.5) == 0
    assert timeline.as_animate_elements()
    # Extending with a mismatched per-run count raises too.
    other = draw.Rectangle(0, 0, 10, 10)
    with pytest.raises(ValueError):
        other.add_attribute_key_sequence(
                'x', [0, 1, 2], [0, 1, 2], easings=[LINEAR])


def test_first_key_frame_cannot_take_an_easing():
    rect = draw.Rectangle(0, 0, 10, 10)
    with pytest.raises(ValueError):
        rect.add_key_frame(0, x=0, easing=LINEAR)


def test_mixed_easing_timeline_values_and_svg_runs():
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, x=0)
    rect.add_key_frame(1, x=10, easing=LINEAR)
    rect.add_key_frame(2, x=20, easing=DISCRETE)
    rect.add_key_frame(3, x=40,
                       easing=CubicBezierEasing(0.25, 0.1, 0.25, 1))
    timeline = rect.animation_data.attr_timelines['x']
    assert timeline.interpolate_at_time(0.5) == pytest.approx(5)
    assert timeline.interpolate_at_time(1.5) == 10
    assert timeline.interpolate_at_time(1.999) == 10
    assert timeline.interpolate_at_time(2) == 20
    svg_text = _svg(rect)
    assert svg_text.count('<animate') == 3
    assert 'calcMode="linear"' in svg_text
    assert 'calcMode="discrete"' in svg_text
    assert 'calcMode="spline"' in svg_text
    assert 'keySplines="0.25 0.1 0.25 1"' in svg_text
    # Runs are sequential and non-overlapping.
    assert 'begin="1s"' in svg_text and 'begin="2s"' in svg_text


def test_svg_freeze_frames_match_python_values():
    easing = CubicBezierEasing(0.3, 0.7, 0.6, 0.2)
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, x=0)
    rect.add_key_frame(1, x=10, easing=DISCRETE)
    rect.add_key_frame(2, x=50, easing=easing)
    timeline = rect.animation_data.attr_timelines['x']
    import re
    for at_time in (0, 0.5, 1, 1.25, 1.75, 2):
        config = draw.SyncedAnimationConfig(
                duration=2, freeze_frame_at=at_time)
        drawing = draw.Drawing(
                100, 100, context=draw.Context(animation_config=config))
        frozen = draw.Rectangle(0, 0, 10, 10)
        frozen.animation_data = copy.deepcopy(rect.animation_data)
        drawing.append(frozen)
        match = re.search(r'<rect ([^>]*)/', drawing.as_svg())
        svg_x = float(re.search(r'x="([^"]+)"', match.group(1)).group(1))
        assert svg_x == pytest.approx(
                timeline.interpolate_at_time(at_time))


def test_repeated_export_does_not_mutate_key_frame_data():
    easing = CubicBezierEasing(0.3, 0.7, 0.6, 0.2)
    rect = _rect_with_sequence(easings=[DISCRETE, easing])
    timeline = rect.animation_data.attr_timelines['x']
    snapshot = (
            copy.deepcopy(timeline.times), copy.deepcopy(timeline.values),
            copy.deepcopy(timeline.easings))
    first = _svg(rect)
    second = _svg(rect)
    assert first == second
    assert (timeline.times, timeline.values, timeline.easings) == snapshot


def test_same_time_adjacent_key_frames_jump_instantly():
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, x=0)
    rect.add_key_frame(1, x=10, easing=LINEAR)
    rect.add_key_frame(1, x=99, easing=DISCRETE)
    rect.add_key_frame(2, x=200,
                       easing=CubicBezierEasing(0.4, 0, 0.6, 1))
    timeline = rect.animation_data.attr_timelines['x']
    assert timeline.interpolate_at_time(0.999) == pytest.approx(9.99)
    assert timeline.interpolate_at_time(1) == 99
    assert timeline.interpolate_at_time(1.5) > 99
    svg_text = _svg(rect)
    # The jump appears as two sequential runs: old value held until t=1 and
    # the next run starting from the new value 99.
    assert 'values="0;10"' in svg_text
    assert 'values="99;200"' in svg_text


def test_parse_easing_accepts_supported_spellings():
    assert parse_easing(None) == LINEAR
    assert parse_easing('linear') == LINEAR
    assert parse_easing('discrete') == DISCRETE
    bezier = parse_easing((0.1, 0.2, 0.3, 0.4))
    assert isinstance(bezier, CubicBezierEasing)
    assert parse_easing(LINEAR) is LINEAR
    assert isinstance(parse_easing(DiscreteEasing()), DiscreteEasing)


def test_non_numeric_attributes_keep_legacy_hold_behavior():
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, fill='red')
    rect.add_key_frame(1, fill='green', easing=DISCRETE)
    rect.add_key_frame(2, fill='blue',
                       easing=CubicBezierEasing(0.4, 0, 0.6, 1))
    timeline = rect.animation_data.attr_timelines['fill']
    assert timeline.interpolate_at_time(0.5) == 'red'
    assert timeline.interpolate_at_time(1.5) == 'green'
    assert timeline.interpolate_at_time(2) == 'blue'


def test_invert_y_preserves_bezier_easing():
    config = draw.SyncedAnimationConfig(duration=2)
    drawing = draw.Drawing(
            100, 100,
            context=draw.Context(invert_y=True, animation_config=config))
    rect = draw.Rectangle(0, 0, 10, 10)
    rect.add_key_frame(0, y=0)
    rect.add_key_frame(2, y=20,
                       easing=CubicBezierEasing(0.4, 0, 0.6, 1))
    drawing.append(rect)
    svg_text = drawing.as_svg()
    assert 'calcMode="spline"' in svg_text
    assert 'keySplines="0.4 0 0.6 1"' in svg_text
