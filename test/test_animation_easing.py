'''Tests for key frame easing and SVG/Python animation consistency.'''

import math
import xml.etree.ElementTree as ET

import pytest

import drawsvg as draw


def _find_animate(svg, attribute_name):
    root = ET.fromstring(svg)
    for element in root.iter():
        if (element.tag.endswith('animate')
                and element.get('attributeName') == attribute_name):
            return element
    raise AssertionError(f'no animate element for {attribute_name}')


def _bezier_coordinate(t, p1, p2):
    return (3*(1-t)*(1-t)*t*p1 + 3*(1-t)*t*t*p2 + t*t*t)


def _bezier_progress(x, spline):
    x1, y1, x2, y2 = map(float, spline.split())
    low, high = 0.0, 1.0
    for _ in range(64):
        t = (low + high) / 2
        if _bezier_coordinate(t, x1, x2) < x:
            low = t
        else:
            high = t
    return _bezier_coordinate((low + high) / 2, y1, y2)


def _sample_svg_animate(element, time, duration):
    values = [float(v) for v in element.get('values').split(';')]
    key_times = [float(v) for v in element.get('keyTimes').split(';')]
    fraction = time / duration
    index = sum(t <= fraction for t in key_times)
    if index >= len(key_times):
        return values[-1]
    if index <= 0:
        return values[0]
    if fraction == key_times[index-1] or element.get('calcMode') == 'discrete':
        return values[index-1]
    start, end = key_times[index-1], key_times[index]
    local_fraction = (fraction-start) / (end-start)
    if element.get('calcMode') == 'spline':
        splines = element.get('keySplines').split(';')
        local_fraction = _bezier_progress(
                local_fraction, splines[index-1])
    start_value, end_value = values[index-1], values[index]
    return start_value * (1-local_fraction) + end_value * local_fraction


def _make_animated_circle(times, values, easings=None, duration=None):
    if duration is None:
        duration = times[-1]
    config = draw.SyncedAnimationConfig(duration=duration)
    d = draw.Drawing(100, 100, animation_config=config)
    circle = draw.Circle(0, 0, 1)
    circle.add_attribute_key_sequence(
            'cx', times, values, easing=easings)
    d.append(circle)
    return d, circle


def test_default_easing_remains_linear_and_unchanged():
    d, circle = _make_animated_circle([0, 1, 2], [0, 10, 20])

    assert circle.interpolate_at_time(0.5)['cx'] == 5
    assert circle.interpolate_at_time(1.5)['cx'] == 15

    animate = _find_animate(d.as_svg(), 'cx')
    assert animate.get('calcMode') is None
    assert animate.get('keySplines') is None
    assert animate.get('values') == '0;10;20'


def test_asymmetric_cubic_bezier_values():
    easing = draw.CubicBezierEasing(0.1, 0.7, 0.2, 1)
    circle = draw.Circle(0, 0, 1)
    circle.add_attribute_key_sequence(
            'cx', [0, 1], [0, 100], easing=[easing])

    assert circle.interpolate_at_time(0.1)['cx'] == pytest.approx(
            49.8089068174676, abs=1e-10)
    assert circle.interpolate_at_time(0.5)['cx'] == pytest.approx(
            93.547441388767, abs=1e-10)
    assert circle.interpolate_at_time(0.75)['cx'] == pytest.approx(
            98.7868470749465, abs=1e-10)

    animate = circle.animation_data.attr_timelines['cx'].as_animate_element(
            draw.SyncedAnimationConfig(1))
    assert animate.args['calcMode'] == 'spline'
    assert animate.args['keySplines'] == '0.1 0.7 0.2 1'


def test_cubic_bezier_horizontal_endpoint_tangents():
    easing = draw.CubicBezierEasing(0.42, 0, 0.58, 1)
    circle = draw.Circle(0, 0, 1)
    circle.add_attribute_key_sequence(
            'cx', [0, 1], [0, 100], easing=[easing])

    assert circle.interpolate_at_time(0.001)['cx'] == pytest.approx(
            0.000189050155194539, abs=1e-15)
    assert circle.interpolate_at_time(0.999)['cx'] == pytest.approx(
            99.9998109498448, abs=1e-10)
    assert circle.interpolate_at_time(0.5)['cx'] == pytest.approx(50)


