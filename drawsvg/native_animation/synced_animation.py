from typing import Any, Callable, Dict, List, Optional, Union

import dataclasses
from collections import defaultdict
from numbers import Number

from .. import elements, types
from . import playback_control_ui, playback_control_js
from .easing import (
    Easing, LINEAR, DISCRETE, parse_easing)


@dataclasses.dataclass
class SyncedAnimationConfig:
    # Animation settings
    duration: float
    start_delay: float = 0
    end_delay: float = 0
    repeat_count: Union[int, str] = 'indefinite'
    fill: str = 'freeze'
    freeze_frame_at: Optional[float] = None

    # Playback controls
    show_playback_progress: bool = False
    show_playback_controls: bool = False  # Adds JavaScript to the drawing
    pause_on_load: bool = False
    controls_width: Optional[float] = None
    controls_height: float = 20
    controls_x: Optional[float] = None
    controls_center_y: Optional[float] = None

    # Playback control style
    bar_thickness: float = 4
    bar_hpad: float = 32
    bar_color: str = '#ccc'
    bar_past_color: str = '#05f'
    knob_rad: float = 6
    knob_fill: str = '#05f'
    pause_width: float = 16
    pause_corner_rad: float = 4
    pause_color: str = '#05f'
    pause_icon_color: str = '#eee'

    # Advanced configuration
    controls_js: str = 'DEFAULT'
    controls_js_onload: str = playback_control_js.SVG_ONLOAD
    controls_draw_function: Callable[['SyncedAnimationConfig', bool], 'Group'
            ] = playback_control_ui.draw_scrub

    @property
    def total_duration(self):
        return self.start_delay + self.duration + self.end_delay

    def extra_css(self, d, context):
        return []

    def extra_javascript(self, d, context):
        config = self._with_filled_defaults(d, context)
        if self.show_playback_controls:
            return [config.controls_js]
        return []

    def extra_onload_js(self, d, context):
        config = self._with_filled_defaults(d, context)
        if self.show_playback_controls:
            return [config.controls_js_onload]
        return []

    def extra_drawing_elements(self, d, context):
        config = self._with_filled_defaults(d, context)
        if self.show_playback_progress or self.show_playback_controls:
            # Control UI
            controls = config.controls_draw_function(
                    config, hidden=not self.show_playback_progress)
            return [controls]
        return []

    def _with_filled_defaults(self, d, context):
        # By default place the controls along the bottom edge
        width = d.view_box[2]
        x = d.view_box[0]
        if context.invert_y:
            y = d.view_box[1] + self.controls_height/2
        else:
            y = d.view_box[1] + d.view_box[3] - self.controls_height/2
        js = playback_control_js.SVG_JS_CONTENT
        if self.controls_width is not None:
            width = self.controls_width
            x += (d.view_box[2] - width) / 2
        if self.controls_x is not None:
            x = self.controls_x
        if self.controls_center_y is not None:
            y = self.controls_center_y
        if self.controls_js != 'DEFAULT':
            js = self.controls_js
        return dataclasses.replace(
                self, controls_width=width, controls_x=x, controls_center_y=y,
                controls_js=js)

    def override_args(self, args, lcontext):
        if (self.freeze_frame_at is not None
                and hasattr(lcontext.element, 'animation_data')):
            args = dict(args)
            data = lcontext.element.animation_data
            args.update(data.interpolate_at_time(self.freeze_frame_at))
        return args


