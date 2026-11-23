'''Run tests with pytest'''

import dataclasses
import io
import re

import drawsvg as draw
from drawsvg.native_animation import SyncedAnimationConfig


def make_drawing(**config_overrides):
    '''Drawing with a circle animated from cx=20 to cx=100 over 2s.'''
    config_kwargs = dict(
            duration=2, start_delay=1, end_delay=0.5, repeat_count=2,
            fill='freeze', show_playback_progress=True,
            show_playback_controls=True)
    config_kwargs.update(config_overrides)
    config = SyncedAnimationConfig(**config_kwargs)
    d = draw.Drawing(120, 60, origin=(0, 0), animation_config=config)
    d.append(draw.Rectangle(0, 0, 120, 60, fill='white'))
    c = draw.Circle(5, 30, 10, fill='red')
    c.add_key_frame(0, cx=20)
    c.add_key_frame(2, cx=100)
    d.append(c)
    return d, c


def circle_cx(svg_text):
    match = re.search(r'<circle[^>]*\bcx="([^"]+)"', svg_text)
    assert match is not None
    return float(match.group(1))


def test_snapshot_has_no_animation_or_scripts_or_controls():
    d, _ = make_drawing()
    svg = d.as_snapshot_svg(2)
    assert '<animate' not in svg
    assert '<script' not in svg
    assert 'onload' not in svg
    assert 'scrub' not in svg  # Playback control UI
    # The original drawing still animates and has controls
    animated_svg = d.as_svg()
    assert '<animate' in animated_svg
    assert '<script' in animated_svg
    assert 'scrub' in animated_svg


def test_snapshot_start_delay_holds_first_value():
    d, _ = make_drawing()
    assert circle_cx(d.as_snapshot_svg(0)) == 20
    assert circle_cx(d.as_snapshot_svg(0.5)) == 20  # During start delay
    assert circle_cx(d.as_snapshot_svg(1)) == 20  # Animation starts


def test_snapshot_interpolates_during_animation():
    d, _ = make_drawing()
    assert circle_cx(d.as_snapshot_svg(2)) == 60
    assert circle_cx(d.as_snapshot_svg(1.5)) == 40


def test_snapshot_end_delay_holds_last_value():
    d, _ = make_drawing()
    assert circle_cx(d.as_snapshot_svg(3)) == 100
    assert circle_cx(d.as_snapshot_svg(3.4)) == 100  # During end delay


def test_snapshot_repeat_boundary():
    d, _ = make_drawing()
    # Cycle is 1 + 2 + 0.5 = 3.5s; the second iteration restarts at 3.5s
    assert circle_cx(d.as_snapshot_svg(3.49)) == 100
    assert circle_cx(d.as_snapshot_svg(3.5)) == 20
    assert circle_cx(d.as_snapshot_svg(4)) == 20  # Second start delay
    assert circle_cx(d.as_snapshot_svg(5.5)) == 60  # Second iteration
    assert circle_cx(d.as_snapshot_svg(6.9)) == 100  # Second end delay


def test_snapshot_fill_freeze_after_finite_repeats():
    d, _ = make_drawing()
    # Both iterations end at t=7
    assert circle_cx(d.as_snapshot_svg(7)) == 100
    assert circle_cx(d.as_snapshot_svg(100)) == 100


def test_snapshot_fill_remove_restores_original_attribute():
    d, _ = make_drawing(fill='remove')
    # Original (un-animated) cx of the circle is 5
    assert circle_cx(d.as_snapshot_svg(7)) == 5
    assert circle_cx(d.as_snapshot_svg(100)) == 5
    # During playback the animation still applies
    assert circle_cx(d.as_snapshot_svg(2)) == 60


def test_snapshot_indefinite_repeat():
    d, _ = make_drawing(repeat_count='indefinite')
    assert circle_cx(d.as_snapshot_svg(7)) == 20  # Third iteration starts
    assert circle_cx(d.as_snapshot_svg(9)) == 60
    assert circle_cx(d.as_snapshot_svg(10.4)) == 100  # Third end delay


