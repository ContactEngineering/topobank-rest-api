import traceback

from topobank.manager.utils import mailto_link_for_reporting_an_error
from topobank_rest_api.utils import get_api_url


def _bandwidths_data_entry(topo):
    """Returns an entry for bandwidths data.

    Parameters
    ----------
    topo : Topography

    Returns
    -------
    dict
    """
    lower_bound = topo.bandwidth_lower
    upper_bound = topo.bandwidth_upper

    err_message = None
    if lower_bound is None or upper_bound is None:
        err_message = f"Bandwidth for measurement '{topo.name}' is not yet available."
        link = mailto_link_for_reporting_an_error(
            f"Failure determining bandwidth (id: {topo.id})",
            "Bandwidth data calculation",
            err_message,
            traceback.format_exc(),
        )
    else:
        link = get_api_url(topo)

    short_reliability_cutoff = topo.short_reliability_cutoff

    return {
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "topography": topo,
        "link": link,
        "error_message": err_message,
        "short_reliability_cutoff": short_reliability_cutoff,
    }


def bandwidths_data(topographies):
    """Return bandwidths data as needed in surface summary plots.

    Parameters
    ----------
    topographies : list of Topography instances

    Returns
    -------
    list of dicts
        A list of data entries, sorted by 'lower_bound'.
        An entry is a dict with keys 'lower_bound', 'upper_bound',
        'topography', 'link', 'error_message'.

    If no bandwidths are available, 'lower_bound' and 'upper_bound'
    are `None`. The `error_message` should be displayed instead.
    The `link` can be used to redirect the user, e.g. for
    sending an email in order to report the error.
    This structure is expected by `plot.js` and
    also on javascript level which gets this data.
    """
    bandwidths_data = [_bandwidths_data_entry(t) for t in topographies]

    #
    # Sort by lower bound, put lower bound=None first to show error messages first in plot
    #
    def weight(entry):
        lb = entry["lower_bound"]
        return float("-inf") if lb is None else lb  # so errors appear first

    bandwidths_data.sort(key=lambda entry: weight(entry))

    return bandwidths_data