@dataclasses.dataclass
class AnimatedAttributeTimeline:
    name: str
    animate_attrs: Optional[Dict[str, Any]] = None
    times: List[float] = dataclasses.field(default_factory=list)
    values: List[Any] = dataclasses.field(default_factory=list)
    easings: List[Easing] = dataclasses.field(default_factory=list)
    # When set, freeze-frame interpolation is delegated here (used by the
    # invert-y merge of separately animated y/height attributes).
    custom_interpolator: Optional[Callable[[float], Any]] = None

    def __post_init__(self):
        self.name = types.normalize_attribute_name(self.name)
        self.easings = [parse_easing(e) for e in self.easings]

    def append(self, time, value, easing=None):
        '''Append one key frame.

        ``easing`` describes the interval from the previous key frame to this
        one and must be omitted for the first key frame.  Adjacent key frames
        sharing the same time form a zero-length interval: the value changes
        instantly at that time (the later value wins) and the interval's
        easing has no visible transition.
        '''
        if self.times and time < self.times[-1]:
            raise ValueError('out-of-order key frame times')
        if easing is not None:
            if not self.times:
                raise ValueError(
                        'the first key frame has no preceding interval, so '
                        'no easing can be specified')
            self.easings.append(parse_easing(easing))
        self.times.append(time)
        self.values.append(value)

    def extend(self, times, values, easings=None):
        if len(times) != len(values):
            raise ValueError('times and values lists are mismatched lengths')
        if easings is None:
            easings = []
        easings = [parse_easing(e) for e in easings]
        expected = max(0, len(times) - 1)
        if easings and len(easings) != expected:
            raise ValueError(
                    'expected ' + str(expected) + ' easings for '
                    + str(len(times)) + ' key frames but got '
                    + str(len(easings)))
        if len(self.times) and len(times) and times[0] < self.times[-1]:
            raise ValueError('out-of-order key frame times')
        if list(times) != sorted(times):
            raise ValueError('out-of-order key frame times')
        self.times.extend(times)
        self.values.extend(values)
        self.easings.extend(easings)

    def set_easings(self, easings):
        '''Replace the pacing of every adjacent key-frame interval.'''
        parsed = [parse_easing(e) for e in easings]
        self._check_easing_count(len(parsed))
        self.easings = parsed

    def _check_easing_count(self, count):
        interval_count = max(0, len(self.times) - 1)
        if count != interval_count:
            raise ValueError(
                    str(interval_count) + ' adjacent key-frame interval(s) '
                    'require ' + str(interval_count) + ' easing(s), but '
                    + str(count) + ' were given')

    def _validated_easings(self):
        interval_count = max(0, len(self.times) - 1)
        if not self.easings:
            return [LINEAR] * interval_count
        self._check_easing_count(len(self.easings))
        return self.easings

    def interpolate_at_time(self, at_time):
        if self.custom_interpolator is not None:
            return self.custom_interpolator(at_time)
        return interpolate_value(
                self.times, self.values, self._validated_easings(), at_time)

    def as_animate_element(self, config: Optional[SyncedAnimationConfig]=None):
        '''Return the first generated SVG animation element.

        See :meth:`as_animate_elements`: mixed linear/discrete/spline
        intervals require several coordinated ``<animate>`` elements.
        '''
        return self.as_animate_elements(config)[0]

    def as_animate_elements(self,
                            config: Optional[SyncedAnimationConfig]=None):
        '''Build the SVG ``<animate>`` element(s) for this timeline.

        A single pacing mode produces one element.  Mixing linear, discrete
        and spline intervals requires one element per contiguous run because
        SVG ``calcMode`` applies to a whole ``<animate>`` element; the runs
        are scheduled back-to-back with ``fill="freeze"`` and
        ``repeatCount=1`` (indefinite repetition is only available when every
        interval shares one mode).  Key-frame data is never modified.
        '''
        if config is not None:
            total_duration = (
                    config.start_delay + config.duration + config.end_delay)
            start_delay = config.start_delay
            repeat_count = config.repeat_count
            fill = config.fill
        else:
            total_duration = self.times[-1]
            start_delay = 0
            repeat_count = 1
            fill = 'freeze'

        easings = self._validated_easings()
        key_times = [
            max(0, min(1, round((start_delay + t) / total_duration, 3)))
            for t in self.times
        ]
        values = list(self.values)
        interval_easings = list(easings)

        pad_start = not key_times or key_times[0] != 0
        pad_end = not key_times or key_times[-1] != 1
        if pad_start:
            key_times.insert(0, 0)
            values.insert(0, values[0])
            interval_easings.insert(0, LINEAR)
        if pad_end:
            key_times.append(1)
            values.append(values[-1])
            interval_easings.append(LINEAR)

        modes = [e.calc_mode for e in interval_easings]
        if all(m == 'linear' for m in modes):
            # Linear is the SVG default calcMode; omit it to preserve the
            # output of timelines without explicit easing.
            return [self._build_animate(
                    total_duration, values, key_times,
                    repeat_count=repeat_count, fill=fill,
                    calc_mode=None, key_splines=None,
                    begin=None, duration=None)]

        return self._build_mode_runs(
                key_times, values, interval_easings, total_duration,
                start_delay, repeat_count, fill,
                pad_start, pad_end)

    def _build_mode_runs(self, key_times, values, interval_easings,
                         total_duration, start_delay, repeat_count, fill,
                         pad_start, pad_end):
        # Group adjacent intervals sharing a calc_mode into one element.
        # Zero-length intervals (identical neighboring key times) cannot be
        # expressed by SMIL pacing and are folded into an adjacent run.
        positive = [
            i for i in range(len(interval_easings))
            if key_times[i] != key_times[i + 1]]
        def is_padding(index):
            return ((pad_start and index == 0)
                    or (pad_end
                        and index == len(interval_easings) - 1))
        if not any(not is_padding(i) for i in positive):
            # Every interval is zero-length: the value jumps to the final
            # key frame instantly, so emit a discrete hold ending on it.
            return [self._build_animate(
                    total_duration, [values[0], values[-1]], [0, 1],
                    repeat_count=repeat_count, fill=fill,
                    calc_mode='discrete', key_splines=None,
                    begin=None, duration=None)]

        def raw_time_at(display_index):
            index = display_index - (1 if pad_start else 0)
            if index < 0:
                return 0.0
            if index >= len(self.times):
                return self.times[-1]
            return self.times[index]

        # Each run is a compact list of interval indices.  A zero-length
        # interval always breaks a run so the instant value jump happens at
        # the shared key time: the previous run ends on the old value and the
        # next run starts from the new value, matching Python freeze frames.
        runs = []
        run_indices = [0]
        run_mode = interval_easings[0].calc_mode
        for index in range(1, len(interval_easings)):
            mode = interval_easings[index].calc_mode
            zero_before = (key_times[index] == key_times[index - 1])
            if mode != run_mode or zero_before:
                runs.append((run_indices, run_mode))
                run_indices = [index]
                run_mode = mode
            else:
                run_indices.append(index)
        runs.append((run_indices, run_mode))

        mixed = len(runs) > 1

        if mixed:
            # Padding intervals only hold the boundary value: before the
            # first run the element's own attribute applies, and after the
            # last run fill="freeze" keeps its final value, so no elements
            # are emitted for zero-duration padding.
            runs = [
                (indices, mode) for indices, mode in runs
                if raw_time_at(indices[-1] + 1)
                - raw_time_at(indices[0]) > 0]

        anim_elements = []
        for indices, mode in runs:
            start = indices[0]
            run_frames = [start] + [i + 1 for i in indices]
            run_times, run_values, run_raw_times = self._compact_run_frames(
                    run_frames, key_times, values, raw_time_at)
            run_easing_indices = [
                    i for i in indices
                    if key_times[i] != key_times[i + 1]]
            if mixed:
                # Each run animates only its own window; fill="freeze" keeps
                # the last value while later runs take over.
                raw_start = run_raw_times[0]
                raw_end = run_raw_times[-1]
                run_begin = start_delay + raw_start
                run_duration = raw_end - raw_start
                span = run_times[-1] - run_times[0]
                local_times = [0] + [
                    round((t - run_times[0]) / span, 3)
                    for t in run_times[1:-1]] + [1]
                run_repeat_count = 1
            else:
                local_times = run_times
                run_repeat_count = repeat_count
                run_begin = None
                run_duration = None

            key_splines = None
            if mode == 'spline':
                key_splines = [
                    interval_easings[i].key_spline
                    for i in run_easing_indices]
            anim_elements.append(self._build_animate(
                    total_duration, run_values, local_times,
                    repeat_count=run_repeat_count, fill=fill,
                    calc_mode=mode, key_splines=key_splines,
                    begin=run_begin, duration=run_duration))
        return anim_elements

    @staticmethod
    def _compact_run_frames(frame_indices, key_times, values, raw_time_at):
        # Drop duplicate (same-time) frames inside one run; the first frame
        # keeps its own value so a same-time jump landing on this run's start
        # is represented by the preceding run instead.
        run_times, run_values, run_raw_times = [], [], []
        for frame_index in frame_indices:
            time_value = key_times[frame_index]
            if run_times and time_value == run_times[-1]:
                continue
            run_times.append(time_value)
            run_values.append(values[frame_index])
            run_raw_times.append(raw_time_at(frame_index))
        return run_times, run_values, run_raw_times

    def _build_animate(self, total_duration, values, key_times,
                       repeat_count, fill, calc_mode, key_splines,
                       begin, duration):
        key_times_str = ';'.join(map(str, key_times))
        values_str = ';'.join(map(str, values))
        active_duration = (
                duration if duration is not None else total_duration)
        attrs = dict(
                dur=str(active_duration) + 's',
                values=values_str,
                keyTimes=key_times_str,
                repeatCount=repeat_count,
                fill=fill)
        if begin is not None and begin != 0:
            attrs['begin'] = str(begin) + 's'
        if calc_mode is not None:
            attrs['calcMode'] = calc_mode
        if key_splines is not None:
            attrs['keySplines'] = ';'.join(key_splines)
        attrs.update(self.animate_attrs or {})
        return elements.Animate(self.name, **attrs)


