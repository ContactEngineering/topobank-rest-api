"""
Query construction for the staff dashboards.

The dashboards page through potentially every user and every analysis in the
instance, so all derived values have to come out of the database as
annotations. In particular the user list must *not* touch
``User.orcid_id``: on the production user model that property runs a
``SocialAccount`` lookup per user, which would turn a 25-row page into 25
extra queries.
"""

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db.models import (
    Case,
    CharField,
    Count,
    DateTimeField,
    F,
    FilteredRelation,
    IntegerField,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Coalesce
from topobank.manager.models import Surface, Topography
from topobank.taskapp.models import TaskStateModel

#
# Terms-of-use acceptance states
#
TERMS_ACCEPTED = "accepted"
TERMS_PARTIAL = "partial"
TERMS_NOT_ACCEPTED = "not_accepted"
TERMS_EXEMPT = "exempt"
TERMS_NOT_REQUIRED = "not_required"
TERMS_UNAVAILABLE = "unavailable"


def _count_per_user(queryset: QuerySet, user_field: str = "created_by"):
    """
    Count rows of ``queryset`` per user as a correlated subquery.

    Subqueries rather than ``Count(..., distinct=True)`` annotations: two
    multi-valued joins on the same query would build a cross product, which
    ``distinct=True`` corrects but does not make cheap.

    The ``.order_by()`` is load-bearing. Both ``Surface`` and ``Topography``
    declare a ``Meta.ordering``, and Django would otherwise carry those
    columns into the ``GROUP BY``, producing one row per object instead of
    one row per user.
    """
    return Coalesce(
        Subquery(
            queryset.filter(**{user_field: OuterRef("pk")})
            .order_by()
            .values(user_field)
            .annotate(n=Count("pk"))
            .values("n")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def annotate_orcid_from_socialaccount(queryset: QuerySet) -> QuerySet:
    """
    Annotate ``orcid`` by reading the iD out of the allauth
    ``SocialAccount.extra_data`` JSON blob.

    This mirrors what the production ``User.orcid_id`` property does per
    instance, but as a single joined expression, which is what keeps the
    dashboard's query count independent of the page size and makes the column
    searchable and sortable in the database.
    """
    return queryset.annotate(
        # FilteredRelation keeps the join to the single ORCID row, so user
        # rows are not multiplied by unrelated social accounts.
        _orcid_account=FilteredRelation(
            "socialaccount", condition=Q(socialaccount__provider="orcid")
        ),
    ).annotate(
        orcid=KeyTextTransform(
            "path", KeyTransform("orcid-identifier", "_orcid_account__extra_data")
        )
    )


def annotate_orcid(queryset: QuerySet) -> QuerySet:
    """
    Add an ``orcid`` annotation to a user queryset.

    The production user model (``topobank_orcid``) exposes ``orcid_id`` only
    as a Python property, so the iD has to be dug out of the social account.
    Test and mock user models carry ``orcid_id`` as a plain field, which is
    used directly.
    """
    concrete = {
        field.name
        for field in queryset.model._meta.get_fields()
        if getattr(field, "concrete", False)
    }
    if "orcid_id" in concrete:
        return queryset.annotate(orcid=F("orcid_id"))

    if apps.is_installed("allauth.socialaccount"):
        return annotate_orcid_from_socialaccount(queryset)

    return queryset.annotate(orcid=Value(None, output_field=CharField()))


def active_terms_ids():
    """
    Return the IDs of the currently active terms, or ``None`` if the
    terms-and-conditions app is not installed in this deployment.
    """
    if not apps.is_installed("termsandconditions"):
        return None
    from termsandconditions.models import TermsAndConditions

    return list(TermsAndConditions.get_active_terms_ids())


def annotate_terms(queryset: QuerySet, terms_ids) -> QuerySet:
    """
    Annotate how many of the active terms each user has accepted, and when
    they last accepted one.
    """
    if not terms_ids:
        return queryset.annotate(
            num_accepted_terms=Value(0, output_field=IntegerField()),
            terms_accepted_on=Value(None, output_field=DateTimeField()),
        )

    user_terms = apps.get_model("termsandconditions", "UserTermsAndConditions")
    accepted = user_terms.objects.filter(
        user=OuterRef("pk"), terms_id__in=terms_ids
    ).order_by()

    return queryset.annotate(
        num_accepted_terms=Coalesce(
            Subquery(
                accepted.values("user").annotate(n=Count("pk")).values("n")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        terms_accepted_on=Subquery(
            accepted.values("user").annotate(m=Max("date_accepted")).values("m")[:1],
            output_field=DateTimeField(),
        ),
    )


def terms_exempt_user_ids(user_ids) -> set:
    """
    Return which of ``user_ids`` are exempt from accepting the terms.

    Mirrors the logic in ``TermsAndConditions.get_active_terms_not_agreed_to``:
    holding ``TERMS_EXCLUDE_USERS_WITH_PERM`` exempts a user, but superusers
    are deliberately *not* exempted by that route (``has_perm`` returns True
    for them regardless), only by ``TERMS_EXCLUDE_SUPERUSERS``.

    Resolved in bulk for a whole page rather than by calling ``has_perm()``
    per row, which would issue two queries per user.
    """
    from django.contrib.auth import get_user_model

    user_ids = list(user_ids)
    if not user_ids:
        return set()

    users = get_user_model().objects.filter(pk__in=user_ids)
    exempt = set()

    if getattr(settings, "TERMS_EXCLUDE_SUPERUSERS", False):
        exempt |= set(users.filter(is_superuser=True).values_list("pk", flat=True))

    perm_label = getattr(settings, "TERMS_EXCLUDE_USERS_WITH_PERM", None)
    if perm_label and "." in perm_label:
        app_label, codename = perm_label.split(".", 1)
        permissions = Permission.objects.filter(
            content_type__app_label=app_label, codename=codename
        )
        exempt |= set(
            users.filter(
                Q(user_permissions__in=permissions)
                | Q(groups__permissions__in=permissions)
            )
            .exclude(is_superuser=True)
            .values_list("pk", flat=True)
        )

    return exempt


def user_dashboard_queryset(terms_ids) -> QuerySet:
    """
    Build the annotated user queryset backing the user dashboard.

    Counts are of objects the user *created*, excluding soft-deleted ones.
    """
    from django.contrib.auth import get_user_model
    from topobank.authorization import get_anonymous_user

    queryset = get_user_model().objects.all()

    anonymous = get_anonymous_user()
    if anonymous is not None:
        queryset = queryset.exclude(pk=anonymous.pk)

    queryset = annotate_orcid(queryset)
    queryset = annotate_terms(queryset, terms_ids)

    return queryset.annotate(
        num_surfaces=_count_per_user(
            Surface.all_objects.filter(deletion_time__isnull=True)
        ),
        num_topographies=_count_per_user(
            Topography.all_objects.filter(deletion_time__isnull=True)
        ),
    )


#
# Task dashboard
#

#: Sort key that puts the tasks currently loading the system at the top.
TASK_STATE_RANK = Case(
    When(task_state=TaskStateModel.STARTED, then=Value(0)),
    When(
        task_state__in=[
            TaskStateModel.PENDING,
            TaskStateModel.PENDING_DEPENDENCIES,
        ],
        then=Value(1),
    ),
    When(task_state=TaskStateModel.RETRY, then=Value(2)),
    When(task_state=TaskStateModel.FAILURE, then=Value(3)),
    When(task_state=TaskStateModel.SUCCESS, then=Value(4)),
    default=Value(5),
    output_field=IntegerField(),
)


def task_dashboard_queryset() -> QuerySet:
    """
    Build the annotated ``WorkflowResult`` queryset backing the task
    dashboard.

    ``activity_time`` collapses the three timestamps into one sortable
    column: a queued task has no start time but does have a submission time,
    and a never-run task has neither. ``created_at`` is ``auto_now_add`` and
    therefore never null, so the coalesced value is always defined.
    """
    from topobank.analysis.models import WorkflowResult

    return (
        WorkflowResult.objects.select_related(
            "created_by",
            "subject_topography",
            "subject_surface",
            "subject_tag",
        )
        # Surface-set analyses carry their subjects in an M2M; prefetching
        # keeps that at one extra query for the whole page.
        .prefetch_related("surfaces")
        .annotate(
            state_rank=TASK_STATE_RANK,
            activity_time=Coalesce(
                "task_start_time", "task_submission_time", "created_at"
            ),
        )
    )