def test_snapshot_attribute_key_sequence():
    d, _ = make_drawing()
    r = draw.Rectangle(10, 10, 20, 20, fill='blue', opacity=0.3)
    r.add_attribute_key_sequence('opacity', [0, 1, 2], [0, 1, 0])
    d.append(r)
    def rect_opacity(svg_text):
        match = re.search(r'<rect[^>]*\bopacity="([^"]+)"', svg_text)
        assert match is not None
        return float(match.group(1))
    assert rect_opacity(d.as_snapshot_svg(0.5)) == 0  # Start delay
    assert rect_opacity(d.as_snapshot_svg(1.5)) == 0.5
    assert rect_opacity(d.as_snapshot_svg(2)) == 1
    assert rect_opacity(d.as_snapshot_svg(3)) == 0
    assert rect_opacity(d.as_snapshot_svg(3.4)) == 0  # End delay
    assert rect_opacity(d.as_snapshot_svg(7)) == 0  # fill='freeze'


def test_snapshot_preserves_gradients_and_references():
    d, _ = make_drawing()
    gradient = draw.LinearGradient(0, 0, 120, 0)
    gradient.add_stop(0, 'red')
    gradient.add_stop(1, 'blue')
    d.append(draw.Rectangle(0, 40, 120, 20, fill=gradient))
    # Internal reference to another element
    shape = draw.Group()
    shape.append(draw.Rectangle(0, 0, 10, 10, fill='green'))
    d.append(draw.Use(shape, 50, 45))
    svg = d.as_snapshot_svg(2)
    assert '<linearGradient' in svg
    assert 'url(#' in svg
    assert '<use' in svg
    assert 'xlink:href="#' in svg


def test_snapshot_does_not_modify_drawing_and_is_repeatable():
    d, c = make_drawing()
    before = d.as_svg()
    svg_late = d.as_snapshot_svg(2)
    svg_early = d.as_snapshot_svg(0)
    # Exporting the later snapshot first must not affect the earlier one
    assert circle_cx(svg_late) == 60
    assert circle_cx(svg_early) == 20
    # The original drawing and animation data are unchanged
    assert d.as_svg() == before
    assert list(c.animation_data.attr_timelines['cx'].times) == [0, 2]
    assert list(c.animation_data.attr_timelines['cx'].values) == [20, 100]


def test_freeze_frame_at_still_works():
    d, _ = make_drawing()
    config = d.context.animation_config
    frozen_context = dataclasses.replace(
            d.context,
            animation_config=dataclasses.replace(config, freeze_frame_at=1))
    svg = d.as_svg(context=frozen_context)
    # freeze_frame_at interpolates the raw key frame times (no delays)
    assert circle_cx(svg) == 60
    assert '<animate' not in svg


def test_snapshot_rendered_pixels():
    pytest = __import__('pytest')
    Image = pytest.importorskip('PIL.Image')
    d, _ = make_drawing()
    from drawsvg.raster import Raster
    def pixel_at(svg_text, x, y):
        png = Raster.from_svg(svg_text).png_data
        img = Image.open(io.BytesIO(png)).convert('RGB')
        return img.getpixel((x, y))
    svg_start = d.as_snapshot_svg(0)
    svg_mid = d.as_snapshot_svg(2)
    # Circle center is at cx=20 at t=0 and cx=60 at t=2 (cy=30)
    assert pixel_at(svg_start, 20, 30) == (255, 0, 0)
    assert pixel_at(svg_start, 60, 30) == (255, 255, 255)
    assert pixel_at(svg_mid, 60, 30) == (255, 0, 0)
    assert pixel_at(svg_mid, 20, 30) == (255, 255, 255)


def test_save_snapshot_svg(tmp_path):
    d, _ = make_drawing()
    fname = tmp_path / 'snapshot.svg'
    d.save_snapshot_svg(fname, 2)
    svg = fname.read_text()
    assert circle_cx(svg) == 60
    assert '<animate' not in svg