class AnimationHelperData:
    def __init__(self):
        self.attr_timelines = {}

    def add_key_frame(self, time, animation_args=None, easing=None,
                      **attr_values):
        for attr, val in attr_values.items():
            attr = types.normalize_attribute_name(attr)
            timeline = self.attr_timelines.get(attr)
            if timeline is None:
                timeline = AnimatedAttributeTimeline(attr, animation_args)
                self.attr_timelines[attr] = timeline
            timeline.append(time, val, easing=easing)

    def add_attribute_key_sequence(self, attr, times, values, *,
                                   animation_args=None, easings=None):
        attr = types.normalize_attribute_name(attr)
        timeline = self.attr_timelines.get(attr)
        if timeline is None:
            timeline = AnimatedAttributeTimeline(attr, animation_args)
            self.attr_timelines[attr] = timeline
        timeline.extend(times, values, easings=easings)

    def interpolate_at_time(self, at_time):
        return {
            name: timeline.interpolate_at_time(at_time)
            for name, timeline in self.attr_timelines.items()
        }

    def _timelines_adjusted_for_context(self, lcontext=None):
        all_timelines = dict(self.attr_timelines)
        if lcontext is not None and lcontext.context.invert_y:
            # Invert cy, y1, y2, ...
            for name, timeline in self.attr_timelines.items():
                if name != 'y' and lcontext.context.is_attr_inverted(name):
                    inv_timeline = AnimatedAttributeTimeline(
                            timeline.name, timeline.animate_attrs,
                            timeline.times, [-v for v in timeline.values],
                            list(timeline.easings))
                    all_timelines[name] = inv_timeline
            # Invert -y - height
            y_attrs = None
            if 'height' in all_timelines.keys():
                height_timeline = all_timelines['height']
                htimes = height_timeline.times
                hvalues = height_timeline.values
                y_attrs = height_timeline.animate_attrs
            else:
                height_timeline = None
                htimes = [0]
                hvalues = [lcontext.element.args.get('height', 0)]
            if 'y' in all_timelines.keys():
                y_timeline = all_timelines['y']
                ytimes = y_timeline.times
                yvalues = y_timeline.values
                y_attrs = y_timeline.animate_attrs
            else:
                y_timeline = None
                ytimes = [0]
                yvalues = [lcontext.element.args.get('y', 0)]
            if y_timeline is not None or height_timeline is not None:
                ytimes, yvalues = _merge_timeline_inverted_y_values(
                        ytimes, yvalues, htimes, hvalues,
                        linear_interpolate_value, linear_interpolate_value)
                if ytimes is not None:
                    merged_easings = []
                    custom_interpolator = None
                    if y_timeline is not None and height_timeline is None:
                        # Static height: negation preserves every easing.
                        merged_easings = list(y_timeline.easings)
                    elif y_timeline is not None and height_timeline is not None:
                        # The merged grid has no single matching Bezier, so
                        # freeze frames use the exact per-timeline easings
                        # while SVG export falls back to linear pacing.
                        def merged_y_value(
                                at_time,
                                y_timeline=y_timeline,
                                height_timeline=height_timeline):
                            return -y_timeline.interpolate_at_time(
                                    at_time) - height_timeline.interpolate_at_time(
                                    at_time)
                        custom_interpolator = merged_y_value
                    y_timeline = AnimatedAttributeTimeline(
                            'y', y_attrs, ytimes, yvalues,
                            easings=merged_easings,
                            custom_interpolator=custom_interpolator)
                    all_timelines['y'] = y_timeline
        return all_timelines

    def children_with_context(self, lcontext=None):
        if (lcontext is not None
                and lcontext.context.animation_config is not None
                and lcontext.context.animation_config.freeze_frame_at
                    is not None):
            return []  # Don't animate if frame is frozen
        all_timelines = self._timelines_adjusted_for_context(lcontext)
        anim_elements = []
        for timeline in all_timelines.values():
            anim_elements.extend(timeline.as_animate_elements(
                    lcontext.context.animation_config))
        return anim_elements


