"""
Tests for the units an analysis plot is labelled in.

An analysis reports its results in the unit of the measurement it ran on, which
need not suit the data: a measurement stored in millimetres but a hundred
nanometres across produced an axis labelled in mm with ticks around 1×10⁻⁴
(ContactEngineering/ce-ui#39).
"""

import types

import pytest

from topobank_rest_api.analysis.display_units import (
    format_length_power,
    natural_display_units,
    parse_length_power,
    series_extents,
)


def _analysis(metadata):
    """Something with a `result_metadata`, which is all `series_extents` reads."""
    return types.SimpleNamespace(result_metadata=metadata)


def _axes(x_unit, y_unit, extents, x_scale="linear", y_scale="linear"):
    """A plot whose extents are all on the x axis, which is the usual case: the
    abscissa is the length whose scale a reader judges."""
    return {
        "x": {"unit": x_unit, "extents": extents, "scale": x_scale},
        "y": {"unit": y_unit, "extents": [], "scale": y_scale},
    }


class TestParseLengthPower:
    @pytest.mark.parametrize(
        "unit,expected",
        [
            ("mm", ("mm", 1)),
            ("µm", ("µm", 1)),
            ("mm⁻¹", ("mm", -1)),
            ("µm³", ("µm", 3)),
            ("nm²", ("nm", 2)),
            ("m⁻³", ("m", -3)),
        ],
    )
    def test_recognizes_powers_of_a_length(self, unit, expected):
        assert parse_length_power(unit) == expected

    @pytest.mark.parametrize("unit", ["1", "", "s", "s⁻¹", None, "kg⁻¹", "m⁰"])
    def test_rejects_anything_else(self, unit):
        assert parse_length_power(unit) is None


class TestFormatLengthPower:
    @pytest.mark.parametrize(
        "exponent,expected", [(1, "nm"), (-1, "nm⁻¹"), (3, "nm³"), (-3, "nm⁻³")]
    )
    def test_writes_the_exponent_as_the_workflows_do(self, exponent, expected):
        assert format_length_power("nm", exponent) == expected

    @pytest.mark.parametrize("unit", ["mm", "mm⁻¹", "µm³", "nm⁻³"])
    def test_round_trips_with_the_parser(self, unit):
        base, exponent = parse_length_power(unit)
        assert format_length_power(base, exponent) == unit


class TestNaturalDisplayUnits:
    def test_the_case_from_the_issue(self):
        """Data of 1e-4 mm is a hundred nanometres."""
        units = natural_display_units(_axes("mm", "mm⁻¹", [("mm", 0.0, 1e-4)]))
        assert units["x"] == "nm"

    def test_rewrites_every_axis_over_one_base(self):
        """A density has to stay consistent with its abscissa: rescaling the heights
        of a distribution to nm without its probability density would leave a curve
        whose area is off by a factor of a million."""
        units = natural_display_units(_axes("mm", "mm⁻¹", [("mm", 0.0, 1e-4)]))
        assert units == {"x": "nm", "y": "nm⁻¹"}

    def test_keeps_higher_powers_of_the_base(self):
        units = natural_display_units(_axes("mm", "mm³", [("mm", 0.0, 1e-4)]))
        assert units == {"x": "nm", "y": "nm³"}

    def test_leaves_a_dimensionless_axis_alone(self):
        units = natural_display_units(_axes("mm", "1", [("mm", 0.0, 1e-4)]))
        assert units == {"x": "nm", "y": "1"}

    def test_a_unit_that_already_fits_is_kept(self):
        units = natural_display_units(_axes("µm", "µm⁻¹", [("µm", 0.0, 5.0)]))
        assert units == {"x": "µm", "y": "µm⁻¹"}

    def test_scales_up_as_well_as_down(self):
        units = natural_display_units(_axes("nm", "nm⁻¹", [("nm", 0.0, 2e7)]))
        assert units == {"x": "mm", "y": "mm⁻¹"}

    def test_considers_every_analysis_on_the_card(self):
        """Analyses can report in different units; the widest extent decides."""
        extents = [("mm", 0.0, 1e-4), ("nm", 0.0, 500.0)]
        assert natural_display_units(_axes("mm", "mm⁻¹", extents))["x"] == "nm"

    def test_the_scale_of_the_axis_changes_the_choice(self):
        """A linear axis is served by the unit of its largest value, a logarithmic
        one by a unit further down its range, so the same data gives different
        answers."""
        extents = [("m", 1e-9, 1e-3)]
        assert natural_display_units(_axes("m", "m⁻¹", extents))["x"] == "mm"
        assert (
            natural_display_units(_axes("m", "m⁻¹", extents, x_scale="log"))["x"]
            == "nm"
        )

    def test_a_logarithmic_axis_ignores_non_positive_values(self):
        """A zero cannot be drawn on a log axis and would take the range with it."""
        units = natural_display_units(
            _axes("mm", "mm⁻¹", [("mm", 0.0, 1e-4)], x_scale="log")
        )
        assert units["x"] == "nm"

    def test_a_plot_without_a_plain_length_axis_is_left_alone(self):
        """A power-spectral density is plotted against `µm⁻¹` and in `µm³`; picking a
        unit from a reciprocal or a volume is out of scope here."""
        axes = {
            "x": {"unit": "µm⁻¹", "extents": [("µm⁻¹", 1.0, 1e4)], "scale": "log"},
            "y": {"unit": "µm³", "extents": [("µm³", 1e-9, 1e-3)], "scale": "log"},
        }
        assert natural_display_units(axes) == {"x": "µm⁻¹", "y": "µm³"}

    def test_a_wholly_dimensionless_plot_is_left_alone(self):
        assert natural_display_units(_axes("1", "1", [("1", 0.0, 1e-4)])) == {
            "x": "1",
            "y": "1",
        }

    def test_no_extents_keeps_the_reported_units(self):
        """Analyses computed before the extent was recorded carry none."""
        assert natural_display_units(_axes("mm", "mm⁻¹", [])) == {
            "x": "mm",
            "y": "mm⁻¹",
        }

    def test_extents_in_a_foreign_unit_are_ignored(self):
        units = natural_display_units(_axes("mm", "mm⁻¹", [("s", 0.0, 1e-4)]))
        assert units["x"] == "mm"

    def test_extents_of_the_wrong_power_are_ignored(self):
        """Only the extent of the length axis itself says what the scale is."""
        units = natural_display_units(_axes("mm", "mm⁻¹", [("mm⁻¹", 0.0, 1e-4)]))
        assert units["x"] == "mm"

    def test_a_series_of_zeros_has_no_scale(self):
        units = natural_display_units(_axes("mm", "mm⁻¹", [("mm", 0.0, 0.0)]))
        assert units["x"] == "mm"

    def test_extents_with_nothing_finite_are_ignored(self):
        """A distribution can diverge, and a NaN comes back from JSON as null."""
        extents = [("mm", float("-inf"), float("inf")), ("mm", None, None)]
        assert natural_display_units(_axes("mm", "mm⁻¹", extents))["x"] == "mm"

    def test_a_finite_bound_counts_even_next_to_a_non_finite_one(self):
        """Half an extent is still information about the scale of the data."""
        units = natural_display_units(_axes("mm", "mm⁻¹", [("mm", None, 1e-4)]))
        assert units["x"] == "nm"

    def test_missing_units_are_kept(self):
        assert natural_display_units(_axes(None, None, [("mm", 0.0, 1e-4)])) == {
            "x": None,
            "y": None,
        }

    def test_axes_over_different_bases_are_left_alone(self):
        """Does not arise — every unit of a plot comes from one measurement unit —
        but rescaling would be guesswork if it did."""
        axes = {
            "x": {"unit": "mm", "extents": [("mm", 0.0, 1e-4)], "scale": "linear"},
            "y": {"unit": "nm⁻¹", "extents": [], "scale": "linear"},
        }
        assert natural_display_units(axes) == {"x": "mm", "y": "nm⁻¹"}

    @pytest.mark.parametrize("scale", ["linear", "log"])
    def test_never_suggests_a_unit_outside_the_thousand_steps(self, scale):
        """Ångström is a length unit but not a thousand-step, so it never reads as
        the natural choice next to its neighbours."""
        axes = _axes("m", "m⁻¹", [("m", 1e-10, 3e-10)], x_scale=scale)
        assert natural_display_units(axes)["x"] != "Å"


