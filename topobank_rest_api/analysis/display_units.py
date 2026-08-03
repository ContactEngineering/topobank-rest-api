"""
Choosing the units an analysis plot is labelled in.

An analysis reports its results in the unit of the measurement it ran on, and a
card plots every result in the unit of the first of them. That unit need not suit
the data: a measurement stored in millimetres but a hundred nanometres across
produces an axis labelled in mm with ticks around 1×10⁻⁴, which is not a scale
anyone reads off a plot (ContactEngineering/ce-ui#39).

The extent of each data series is recorded in its metadata when the analysis runs,
so a unit that fits the data can be chosen here without reading the series back out
of the object store.

Both axes are rewritten together, over a single base length unit. The units of a
plot are all derived from one measurement unit — a height distribution is plotted
against `mm` and in `mm⁻¹` — and rescaling one axis on its own would leave a
probability density in units that no longer integrate to one over its abscissa.
"""

import logging
import re

from SurfaceTopography.Support.UnitConversion import (
    get_unit_conversion_factor,
    length_units,
    suggest_length_unit,
)

_log = logging.getLogger(__name__)

#: Superscript digits, the way the workflows write an exponent: `µm³`, `mm⁻¹`.
_SUPERSCRIPT_DIGITS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
}

_DIGIT_SUPERSCRIPTS = {digit: sup for sup, digit in _SUPERSCRIPT_DIGITS.items()}

_EXPONENT_PATTERN = re.compile(r"^(?P<base>.+?)(?P<sign>⁻?)(?P<digits>[⁰¹²³⁴⁵⁶⁷⁸⁹]+)$")


def parse_length_power(unit):
    """
    Split a unit into the length it is built from and the power it is raised to.

    Parameters
    ----------
    unit : str or None
        A unit as an analysis reports it, e.g. `mm`, `mm⁻¹` or `µm³`.

    Returns
    -------
    tuple of (str, int) or None
        The base length unit and its exponent, or None if the unit is not a power
        of a length: a dimensionless axis (`1`, or the empty string a workflow
        writes for a count), or anything else we do not recognize.
    """
    if unit is None:
        return None
    if unit in length_units:
        return unit, 1
    match = _EXPONENT_PATTERN.match(unit)
    if match is None:
        return None
    base = match.group("base")
    if base not in length_units:
        return None
    exponent = int("".join(_SUPERSCRIPT_DIGITS[d] for d in match.group("digits")))
    if match.group("sign"):
        exponent = -exponent
    if exponent == 0:
        return None
    return base, exponent


def format_length_power(base, exponent):
    """
    Write a power of a length unit the way the workflows do.

    Parameters
    ----------
    base : str
        A length unit, e.g. `nm`.
    exponent : int
        The power it is raised to.

    Returns
    -------
    str
        e.g. `nm`, `nm⁻¹`, `nm³`.
    """
    if exponent == 1:
        return base
    digits = "".join(_DIGIT_SUPERSCRIPTS[d] for d in str(abs(exponent)))
    return f"{base}{'⁻' if exponent < 0 else ''}{digits}"


def natural_display_units(axes):
    """
    Pick the units an analysis plot reads most naturally in.

    Parameters
    ----------
    axes : dict
        One entry per axis, keyed by name, each a dict with

        - `unit`: the unit the axis would otherwise be labelled in
        - `extents`: the extent of each series on that axis, as
          `(unit, lower, upper)` in the unit of the analysis that produced it
        - `scale`: 'linear' or 'log', the scale the axis is drawn on

    Returns
    -------
    dict
        The unit for each axis, unchanged wherever no better choice can be made.

    Notes
    -----
    The base length unit is chosen from an axis that *is* a length, i.e. one whose
    exponent is one — a height or a distance, the quantity whose scale a reader is
    judging. Every other axis built from the same base is then rewritten over it,
    keeping its own exponent, so the axes of a plot stay consistent with each
    other.

    A plot with no plain-length axis, such as a power-spectral density plotted
    against `µm⁻¹` and in `µm³`, is left alone: choosing a unit from a reciprocal
    or a volume means deciding what "natural" means for those, which belongs with
    moving unit conversion to the frontend (ContactEngineering/ce-ui#36).
    """
    units = {name: axis["unit"] for name, axis in axes.items()}
    powers = {name: parse_length_power(axis["unit"]) for name, axis in axes.items()}
    lengths = {name: power for name, power in powers.items() if power is not None}
    if not lengths:
        return units

    bases = {base for base, _ in lengths.values()}
    if len(bases) > 1:
        # Every unit of a plot is derived from one measurement unit, so this does
        # not arise; rescaling would be guesswork if it did.
        _log.warning(
            "Axes of a plot are built from more than one length unit (%s), keeping "
            "the units as reported.",
            ", ".join(sorted(bases)),
        )
        return units

    # If both axes are lengths — a distance against a height — the first one wins,
    # and callers pass the abscissa first, since that is the axis whose scale a
    # reader is judging.
    reference = [name for name, (_, exponent) in lengths.items() if exponent == 1]
    if not reference:
        return units

    name = reference[0]
    new_base = _suggest_base(
        lengths[name][0], axes[name]["extents"], axes[name]["scale"]
    )
    if new_base is None:
        return units

    return {
        name: (
            format_length_power(new_base, powers[name][1])
            if name in lengths
            else unit
        )
        for name, unit in units.items()
    }


