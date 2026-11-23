'''Example: export static SVG snapshots of a native animation.

Run from the repository root:
    python3 examples/snapshot_export.py

Writes snapshot SVG files (no animation elements, playback controls, or
scripts) into the examples/ directory.  These can be used with renderers
that do not support SVG animation.
'''

import os

import drawsvg as draw

# An animation with a 1s start delay, 2s of motion, a 0.5s end delay, and
# two repeat iterations.  Each iteration is 3.5s; playback ends at 7s and
# the last frame is kept (fill='freeze').
config = draw.SyncedAnimationConfig(
        duration=2, start_delay=1, end_delay=0.5, repeat_count=2,
        fill='freeze', show_playback_controls=True)
d = draw.Drawing(120, 60, origin=(0, 0), animation_config=config)

# Static content and a gradient are preserved in every snapshot
gradient = draw.LinearGradient(0, 0, 120, 0)
gradient.add_stop(0, '#fdd')
gradient.add_stop(1, '#ddf')
d.append(draw.Rectangle(0, 0, 120, 60, fill=gradient))

c = draw.Circle(5, 30, 10, fill='red', stroke='black', stroke_width=1)
c.add_key_frame(0, cx=20)
c.add_key_frame(2, cx=100)
d.append(c)

r = draw.Rectangle(10, 45, 20, 10, fill='blue')
r.add_attribute_key_sequence('opacity', [0, 1, 2], [0.2, 1, 0.2])
d.append(r)

out_dir = os.path.dirname(os.path.abspath(__file__))

# The animated original (with playback controls) is unchanged by exporting
d.save_svg(os.path.join(out_dir, 'snapshot-animated.svg'))

# Export static snapshots at various playback times (in seconds):
#   0.5  during the start delay (first frame held)
#   2    halfway through the first iteration
#   4    start delay of the second iteration
#   5.5  halfway through the second iteration
#   8    after the final iteration (fill='freeze' keeps the last frame)
for time in (0.5, 2, 4, 5.5, 8):
    d.save_snapshot_svg(
            os.path.join(out_dir, f'snapshot-{time:g}s.svg'), time)
    print(f'exported snapshot at t={time:g}s')
