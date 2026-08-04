import itertools
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, F, Q, When
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from notifications.signals import notify
from rest_framework import mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import (
    IsAdminUser,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from topobank.files.models import Manifest
from topobank.manager.models import Surface, Tag, Topography
from topobank.manager.tasks import import_container_from_url
from topobank.supplib.versions import get_versions
from topobank.taskapp.utils import run_task

from topobank_rest_api.authorization.permissions import ObjectPermission
from topobank_rest_api.manager.filters import filter_surfaces
from topobank_rest_api.manager.v1.permissions import TagPermission
from topobank_rest_api.supplib.mixins import UserUpdateMixin
from topobank_rest_api.utils import get_api_url

from ..v1.serializers import SurfaceSerializer, TagSerializer, TopographySerializer

_log = logging.getLogger(__name__)


class TagViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Tag.objects.all()
    lookup_field = "name"
    lookup_value_regex = "[^.]+"  # We need to match paths that include slashes
    serializer_class = TagSerializer
    permission_classes = [TagPermission]
    pagination_class = LimitOffsetPagination

    def list(self, request, *args, **kwargs):
        search = request.query_params.get("search")
        if search is not None:
            # Autocomplete mode: full names of tags (on datasets visible to the
            # current user) that contain the search string
            try:
                limit = min(int(request.query_params.get("limit", 10)), 25)
            except ValueError:
                raise ParseError("`limit` must be an integer.")
            tag_names = sorted(
                set(
                    Surface.objects.for_user(request.user)
                    .filter(tags__name__icontains=search)
                    .values_list("tags__name", flat=True)
                )
            )[:limit]
            return Response(tag_names)

        all_tags = set(
            "" if tag_name is None else tag_name
            for tag_name in itertools.chain.from_iterable(
                Surface.objects.for_user(request.user).values_list("tags__name")
            )
        )

        toplevel_tags = set(f"{tag}/".split("/", maxsplit=1)[0] for tag in all_tags)
        return Response(sorted(toplevel_tags))


class SurfaceViewSet(UserUpdateMixin, viewsets.ModelViewSet):
    serializer_class = SurfaceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, ObjectPermission]
    pagination_class = LimitOffsetPagination

    def _notify(self, instance, verb):
        user = self.request.user
        other_users = instance.permissions.user_permissions.filter(~Q(user__id=user.id))
        for u in other_users:
            notify.send(
                sender=user,
                verb=verb,
                recipient=u.user,
                description=f"User '{user.name}' {verb}d digital surface twin '{instance.name}'.",
            )

    def get_queryset(self):
        qs = Surface.objects.for_user(self.request.user)
        return filter_surfaces(self.request, qs)

    @transaction.atomic
    def perform_create(self, serializer):
        # Set created_by to current user when creating a new surface
        instance = super().perform_create(serializer)

        # We now have an id, set name if missing
        if "name" not in serializer.data or serializer.data["name"] == "":
            instance.name = f"Digital surface twin #{instance.id}"
            instance.save()

    @transaction.atomic
    def perform_update(self, serializer):
        super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        self._notify(instance, "delete")
        instance.delete()


class TopographyViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TopographySerializer
    permission_classes = [IsAuthenticatedOrReadOnly, ObjectPermission]
    pagination_class = LimitOffsetPagination

    def _notify(self, instance, verb):
        user = self.request.user
        other_users = instance.permissions.user_permissions.filter(~Q(user__id=user.id))
        for u in other_users:
            notify.send(
                sender=user,
                verb=verb,
                recipient=u.user,
                description=f"User '{user.name}' {verb}d digital surface twin "
                f"'{instance.name}'.",
            )

    def get_queryset(self):
        # Return empty queryset for schema generation
        if getattr(self, "swagger_fake_view", False):
            return Topography.objects.none()

        # Everything the serializer touches per object, so that listing the
        # measurements of a dataset does not degenerate into ~10 queries per
        # measurement
        qs = Topography.objects.for_user(self.request.user).select_related(
            "surface",
            "permissions",
            "created_by",
            "datafile",
            "squeezed_datafile",
            "thumbnail",
            "deepzoom",
            "attachments",
        ).prefetch_related(
            "tags",
            "permissions__user_permissions__user",
        )
        surfaces = self.request.query_params.getlist("surface")
        tags = self.request.query_params.getlist("tag")
        tags_startswith = self.request.query_params.getlist("tag_startswith")
        subject_q = Q()
        if len(surfaces) > 0:
            for surface in surfaces:
                try:
                    surface_id = int(surface)
                except ValueError:
                    raise ParseError(
                        f"Invalid surface ID '{surface}'. Please provide an integer."
                    )
                subject_q |= Q(surface__id=surface_id)
        elif len(tags) > 0:
            for tag in tags:
                if tag:
                    subject_q |= Q(surface__tags__name=tag)
                else:
                    subject_q |= Q(surface__tags=None)
        elif len(tags_startswith) > 0:
            for tag_startswith in tags_startswith:
                subject_q |= (Q(surface__tags__name=tag_startswith)
                              | Q(surface__tags__name__startswith=tag_startswith.rstrip("/") + "/"))

        if len(subject_q) == 0:
            if self.action == "list":
                raise ParseError(
                    "Please limit your request with query parameters. Possible parameters "
                    "are: `surface`, `tag`, `tag_startswith`"
                )
            return qs
        else:
            return qs.filter(subject_q).distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        # Check whether the user is allowed to write to the parent surface; if not, we
        # cannot add a topography
        parent = serializer.validated_data["surface"]
        if not parent.has_permission(self.request.user, "edit"):
            self.permission_denied(
                self.request,
                message=f"User {self.request.user} has no permission to edit dataset "
                f"{get_api_url(parent)}.",
            )

        # Set created_by to current user when creating a new topography
        # Don't pass permissions - let the save() method inherit from parent surface
        instance = serializer.save(created_by=self.request.user)

        # We need to make sure the datafile manifest is created and associated with the
        # instance *before* the serializer is finished, so it's included in the response.
        # Topography.save() already does this, but we need to ensure the serializer
        # knows about it.
        if instance.datafile is not None:
            # Re-read from database to be absolutely sure all relationships are correct
            instance.refresh_from_db()
        else:
            # Fallback in case save() didn't create it for some reason (e.g. update_fields)
            filename = serializer.validated_data["name"]
            instance.datafile = Manifest.objects.create(
                permissions=instance.permissions,
                filename=filename,
                kind="raw",
                created_by=instance.created_by,
                folder=None,
            )
            instance.save()

    @transaction.atomic
    def perform_update(self, serializer):
        super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        self._notify(instance, "delete")
        instance.delete()

    # From mixins.RetrieveModelMixin
    @transaction.non_atomic_requests
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.task_state == Topography.NOTRUN:
            # The cache has never been created
            _log.info(
                f"Creating cached properties of new {instance.get_subject_type()} {instance.id}..."
            )
            with transaction.atomic():
                run_task(instance)  # Sets task state to 'pe' and triggers task on commit
                instance.save()  # Save the pending state
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@transaction.non_atomic_requests
def download_surface(request, surface_ids):
    from ..v2 import views as v2

    try:
        parsed_ids = [int(sid) for sid in surface_ids.split(",")]
    except ValueError:
        return HttpResponseBadRequest("Invalid surface ID(s).")

    surfaces = [get_object_or_404(Surface, id=sid) for sid in parsed_ids]

    for surface in surfaces:
        if not surface.has_permission(request.user, "view"):
            raise PermissionDenied()

    if len(surfaces) == 1 and surfaces[0].is_published:
        pub = surfaces[0].publication
        try:
            return redirect(
                reverse("publication:download-container", kwargs={"short_url": pub.short_url})
            )
        except Exception:
            if pub.container:
                return redirect(pub.container.url)

    return v2.download_surface(request, surface_ids)


@extend_schema(
    description="Force inspection of a topography",
    parameters=[
        OpenApiParameter(
            name="pk",
            type=int,
            location=OpenApiParameter.PATH,
            description="Topography ID",
        ),
    ],
    request=None,
    responses=OpenApiTypes.OBJECT,
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.non_atomic_requests
def force_inspect(request, pk=None):
    user = request.user
    instance = get_object_or_404(Topography, pk=pk)

    # Check that user has the right to modify this measurement
    if not user.is_staff and not instance.has_permission(user, "edit"):
        return HttpResponseForbidden()

    _log.debug(f"Forcing renewal of cache for {instance}...")

    # Force renewal of cache within transaction. `force=True` re-dispatches even
    # when a task is already in-flight; without it `run_task` skips the dispatch
    # (topobank SD-668), which would defeat the purpose of a force-inspect.
    with transaction.atomic():
        run_task(instance, force=True)
        instance.save()

    # Return current state of object
    data = TopographySerializer(instance, context={"request": request}).data
    return Response(data)


@extend_schema(
    description="Set permissions for a surface",
    parameters=[
        OpenApiParameter(
            name="pk",
            type=int,
            location=OpenApiParameter.PATH,
            description="Surface ID",
        ),
    ],
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.NONE, 405: OpenApiTypes.OBJECT},
)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def set_surface_permissions(request, pk=None):
    logged_in_user = request.user
    obj = get_object_or_404(Surface, pk=pk)

    # Check that user has the right to modify permissions
    if not obj.has_permission(logged_in_user, "full"):
        return HttpResponseForbidden()

    # Check that the request does not ask to revoke permissions from the current user
    for permission in request.data:
        if "user" in permission:
            other_user = get_user_model().resolve(permission["user"])
            if other_user == logged_in_user:
                if permission["permission"] != "full":
                    return Response(
                        {
                            "message": "Permissions cannot be revoked from logged in user"
                        },
                        status=405,
                    )  # Not allowed

    # Everything looks okay, update permissions
    for permission in request.data:
        perm = permission.get("permission", None)
        if perm is None:
            return HttpResponseBadRequest(reason="Permission was not provided")
        if "user" in permission:
            other_user = get_user_model().resolve(permission["user"])
            if other_user != logged_in_user:
                if perm == "no-access":
                    obj.revoke_permission(other_user)
                else:
                    obj.grant_permission(other_user, perm)
        else:
            return HttpResponseBadRequest(
                reason="Can only set permissions for users."
            )

    # Permissions were updated successfully, return 204 No Content
    return Response({}, status=204)


