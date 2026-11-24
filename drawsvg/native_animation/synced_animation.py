from typing import Any, Callable, Dict, List, Optional, Union

import dataclasses
import math
from collections import defaultdict
from numbers import Number

from .. import elements, types
from . import playback_control_ui, playback_control_js


LINEAR_EASING = 'linear'
DISCRETE_EASING = 'discrete'


@dataclasses.dataclass(frozen=True, init=False)
class CubicBezierEasing:
    '''Cubic Bezier animation timing.

    The curve starts at (0, 0) and ends at (1, 1).  The x coordinate is the
    normalized time and the y coordinate is the normalized attribute change.
    Both control point x coordinates must be in the inclusive range [0, 1].
    '''
    x1: float
    y1: float
    x2: float
    y2: float

    def __init__(self, x1, y1=None, x2=None, y2=None):
        if x2 is None and y2 is None and y1 is not None:
            pairs = (x1, y1)
            if not all(
                    isinstance(v, (tuple, list)) and len(v) == 2
                    for v in pairs):
                raise ValueError(
                        'cubic Bezier easing requires four values '
                        '(x1, y1, x2, y2)')
            (x1, y1), (x2, y2) = pairs
        elif y1 is None and x2 is None and y2 is None:
            try:
                values = list(x1)
            except TypeError:
                raise ValueError(
                        'cubic Bezier easing requires four values '
                        '(x1, y1, x2, y2)') from None
            if len(values) == 2 and all(
                    isinstance(v, (tuple, list)) and len(v) == 2
                    for v in values):
                (x1, y1), (x2, y2) = values
            elif len(values) == 4:
                x1, y1, x2, y2 = values
            else:
                raise ValueError(
                        'cubic Bezier easing requires four values '
                        '(x1, y1, x2, y2)')
        elif y1 is None or x2 is None or y2 is None:
            raise ValueError(
                    'cubic Bezier easing requires four values '
                    '(x1, y1, x2, y2)')
        object.__setattr__(self, 'x1', x1)
        object.__setattr__(self, 'y1', y1)
        object.__setattr__(self, 'x2', x2)
        object.__setattr__(self, 'y2', y2)
        self.__post_init__()

    def __post_init__(self):
        values = (self.x1, self.y1, self.x2, self.y2)
        if any(isinstance(v, bool) or not isinstance(v, Number)
               or not math.isfinite(v) for v in values):
            raise ValueError(
                    'cubic Bezier control points must be finite numbers')
        if not 0 <= self.x1 <= 1 or not 0 <= self.x2 <= 1:
            raise ValueError(
                    'cubic Bezier control point x coordinates must be '
                    'between 0 and 1')
        object.__setattr__(self, 'x1', float(self.x1))
        object.__setattr__(self, 'y1', float(self.y1))
        object.__setattr__(self, 'x2', float(self.x2))
        object.__setattr__(self, 'y2', float(self.y2))

    @classmethod
    def from_values(cls, values):
        return cls(values)

    @property
    def key_spline(self):
        return ' '.join(
                _format_number(v) for v in (self.x1, self.y1, self.x2, self.y2))

    @property
    def control_points(self):
        return ((self.x1, self.y1), (self.x2, self.y2))

    def progress(self, fraction):
        '''Return the eased progress for a time fraction in [0, 1].

        Bisection is used instead of Newton iteration because it remains stable
        for every valid curve, including curves with horizontal endpoint
        tangents.
        '''
        fraction = float(fraction)
        if fraction <= 0:
            return 0.0
        if fraction >= 1:
            return 1.0
        low, high = 0.0, 1.0
        for _ in range(64):
            t = (low + high) / 2
            x = _cubic_bezier_coordinate(t, self.x1, self.x2)
            if x < fraction:
                low = t
            else:
                high = t
        t = (low + high) / 2
        return _cubic_bezier_coordinate(t, self.y1, self.y2)

    def __call__(self, fraction):
        return self.progress(fraction)