def _suggest_base(current_base, extents, scale):
    """
    The length unit in which the data of a plain-length axis reads most naturally.

    Parameters
    ----------
    current_base : str
        The length unit the axis is currently in.
    extents : iterable of (str, float, float)
        The extent of each series, in the unit of its own analysis.
    scale : str
        'linear' or 'log'.

    Returns
    -------
    str or None
        The length unit to use, or None if the data does not determine one.
    """
    in_meters = []
    for unit, lower, upper in extents:
        power = parse_length_power(unit)
        if power is None or power[1] != 1:
            continue
        to_meters = get_unit_conversion_factor(power[0], "m")
        for bound in (lower, upper):
            # A series can diverge, and a NaN comes back from JSON as null, so
            # check before converting rather than after.
            if not _is_finite(bound):
                continue
            value = bound * to_meters
            # Only positive values appear on a logarithmic axis; a distribution
            # that reaches zero or below says nothing about where its ticks go.
            if scale == "log" and value <= 0:
                continue
            in_meters.append(value)

    # Nothing usable: analyses computed before the extent was recorded carry none,
    # and a series of all zeros has no scale.
    if not in_meters or all(value == 0 for value in in_meters):
        return None

    lower_in_meters = min(in_meters)
    upper_in_meters = max(in_meters)
    try:
        return suggest_length_unit(scale, lower_in_meters, upper_in_meters)
    except (RuntimeError, ValueError) as exc:
        # `suggest_length_unit` raises if it cannot name the decade it arrives at.
        # An axis in the unit the analysis reported is better than no plot.
        _log.warning(
            "Cannot suggest a display unit for data between %g m and %g m on a %s "
            "axis, keeping '%s'. Cause: %s",
            lower_in_meters,
            upper_in_meters,
            scale,
            current_base,
            exc,
        )
        return None


def series_extents(analyses, axis):
    """
    Collect the extent of every data series of a set of analyses.

    Parameters
    ----------
    analyses : iterable of topobank.analysis.models.WorkflowResult
        The analyses shown on a card. This reads `result_metadata`, which is one
        object read per analysis, and the card reads it for every analysis anyway
        while collecting series names and conversion factors. `WorkflowResult`
        caches it per instance, so being called first here rather than there does
        not add a read — and it never touches the series data itself.
    axis : str
        'x' or 'y'.

    Returns
    -------
    list of (str, float, float)
        One entry per series that records an extent, as expected by
        `natural_display_units`.
    """
    extents = []
    for analysis in analyses:
        metadata = analysis.result_metadata
        if metadata is None:
            continue
        unit = metadata.get(f"{axis}unit")
        if unit is None:
            continue
        for series in metadata.get("series", []):
            extent = series.get(f"{axis}Range")
            if extent is None or len(extent) != 2:
                continue
            lower, upper = extent
            extents.append((unit, lower, upper))
    return extents


def _is_finite(value):
    """Whether a value is a finite number.

    Series are serialized to JSON, where a NaN is written as null and an infinity
    as a string, so a range read back from metadata can hold either.
    """
    try:
        return float("-inf") < float(value) < float("inf")
    except (TypeError, ValueError):
        return False
