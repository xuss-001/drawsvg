'''Demonstration of per-interval easing for drawsvg key-frame animations.

Run from the repository root:

    python examples/easing_demo.py

This writes ``examples/easing_demo.svg`` and prints the frozen-frame
attribute values produced by Python interpolation at a few sample times.
The same easings drive the native SVG ``<animate>`` elements, so a browser
playing the SVG shows identical changes at the same normalized times.
'''

import os

import drawsvg as draw
from drawsvg.native_animation.easing import (
    DISCRETE, LINEAR, CubicBezierEasing)


def main():
    duration = 4
    config = draw.SyncedAnimationConfig(duration=duration)
    drawing = draw.Drawing(
            640, 220, origin=(0, 0),
            context=draw.Context(animation_config=config))

    tracks = [
        # (label, easing, row color)
        ('linear (default)', LINEAR, '#888888'),
        ('discrete hold', DISCRETE, '#d1495b'),
        ('asymmetric bezier',
         CubicBezierEasing(0.1, 0.8, 0.9, 0.2), '#2e86ab'),
        ('horizontal end tangents (ease-in-out)',
         CubicBezierEasing(0.42, 0, 0.58, 1), '#3a7d44'),
        # The last track mixes three pacings on one timeline.
        ('mixed linear / discrete / bezier', 'mixed', '#8338ec'),
    ]

    start_x, end_x = 250, 600
    row_gap = 40
    base_y = 40

    for index, (label, easing, color) in enumerate(tracks):
        y = base_y + index * row_gap
        drawing.append(draw.Text(label, 12, 10, y + 4, fill='#222222'))
        drawing.append(draw.Line(
                start_x, y, end_x, y, stroke='#dddddd', stroke_width=2))
        marker = draw.Circle(start_x, y, 7, fill=color)
        if easing == 'mixed':
            # Times 0 -> 1 -> 2 -> 4 with different pacing per interval.
            times = [0, 1, 2, 4]
            values = [start_x, start_x + 110, start_x + 220, end_x]
            marker.add_attribute_key_sequence(
                    'cx', times, values,
                    easings=[
                        LINEAR,
                        DISCRETE,
                        CubicBezierEasing(0.25, 0.1, 0.25, 1)])
        else:
            marker.add_key_frame(0, cx=start_x)
            marker.add_key_frame(duration, cx=end_x, easing=easing)
        drawing.append(marker)

    out_path = os.path.join(os.path.dirname(__file__), 'easing_demo.svg')
    drawing.save_svg(out_path)
    print('wrote', out_path)

    # Demonstrate that Python freeze frames use the same math.
    demo = draw.Circle(0, 0, 5)
    demo.add_attribute_key_sequence(
            'cx', [0, 1, 2, 4], [0, 10, 20, 40],
            easings=[
                LINEAR, DISCRETE,
                CubicBezierEasing(0.25, 0.1, 0.25, 1)])
    timeline = demo.animation_data.attr_timelines['cx']
    print('mixed-timeline frozen cx values:')
    for at_time in (0, 0.5, 1, 1.5, 1.999, 2, 3, 4):
        print('  t={}: cx={}'.format(
                at_time, timeline.interpolate_at_time(at_time)))


if __name__ == '__main__':
    main()