CubicBezier = CubicBezierEasing


def _format_number(value):
    return format(float(value), '.12g')


def _cubic_bezier_coordinate(t, p1, p2):
    one_minus_t = 1 - t
    return (
            3 * one_minus_t * one_minus_t * t * p1
            + 3 * one_minus_t * t * t * p2
            + t * t * t)


def _looks_like_single_easing(value):
    if value is None or isinstance(value, (str, CubicBezierEasing, dict)):
        return True
    try:
        values = list(value)
    except TypeError:
        return False
    if len(values) == 4 and all(
            isinstance(v, Number) and not isinstance(v, bool) for v in values):
        return True
    if len(values) == 2 and all(
            isinstance(v, (tuple, list)) and len(v) == 2 for v in values):
        return True
    return False


def _parse_float(value, description):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{description} must be a number') from None
    if not math.isfinite(value):
        raise ValueError(f'{description} must be finite')
    return value


def normalize_easing(easing):
    '''Convert a user-specified easing into a timeline easing value.

    Returns None for unspecified (linear) easing, the string 'linear' for
    explicitly linear easing, the string 'discrete' for step/hold easing, or a
    CubicBezierEasing instance.
    '''
    if easing is None or isinstance(easing, CubicBezierEasing):
        return easing
    if isinstance(easing, dict):
        try:
            values = (easing['x1'], easing['y1'],
                      easing['x2'], easing['y2'])
        except KeyError:
            raise ValueError(
                    'cubic Bezier easing mapping requires x1, y1, x2, and y2'
                    ) from None
        return CubicBezierEasing.from_values(values)
    if isinstance(easing, str):
        value = easing.strip().lower().replace('_', '-')
        if value in ('linear', 'default'):
            return LINEAR_EASING
        if value in ('discrete', 'hold', 'step', 'step-end'):
            return DISCRETE_EASING
        named_curves = {
            'ease': (0.25, 0.1, 0.25, 1),
            'ease-in': (0.42, 0, 1, 1),
            'ease-out': (0, 0, 0.58, 1),
            'ease-in-out': (0.42, 0, 0.58, 1),
        }
        if value in named_curves:
            return CubicBezierEasing(*named_curves[value])
        if value.startswith('cubic-bezier(') and value.endswith(')'):
            value = value[len('cubic-bezier('):-1]
        values = value.replace(',', ' ').split()
        if len(values) == 4:
            return CubicBezierEasing.from_values(
                    [_parse_float(v, 'cubic Bezier control point')
                     for v in values])
        raise ValueError(
                "easing must be 'linear', 'discrete', or a cubic Bezier "
                "specified as (x1, y1, x2, y2)")
    try:
        values = list(easing)
    except TypeError:
        raise ValueError(
                "easing must be 'linear', 'discrete', or a cubic Bezier "
                "specified as (x1, y1, x2, y2)") from None
    return CubicBezierEasing.from_values(values)