class TestSeriesExtents:
    def test_collects_the_extent_of_every_series(self):
        analyses = [
            _analysis(
                {
                    "xunit": "mm",
                    "series": [
                        {"name": "a", "xRange": [0.0, 1e-4]},
                        {"name": "b", "xRange": [1e-5, 2e-4]},
                    ],
                }
            )
        ]
        assert series_extents(analyses, "x") == [("mm", 0.0, 1e-4), ("mm", 1e-5, 2e-4)]

    def test_reads_the_requested_axis(self):
        analyses = [
            _analysis(
                {
                    "xunit": "mm",
                    "yunit": "nm",
                    "series": [
                        {"name": "a", "xRange": [0.0, 1.0], "yRange": [2.0, 3.0]}
                    ],
                }
            )
        ]
        assert series_extents(analyses, "y") == [("nm", 2.0, 3.0)]

    def test_skips_series_without_an_extent(self):
        analyses = [
            _analysis(
                {
                    "xunit": "mm",
                    "series": [{"name": "a"}, {"name": "b", "xRange": [1.0, 2.0]}],
                }
            )
        ]
        assert series_extents(analyses, "x") == [("mm", 1.0, 2.0)]

    def test_skips_an_analysis_without_a_unit(self):
        analyses = [_analysis({"series": [{"name": "a", "xRange": [1.0, 2.0]}]})]
        assert series_extents(analyses, "x") == []

    def test_tolerates_an_analysis_without_metadata(self):
        assert series_extents([_analysis(None)], "x") == []

    def test_tolerates_a_malformed_extent(self):
        analyses = [
            _analysis(
                {
                    "xunit": "mm",
                    "series": [
                        {"name": "a", "xRange": [1.0]},
                        {"name": "b", "xRange": [1.0, 2.0]},
                    ],
                }
            )
        ]
        assert series_extents(analyses, "x") == [("mm", 1.0, 2.0)]


class TestContractWithTopobank:
    """The extent is written in `topobank` and read here, so the two have to agree
    on the key. This fails if either side renames it."""

    def test_reads_what_wrap_series_writes(self):
        from topobank.analysis.legacy.workflows import wrap_series

        wrapped = wrap_series(
            [{"name": "Height distribution", "x": [0.0, 1e-4], "y": [0.0, 2.0]}]
        )
        # `store_split_dict` merges the supplementary dict into the series entry of
        # result.json, next to the reference to the separate file.
        metadata = {
            "xunit": "mm",
            "yunit": "mm⁻¹",
            "series": [
                {"__external__": f"{w.name}.json", **w.supplementary} for w in wrapped
            ],
        }
        analyses = [_analysis(metadata)]

        assert series_extents(analyses, "x") == [("mm", 0.0, 1e-4)]
        units = natural_display_units(
            {
                axis: {
                    "unit": unit,
                    "extents": series_extents(analyses, axis),
                    "scale": "linear",
                }
                for axis, unit in (("x", "mm"), ("y", "mm⁻¹"))
            }
        )
        assert units == {"x": "nm", "y": "nm⁻¹"}
