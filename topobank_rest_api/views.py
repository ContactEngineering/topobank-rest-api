from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse


@extend_schema(
    description="Get API entry points",
    request=None,
    responses={
        200: {
            "type": "object",
            "properties": {
                "analysis": {"type": "string", "format": "uri"},
                "surface": {"type": "string", "format": "uri"},
                "topography": {"type": "string", "format": "uri"},
                "admin": {
                    "type": "string",
                    "format": "uri",
                    "description": "Only present for staff users",
                },
            },
            "required": ["analysis", "surface", "topography"],
        }
    },
)
@api_view(["GET"])
@transaction.non_atomic_requests
def entry_points(request):
    e = {
        "analysis": reverse("analysis:result-list", request=request),
        "surface": reverse("manager:surface-api-list", request=request),
        "topography": reverse("manager:topography-api-list", request=request),
    }

    if request.user.is_staff:
        e["admin"] = reverse("admin:index", request=request)

    return Response(e)