def test_mixed_easings_match_between_svg_and_frozen_values():
    times = [0, 1, 2, 3, 4]
    values = [0, 10, 20, 30, 40]
    easings = [
        'linear',
        'discrete',
        draw.CubicBezierEasing(0.1, 0.7, 0.2, 1),
        'linear',
    ]
    d, circle = _make_animated_circle(
            times, values, easings=easings, duration=4)
    animate = _find_animate(d.as_svg(), 'cx')

    assert animate.get('calcMode') == 'spline'
    assert len(animate.get('keyTimes').split(';')) == \
            len(animate.get('values').split(';'))
    assert len(animate.get('keySplines').split(';')) == \
            len(animate.get('keyTimes').split(';')) - 1

    sample_times = [
        0, 0.25, 0.5, 0.75, 0.99,
        1, 1.25, 1.5, 1.99,
        2, 2.1, 2.5, 2.9, 3,
        3.5, 3.99, 4,
    ]
    for time in sample_times:
        expected = circle.interpolate_at_time(time)['cx']
        actual = _sample_svg_animate(animate, time, 4)
        assert actual == pytest.approx(expected, abs=1e-9), time


def test_all_discrete_easing_uses_svg_discrete_mode():
    d, circle = _make_animated_circle(
            [0, 1, 2], [0, 10, 20], easings='discrete')
    animate = _find_animate(d.as_svg(), 'cx')

    assert animate.get('calcMode') == 'discrete'
    assert animate.get('keySplines') is None
    assert circle.interpolate_at_time(0.999)['cx'] == 0
    assert circle.interpolate_at_time(1)['cx'] == 10
    assert _sample_svg_animate(animate, 0.999, 2) == 0
    assert _sample_svg_animate(animate, 1, 2) == 10


def test_easing_on_first_key_frame_applies_to_following_interval():
    circle = draw.Circle(0, 0, 1)
    circle.add_key_frame(0, cx=0, easing='discrete')
    circle.add_key_frame(1, cx=10)

    assert circle.interpolate_at_time(0.5)['cx'] == 0
    assert circle.interpolate_at_time(1)['cx'] == 10


def test_same_time_keyframes_use_last_value_at_that_time():
    d, circle = _make_animated_circle(
            [0, 1, 1, 2], [0, 10, 20, 30],
            easings=['linear', 'discrete', 'linear'])

    assert circle.interpolate_at_time(0.5)['cx'] == 5
    assert circle.interpolate_at_time(1)['cx'] == 20
    assert circle.interpolate_at_time(1.5)['cx'] == 25

    animate = _find_animate(d.as_svg(), 'cx')
    assert _sample_svg_animate(animate, 1, 2) == 20


def test_frozen_svg_uses_same_eased_values():
    times = [0, 1, 2]
    values = [0, 20, 50]
    easing = draw.CubicBezierEasing(0.42, 0, 0.58, 1)
    d, circle = _make_animated_circle(
            times, values, easings=['linear', easing], duration=2)

    for time in (0.25, 0.5, 0.75, 1.25, 1.5, 1.75):
        frozen_config = draw.SyncedAnimationConfig(
                duration=2, freeze_frame_at=time)
        frozen = draw.Drawing(
                100, 100, animation_config=frozen_config)
        frozen_circle = draw.Circle(0, 0, 1)
        frozen_circle.add_attribute_key_sequence(
                'cx', times, values, easing=['linear', easing])
        frozen.append(frozen_circle)
        root = ET.fromstring(frozen.as_svg())
        circle_element = next(
                element for element in root.iter()
                if element.tag.endswith('circle'))
        assert float(circle_element.get('cx')) == pytest.approx(
                circle.interpolate_at_time(time)['cx'], abs=1e-9)


def test_invalid_control_points_and_easing_count_raise():
    for bad_easing in [
            (-0.01, 0, 1, 1),
            (0, 0, 1.01, 1),
            (math.nan, 0, 1, 1),
            (0.5, math.inf, 0.5, 1),
            (0.1, 0.2, 0.3),
    ]:
        circle = draw.Circle(0, 0, 1)
        with pytest.raises(ValueError):
            circle.add_attribute_key_sequence(
                    'cx', [0, 1, 2], [0, 10, 20], easing=[bad_easing])

    circle = draw.Circle(0, 0, 1)
    with pytest.raises(ValueError, match='expected 2 easing values'):
        circle.add_attribute_key_sequence(
                'cx', [0, 1, 2], [0, 10, 20], easing=['linear'])
    with pytest.raises(ValueError, match='expected 2 easing values'):
        circle.add_attribute_key_sequence(
                'cx', [0, 1, 2], [0, 10, 20],
                easing=['linear', 'discrete', 'linear'])


def test_repeated_exports_do_not_mutate_keyframes():
    easing = draw.CubicBezierEasing(0.1, 0.7, 0.2, 1)
    d, circle = _make_animated_circle(
            [0, 1, 2, 3], [0, 10, 20, 30],
            easings=['linear', 'discrete', easing], duration=3)
    timeline = circle.animation_data.attr_timelines['cx']
    original = (
        list(timeline.times),
        list(timeline.values),
        list(timeline.easings),
    )

    first = d.as_svg()
    second = d.as_svg()
    assert first == second
    assert (
        timeline.times,
        timeline.values,
        timeline.easings,
    ) == original
