import logging

from rest_framework.reverse import reverse

_log = logging.getLogger(__name__)


def get_api_url(obj, request=None):
    """
    Return the API endpoint URL for a given topobank model instance.
    """
    model_name = obj.__class__.__name__

    if model_name == "Tag":
        return reverse("manager:tag-api-detail", kwargs=dict(name=obj.name), request=request)
    elif model_name == "Surface":
        return reverse("manager:surface-api-detail", kwargs=dict(pk=obj.pk), request=request)
    elif model_name == "Topography":
        return reverse("manager:topography-api-detail", kwargs=dict(pk=obj.pk), request=request)
    elif model_name == "Manifest":
        return reverse("files:manifest-api-detail", kwargs={"pk": obj.pk}, request=request)
    elif model_name == "Folder":
        return reverse("files:folder-api-detail", kwargs={"pk": obj.pk}, request=request)
    elif model_name == "WorkflowResult":
        return reverse("analysis:result-detail", kwargs=dict(pk=obj.id), request=request)
    elif model_name == "ZipArchive":
        return reverse("manager:zip-container-v2-detail", kwargs=dict(pk=obj.id), request=request)
    elif model_name == "Organization":
        return reverse("organizations:organization-v1-detail", kwargs={"pk": obj.pk}, request=request)
    elif model_name == "User":
        return reverse("users:user-v1-detail", kwargs={"pk": obj.pk}, request=request)

    raise NotImplementedError(f"API URL for model {model_name} is not implemented.")
