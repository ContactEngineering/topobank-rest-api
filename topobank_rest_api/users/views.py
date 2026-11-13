from allauth.utils import generate_unique_username
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from topobank.authorization import get_anonymous_user, get_permission_model

from topobank_rest_api.users.permissions import UserPermission

from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    pagination_class = LimitOffsetPagination
    permission_classes = [UserPermission]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return get_user_model().objects.none()

        name = self.request.query_params.get("name")

        # We don't want the anonymous user
        qs = get_user_model().objects.exclude(id=get_anonymous_user().id)

        # Staff can see and search everyone
        if self.request.user.is_staff:
            if name is not None:
                qs = qs.filter(_substring_match(name))
            return qs

        # Other users see the users they work with (see `_visible_to`). A search
        # matches those by substring, and additionally finds any other user by
        # exact full name or ORCID iD, so that a dataset can be shared with
        # someone new without making every account enumerable.
        visible = _visible_to(self.request.user)
        if name is None:
            return qs.filter(visible)
        return qs.filter((visible & _substring_match(name)) | _exact_match(name))

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        data: dict = request.data
        if data.get("username"):
            username = data.pop("username")
        else:
            username = generate_unique_username([data.get("email"), data.get("name")])
        serializer = self.get_serializer(data={**data, "username": username})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)

    @transaction.atomic
    def perform_update(self, serializer):
        return super().perform_update(serializer)

    @transaction.atomic
    def perform_create(self, serializer):
        return super().perform_create(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        return super().perform_destroy(instance)


def _visible_to(user) -> Q:
    """
    Users that `user` may see: themselves, users that share a group with them,
    and users that share access to a dataset (a permission set) with them.

    The default 'all' group, which every user is a member of, is excluded from
    the shared-group check, otherwise every user would see every other user.
    The checks are subqueries on ids, so they cannot duplicate rows.
    """
    User = get_user_model()
    PermissionSet = get_permission_model()
    UserPermission = PermissionSet._meta.get_field("user_permissions").related_model

    shared_group = User.objects.filter(
        groups__in=user.groups.exclude(name="all")
    ).values("id")
    shared_dataset = UserPermission.objects.filter(
        parent__in=PermissionSet.objects.filter(user_permissions__user=user)
    ).values("user_id")
    return Q(id=user.id) | Q(id__in=shared_group) | Q(id__in=shared_dataset)


def _substring_match(term: str) -> Q:
    return (
        Q(name__icontains=term)
        | Q(username__icontains=term)
        | Q(email__icontains=term)
    )


ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")


def _exact_match(term: str) -> Q:
    """Match a user by exact (case-insensitive) full name or ORCID iD."""
    term = term.strip()
    if not term:
        return Q(pk__in=[])
    q = Q(name__iexact=term)

    orcid = term
    for prefix in ORCID_URL_PREFIXES:
        if orcid.lower().startswith(prefix):
            orcid = orcid[len(prefix):]
            break
    orcid = orcid.upper()  # The checksum digit may be an 'X'

    # The ORCID iD is the uid of the user's ORCID social account
    try:
        from allauth.socialaccount.models import SocialAccount
    except ImportError:
        pass
    else:
        q |= Q(
            id__in=SocialAccount.objects.filter(provider="orcid", uid=orcid).values(
                "user_id"
            )
        )

    # Some user models store the ORCID iD directly
    try:
        get_user_model()._meta.get_field("orcid_id")
    except FieldDoesNotExist:
        pass
    else:
        q |= Q(orcid_id=orcid)

    return q