@extend_schema(request=None, responses=None)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def set_tag_permissions(request, name=None):
    logged_in_user = request.user
    obj = get_object_or_404(Tag, name=name)

    # Check that the request does not ask to revoke permissions from the current user
    for permission in request.data:
        user = get_user_model().resolve(permission["user"])
        if user == logged_in_user:
            if permission["permission"] != "full":
                return Response(
                    {"message": "Permissions cannot be revoked from logged in user"},
                    status=405,
                )

    # Keep track of updated and insufficient permissions
    updated = []
    rejected = []

    # Loop over all surfaces
    obj.authorize_user(logged_in_user)
    for surface in obj.get_descendant_surfaces():
        # Check that user has the right to modify permissions
        if surface.has_permission(logged_in_user, "full"):
            updated += [get_api_url(surface, request)]
            # Loop over permissions
            for permission in request.data:
                perm = permission.get("permission", None)
                if perm is None:
                    return HttpResponseBadRequest(reason="Permission was not provided")

                if "user" in permission:
                    other_user = get_user_model().resolve(permission["user"])
                    if other_user != logged_in_user:
                        perm = permission["permission"]
                        if perm == "no-access":
                            surface.revoke_permission(other_user)
                        else:
                            surface.grant_permission(other_user, perm)
                else:
                    return HttpResponseBadRequest(
                        reason="Can only set permissions for users."
                    )
        else:
            rejected += [get_api_url(surface, request)]

    # Permissions were updated successfully, return 204 No Content
    return Response({"updated": updated, "rejected": rejected})


@extend_schema(request=None, responses=None)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@transaction.non_atomic_requests
def tag_numerical_properties(request, name=None):
    obj = get_object_or_404(Tag, name=name)
    obj.authorize_user(request.user, "view")
    prop_values, prop_infos = obj.get_properties(kind="numerical")
    return Response(dict(names=list(prop_values.keys())))


@extend_schema(request=None, responses=None)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@transaction.non_atomic_requests
def tag_categorical_properties(request, name=None):
    obj = get_object_or_404(Tag, name=name)
    obj.authorize_user(request.user, "view")
    prop_values, prop_infos = obj.get_properties(kind="categorical")
    return Response(dict(names=list(prop_values.keys())))


@extend_schema(request=None, responses=None)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.non_atomic_requests
def import_surface(request):
    url = request.data.get("url")

    if not url:
        return HttpResponseBadRequest()

    user = request.user
    # Need to pass id here because user is not JSON serializable
    with transaction.atomic():
        transaction.on_commit(lambda: import_container_from_url.delay(user.id, url))

    return Response({})


@extend_schema(
    description="Get version information for all installed packages",
    request=None,
    responses=OpenApiTypes.OBJECT,
)
@api_view(["GET"])
@transaction.non_atomic_requests
def versions(request):
    return Response(get_versions())


@extend_schema(request=None, responses=None)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def statistics(request):
    # Global statistics
    stats = {
        "nb_users": get_user_model().objects.count()
        - 1,  # -1 because we don't count the anonymous user
        "nb_surfaces": Surface.objects.count(),
        "nb_topographies": Topography.objects.count(),
    }
    # User-specific statistics
    stats = {
        **stats,
        "nb_surfaces_of_user": Surface.objects.for_user(request.user).count(),
        "nb_topographies_of_user": Topography.objects.for_user(
            request.user
        ).count(),
        "nb_surfaces_shared_with_user": Surface.objects.for_user(request.user)
        .exclude(created_by=request.user)
        .count(),
    }
    return Response(stats)


@extend_schema(request=None, responses=None)
@api_view(["GET"])
@permission_classes([IsAdminUser])
@transaction.non_atomic_requests
def memory_usage(request):
    r = Topography.objects.values(
        "resolution_x", "resolution_y", "task_memory"
    ).annotate(
        task_duration=F("task_end_time") - F("task_start_time"),
        nb_data_pts=F("resolution_x")
        * Case(When(resolution_y__isnull=False, then=F("resolution_y")), default=1),
    )
    return Response(list(r))