def _normalize_easings(easings, interval_count):
    if interval_count < 0:
        raise ValueError('interval count cannot be negative')
    if easings is None:
        return [None] * interval_count
    if _looks_like_single_easing(easings):
        if interval_count == 0:
            raise ValueError(
                    'easing was provided, but there are no key frame '
                    'intervals to apply it to')
        easing = normalize_easing(easings)
        return [easing] * interval_count
    easings = list(easings)
    if len(easings) != interval_count:
        raise ValueError(
                f'expected {interval_count} easing values for '
                f'{interval_count} key frame intervals, got {len(easings)}')
    return [normalize_easing(easing) for easing in easings]


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
    easings: List[Any] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        self.name = types.normalize_attribute_name(self.name)
        self.times = list(self.times)
        self.values = list(self.values)
        self._pending_easing = None
        self.easings = [normalize_easing(easing)
                        for easing in self.easings]
        expected_easings = max(0, len(self.times) - 1)
        if not self.easings and expected_easings:
            self.easings = [None] * expected_easings
        if len(self.easings) != expected_easings:
            raise ValueError(
                    f'expected {expected_easings} easing values for '
                    f'{expected_easings} key frame intervals, '
                    f'got {len(self.easings)}')

    def append(self, time, value, easing=None):
        if self.times and time < self.times[-1]:
            raise ValueError('out-of-order key frame times')
        has_preceding_keyframe = bool(self.times)
        easing = normalize_easing(easing)
        if has_preceding_keyframe:
            if self._pending_easing is not None:
                interval_easing = self._pending_easing
                self._pending_easing = easing
            else:
                interval_easing = easing
        else:
            if easing not in (None, LINEAR_EASING):
                self._pending_easing = easing
            interval_easing = None
        self.times.append(time)
        self.values.append(value)
        if has_preceding_keyframe:
            self.easings.append(interval_easing)

    def extend(self, times, values, easings=None, *, easing=None):
        if easing is not None and easings is not None:
            raise ValueError('specify either easing or easings, not both')
        if easing is not None:
            easings = easing
        if len(times) != len(values):
            raise ValueError('times and values lists are mismatched lengths')
        if len(self.times) and len(times) and times[0] < self.times[-1]:
            raise ValueError('out-of-order key frame times')
        if list(times) != sorted(times):
            raise ValueError('out-of-order key frame times')
        interval_count = len(times) - (0 if self.times else 1)
        interval_count = max(0, interval_count)
        new_easings = _normalize_easings(easings, interval_count)
        self.times.extend(times)
        self.values.extend(values)
        self.easings.extend(new_easings)

    def interpolate_at_time(self, at_time):
        return interpolate_value(
                self.times, self.values, self.easings, at_time)

    def as_animate_element(self, config: Optional[SyncedAnimationConfig]=None):
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
        dur_str = f'{total_duration}s'
        values = self.values
        times = self.times
        has_easing = any(easing is not None for easing in self.easings)
        if has_easing:
            values, key_times, key_splines, calc_mode = (
                    self._expanded_eased_keyframes(
                        times, values, self.easings, total_duration,
                        start_delay))
            attrs = dict(
                    dur=dur_str,
                    values=';'.join(map(str, values)),
                    keyTimes=';'.join(key_times),
                    repeatCount=repeat_count,
                    fill=fill,
                    calcMode=calc_mode)
            if key_splines is not None:
                attrs['keySplines'] = ';'.join(key_splines)
            attrs.update(self.animate_attrs or {})
            return elements.Animate(self.name, **attrs)
        key_times = ';'.join(
            str(max(0, min(1, round(
                    (start_delay + t) / total_duration, 3))))
            for t in times
        )
        values_str = ';'.join(map(str, values))
        if not key_times.startswith('0;'):
            key_times = '0;' + key_times
            values_str = f'{values[0]};' + values_str
        if not key_times.endswith(';1'):
            key_times = key_times + ';1'
            values_str = values_str + f';{values[-1]}'
        attrs = dict(
                dur=dur_str,
                values=values_str,
                keyTimes=key_times,
                repeatCount=repeat_count,
                fill=fill)
        attrs.update(self.animate_attrs or {})
        anim = elements.Animate(self.name, **attrs)
        return anim

    def _expanded_eased_keyframes(self, times, values, easings,
                                  total_duration, start_delay):
        def normalized_time(time):
            return max(0.0, min(1.0, (start_delay + time) / total_duration))

        if all(easing == DISCRETE_EASING for easing in easings):
            key_times = []
            key_values = []
            for time, value in zip(times, values):
                key_times.append(_format_number(normalized_time(time)))
                key_values.append(value)
            if not key_times or float(key_times[0]) != 0:
                key_times.insert(0, '0')
                key_values.insert(0, values[0])
            if float(key_times[-1]) != 1:
                key_times.append('1')
                key_values.append(values[-1])
            return key_values, key_times, None, 'discrete'

        linear_spline = '0 0 1 1'
        first_time = normalized_time(times[0])
        keys = []
        if first_time > 0:
            keys.append((0.0, values[0], None))
            keys.append((first_time, values[0], linear_spline))
        else:
            keys.append((0.0, values[0], None))
        for i, easing in enumerate(easings):
            end_time = normalized_time(times[i+1])
            if easing == DISCRETE_EASING:
                keys.append((end_time, values[i], linear_spline))
                keys.append((end_time, values[i+1], linear_spline))
            else:
                spline = (easing.key_spline
                          if isinstance(easing, CubicBezierEasing)
                          else linear_spline)
                keys.append((end_time, values[i+1], spline))
        if keys[-1][0] < 1:
            keys.append((1.0, values[-1], linear_spline))
        key_times = [_format_number(k[0]) for k in keys]
        key_values = [k[1] for k in keys]
        key_splines = [k[2] for k in keys[1:]]
        return key_values, key_times, key_splines, 'spline'


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
                                   animation_args=None, easing=None,
                                   easings=None):
        if easing is not None and easings is not None:
            raise ValueError('specify either easing or easings, not both')
        if easings is not None:
            easing = easings
        attr = types.normalize_attribute_name(attr)
        timeline = self.attr_timelines.get(attr)
        if timeline is None:
            timeline = AnimatedAttributeTimeline(attr, animation_args)
            self.attr_timelines[attr] = timeline
        timeline.extend(times, values, easings=easing)

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
                            timeline.easings)
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
                y_value_count = len(yvalues)
                height_value_count = len(hvalues)
                if y_timeline is None:
                    y_interpolate = linear_interpolate_value
                else:
                    y_interpolate = (
                            lambda times, values, at_time:
                            y_timeline.interpolate_at_time(at_time))
                if height_timeline is None:
                    height_interpolate = linear_interpolate_value
                else:
                    height_interpolate = (
                            lambda times, values, at_time:
                            height_timeline.interpolate_at_time(at_time))
                ytimes, yvalues = _merge_timeline_inverted_y_values(
                        ytimes, yvalues, htimes, hvalues,
                        y_interpolate, height_interpolate)
                if ytimes is not None:
                    if len(ytimes) <= 1:
                        merged_easings = []
                    elif height_timeline is None or height_value_count == 1:
                        merged_easings = list(y_timeline.easings)
                    elif y_timeline is None or y_value_count == 1:
                        merged_easings = list(height_timeline.easings)
                    elif (ytimes == htimes
                          and y_timeline.easings == height_timeline.easings):
                        merged_easings = list(y_timeline.easings)
                    else:
                        merged_easings = [None] * (len(ytimes) - 1)
                    y_timeline = AnimatedAttributeTimeline(
                            'y', y_attrs, ytimes, yvalues, merged_easings)
                    all_timelines['y'] = y_timeline
        return all_timelines

    def children_with_context(self, lcontext=None):
        if (lcontext is not None
                and lcontext.context.animation_config is not None
                and lcontext.context.animation_config.freeze_frame_at
                    is not None):
            return []  # Don't animate if frame is frozen
        all_timelines = self._timelines_adjusted_for_context(lcontext)
        return [
            timeline.as_animate_element(lcontext.context.animation_config)
            for timeline in all_timelines.values()
        ]


def interpolate_value(times, values, easings, at_time):
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
        easing = easings[idx-1] if idx-1 < len(easings) else None
        if easing == DISCRETE_EASING:
            return values[idx-1]
        if isinstance(easing, CubicBezierEasing):
            fraction = easing.progress(fraction)
        return values[idx-1] * (1-fraction) + (values[idx] * fraction)
    else:
        return values[idx-1]


def linear_interpolate_value(times, values, at_time):
    return interpolate_value(times, values, (), at_time)


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
