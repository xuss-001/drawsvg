'''Export mixed linear, discrete, and cubic-Bezier key frame easing.'''

import drawsvg as draw


d = draw.Drawing(
    100, 100,
    animation_config=draw.SyncedAnimationConfig(duration=3))
r = draw.Rectangle(0, 0, 20, 20, fill='steelblue')
r.add_attribute_key_sequence(
    'x',
    [0, 1, 2, 3],
    [0, 30, 30, 80],
    easing=[
        'linear',
        'discrete',
        (0.42, 0, 0.58, 1),
    ],
)
d.append(r)

for time in (0.5, 1.5, 2.5):
    print(time, r.interpolate_at_time(time)['x'])

d.save_svg('eased-animation.svg')
