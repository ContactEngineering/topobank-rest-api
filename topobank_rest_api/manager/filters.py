from django.contrib.postgres.search import SearchQuery
from django.db.models import F, OuterRef, Q, Subquery
from rest_framework.exceptions import ParseError, PermissionDenied
from topobank.manager.models import Surface

ORDER_BY_FILTER_CHOICES = {"name": "name", "date": "-created_at"}
SHARING_STATUS_FILTER_CHOICES = set(["all", "own", "others", "published"])


# v1 filter
def filter_by_search_term(request, qs):
    """Filter queryset for a given search term.

    Searches the precomputed search document (`Surface.search_vector`, backed
    by a GIN index), which contains the dataset's name, description, creator,
    tags and the same fields of its measurements. The search term is
    interpreted in 'websearch' manner: phrases are combined by "AND",
    expressions and quotes are allowed. See
    https://docs.djangoproject.com/en/stable/ref/contrib/postgres/search/
    for details.

    Parameters
    ----------
    request
        Request instance; the search term is taken from the `search` query
        parameter.
    qs : QuerySet
        QuerySet which should be additionally filtered by a search term.

    Returns
    -------
    Filtered query set.
    """
    search_term = request.GET.get("search", default="")
    if not search_term:
        return qs
    return qs.filter(
        search_vector=SearchQuery(
            search_term, config="english", search_type="websearch"
        )
    )


# v1 filter
def filter_by_sharing_status(request, qs):
    sharing_status = request.GET.get("sharing_status", default="all")
    if sharing_status not in SHARING_STATUS_FILTER_CHOICES:
        raise ParseError(f"Cannot filter for sharing status '{sharing_status}'.")
    if sharing_status == "own":
        qs = qs.filter(created_by=request.user)
        if hasattr(Surface, "publication"):
            qs = qs.exclude(
                publication__isnull=False
            )  # exclude published and own surfaces
    elif sharing_status == "others":
        qs = qs.exclude(created_by=request.user)
        if hasattr(Surface, "publication"):
            qs = qs.exclude(
                publication__isnull=False
            )  # exclude published and own surfaces
    elif sharing_status == "published":
        if hasattr(Surface, "publication"):
            qs = qs.filter(publication__isnull=False)
        else:
            qs = Surface.objects.none()
    elif sharing_status == "all":
        pass
    else:
        raise PermissionDenied(f"Cannot filter for sharing status '{sharing_status}'.")
    return qs


# v1 filter
def filter_by_author(request, qs):
    """Filter queryset by the name of the creating user.

    Each `author` query parameter is matched case-insensitively as a substring
    of the creator's name; multiple parameters must all match (AND).
    """
    for author in request.query_params.getlist("author"):
        if author:
            qs = qs.filter(created_by__name__icontains=author)
    return qs


# v1 filter
def filter_by_name(request, qs):
    """Filter queryset by (part of) the digital surface twin's name.

    Each `name` query parameter is matched case-insensitively as a substring;
    multiple parameters must all match (AND).
    """
    for name in request.query_params.getlist("name"):
        if name:
            qs = qs.filter(name__icontains=name)
    return qs


# v1 filter
def filter_by_tag(request, qs):
    tags = request.query_params.getlist("tag")
    tag_startswith = request.query_params.get("tag_startswith", None)
    if len(tags) > 0:
        if tag_startswith is not None:
            raise ParseError(
                "Please specify either `tag` or `tag_startswith`, not both."
            )
        # Multiple tags must all match (AND); an empty value selects untagged
        # datasets (legacy behavior of the single `tag` parameter).
        for tag in tags:
            if tag:
                qs = qs.filter(tags__name=tag)
            else:
                qs = qs.filter(tags=None)
    elif tag_startswith is not None:
        if tag_startswith:
            qs = (
                qs.filter(
                    Q(tags__name=tag_startswith)
                    | Q(tags__name__startswith=tag_startswith.rstrip("/") + "/")
                )
                .order_by("id")
                .distinct("id")
            )
        else:
            raise ParseError("`tag_startswith` cannot be empty.")
    return qs


# v1 filter
def filter_to_latest_version(request, qs):
    """Collapse the published versions of a dataset to its latest version.

    Publishing creates a new `Surface`, so every version of a dataset is a row of
    its own. Ordered by date or by name they end up scattered through the list:
    searching for a dataset returns one hit near the top and another far down,
    with the same name and nothing but a small note to tell them apart, and most
    people click the first one they find (see ContactEngineering/ce-ui#38). Only
    the latest version is listed; the others are reachable from its detail page.

    Left alone are unpublished datasets — a work in progress is nobody's older
    version — and publications that do not record an original, which cannot be
    grouped. Every version of a dataset is public, so this never hides a version
    the user would otherwise have been able to see.
    """
    if not hasattr(Surface, "publication"):
        # The publication plugin is not installed, so there are no versions.
        return qs
    latest_of_group = (
        Surface.objects.filter(
            publication__original_surface=OuterRef("publication__original_surface")
        )
        .order_by("-publication__version")
        .values("pk")[:1]
    )
    return qs.annotate(_latest_of_group=Subquery(latest_of_group)).filter(
        Q(publication__isnull=True)
        | Q(publication__original_surface__isnull=True)
        | Q(pk=F("_latest_of_group"))
    )


# v1 filter
def order_results(request, qs):
    order_by = request.GET.get("order_by", default="date")
    if order_by not in ORDER_BY_FILTER_CHOICES:
        raise ParseError(f"Cannot order by '{order_by}'.")
    qs = Surface.objects.filter(pk__in=Subquery(qs.values("pk"))).order_by(
        ORDER_BY_FILTER_CHOICES[order_by]
    )
    return qs


# v1 filter
def filter_surfaces(request, qs):
    """Return queryset with surfaces matching all filter criteria.

    Surfaces should be
    - readable by the current user
    - filtered by sharing status
    - filtered by search expression, if given
    - collapsed to the latest version of each published dataset

    Parameters
    ----------
    request
        Request instance

    Returns
    -------
        Filtered queryset of surfaces
    """
    filters = [
        filter_by_tag,
        filter_by_author,
        filter_by_name,
        filter_by_sharing_status,
        filter_by_search_term,
        filter_to_latest_version,
        order_results,
    ]

    for filter in filters:
        qs = filter(request, qs)

    return qs