def linear_interpolate_value(times, values, at_time):
    if len(times) == 0:
        return 0
    idx = sum(t <= at_time for t in times)
    if idx >= len(times):
        return values[-1]
    elif idx <= 0:
        return values[0]
    elif at_time == times[idx-1]:
        return values[idx-1]
    elif isinstance(values[idx], Number) and isinstance(values[idx-1], Number):
        fraction = (at_time-times[idx-1]) / (times[idx]-times[idx-1])
        return values[idx-1] * (1-fraction) + (values[idx] * fraction)
    else:
        return values[idx-1]

def interpolate_value(times, values, easings, at_time):
    '''Interpolate one value using one easing per adjacent key-frame pair.

    Easing only affects numeric attributes.  Non-numeric values (colors as
    strings, visibility flags, ...) keep the previous key-frame value until
    the next key frame, matching the pre-existing behavior.
    '''
    if len(times) == 0:
        return 0
    idx = sum(t <= at_time for t in times)
    if idx >= len(times):
        return values[-1]
    if idx <= 0:
        return values[0]
    if at_time == times[idx-1]:
        return values[idx-1]
    left, right = values[idx-1], values[idx]
    if not (isinstance(left, Number) and not isinstance(left, bool)
            and isinstance(right, Number) and not isinstance(right, bool)):
        return left
    span = times[idx] - times[idx-1]
    if span == 0:
        # Same-time adjacent key frames: instant jump to the later value.
        return right
    progress = (at_time - times[idx-1]) / span
    eased = easings[idx-1](progress)
    return left * (1 - eased) + right * eased

