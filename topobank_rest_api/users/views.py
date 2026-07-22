from allauth.utils import generate_unique_username
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from topobank.authorization import get_anonymous_user

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

        # If we are not the staff user, then only show ourselves and users we
        # share a group with. The default 'all' group (which every user is a
        # member of) is excluded from the shared-membership check, otherwise
        # every user would be able to see every other user.
        if not self.request.user.is_staff:
            user_groups = self.request.user.groups.exclude(name="all")
            qs = qs.filter(
                Q(id=self.request.user.id)
                | Q(groups__in=user_groups)
            )

        # Filter for name, username, or email
        if name is not None:
            qs = qs.filter(
                Q(name__icontains=name)
                | Q(username__icontains=name)
                | Q(email__icontains=name)
            )

        # Return query set with distinct to avoid duplicates from group joins
        return qs.distinct()

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