def _merge_timeline_inverted_y_values(ytimes, yvalues, htimes, hvalues,
                                      yinterpolate, hinterpolate):
    if len(yvalues) == 1:
        try:
            return htimes, [-yvalues[0]-h for h in hvalues]
        except TypeError:
            return None, None
    elif len(hvalues) == 1:
        try:
            return ytimes, [-y-hvalues[0] for y in yvalues]
        except TypeError:
            return None, None
    elif ytimes == htimes:
        try:
            return ytimes, [-y-h for y, h in zip(yvalues, hvalues)]
        except TypeError:
            return None, None
    try:
        # Offset y-value by height if invert_y
        # Merge key_times for y and height animations
        new_times = []
        new_values = []
        hi = yi = 0
        inf = float('inf')
        ht = htimes[0] if len(htimes) else inf
        yt = ytimes[0] if len(ytimes) else inf
        while ht < inf and yt < inf:
            if yt < ht:
                h_val = hinterpolate(htimes, hvalues, yt)
                new_times.append(yt)
                new_values.append(-yvalues[yi] - h_val)
                yi += 1
            elif ht < yt:
                y_val = yinterpolate(ytimes, yvalues, ht)
                new_times.append(ht)
                new_values.append(-y_val - hvalues[hi])
                hi += 1
            else:
                new_times.append(yt)
                new_values.append(-yvalues[yi] - hvalues[hi])
                yi += 1
                hi += 1
            yt = ytimes[yi] if yi < len(ytimes) else inf
            ht = htimes[hi] if hi < len(htimes) else inf
        return new_times, new_values
    except TypeError:
        return None, None

def animate_element_sequence(times, element_sequence):
    '''Animate a list of elements to appear one-at-a-time in sequence.

    Elements should already be added to the drawing before using this.
    '''
    for i, elem in enumerate(element_sequence):
        if elem is None:
            continue  # Draw nothing during this time
        key_times = [times[i]]
        values = ['visible']
        if i > 0:
            key_times.insert(0, times[i-1])
            values.insert(0, 'hidden')
        if i < len(element_sequence) - 1:
            key_times.append(times[i+1])
            values.append('hidden')
        elem.add_attribute_key_sequence('visibility', key_times, values)

def animate_text_sequence(container, times: List[float], values: List[str],
                          *text_args, kwargs_list=None, **text_kwargs):
    '''Animate a sequence of text to appear one-at-a-time in sequence.

    Multiple `Text` elements will be appended to the given `container`.
    '''
    if kwargs_list is None:
        kwargs_list = [None] * len(values)
    new_elements = []
    for val, current_kw in zip(values, kwargs_list):
        kwargs = dict(text_kwargs)
        if current_kw is not None:
            kwargs.update(current_kw)
        new_elements.append(elements.Text(val, *text_args, **kwargs))
    animate_element_sequence(times, new_elements)
    container.extend(new_elements)
