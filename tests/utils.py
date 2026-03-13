import logging
import requests

from django.conf import settings
from rest_framework.reverse import reverse

_log = logging.getLogger(__name__)


def upload_file(api_client, upload_instructions, fn):
    url = upload_instructions["url"]
    method = upload_instructions["method"]
    _log.debug(f"Upload to url: {url}, method: {method}")
    with open(fn, mode="rb") as fp:
        if method == "POST":
            if settings.USE_S3_STORAGE:
                # We need to use `requests` as the upload is directly to S3, not to the
                # Django app
                response = requests.post(
                    url,
                    data={**upload_instructions["fields"]},
                    files={"file": fp},
                )
            else:
                response = api_client.post(
                    url,
                    {**upload_instructions["fields"], "file": fp},
                    format="multipart",
                )
            assert response.status_code == 204, response.content  # Created
        elif method == "PUT":
            if settings.USE_S3_STORAGE:
                # We need to use `requests` as the upload is directly to S3, not to the
                # Django app
                response = requests.put(
                    url, data=fp, headers={"Content-Type": "binary/octet-stream"}
                )
            else:
                raise RuntimeError("PUT uploads not supported without S3")
            assert response.status_code == 200, response.content  # OK
        else:
            raise RuntimeError(f"Unknown upload method {method}")


def upload_topography_file(
    fn,
    surface_id,
    api_client,
    django_capture_on_commit_callbacks,
    final_task_state="su",
    **kwargs,
):
    # create new topography (and request file upload location)
    _log.debug(f"Uploading file '{fn}'...")
    name = fn.split("/")[-1]
    response = api_client.post(
        reverse("manager:topography-api-list"),
        {
            "surface": reverse(
                "manager:surface-api-detail", kwargs=dict(pk=surface_id)
            ),
            "name": name,
            **kwargs,
        },
    )
    assert response.status_code == 201, response.content  # Created
    topography_id = response.data["id"]

    # The POST request above informs us how to upload the file
    upload_instructions = response.data["datafile"]["upload_instructions"]
    upload_file(api_client, upload_instructions, fn)

    # We need to execute on commit actions, because this is where the refresh_cache task
    # is triggered
    with django_capture_on_commit_callbacks(execute=True):
        # Get info on file (this will trigger the inspection). In the production
        # instance, the first GET triggers a background (Celery) task and always returns
        # a 'pe'nding state. In this testing environment, this is run immediately after
        # the `save` but not yet reflected in the returned dictionary.
        response = api_client.get(
            reverse("manager:topography-api-detail", kwargs=dict(pk=topography_id))
        )
        assert response.status_code == 200, response.content
        assert response.data["task_state"] == "pe", response.data["task_state"]
        # We need to close the commit capture here because the file inspection runs on
        # commit

    with django_capture_on_commit_callbacks(execute=True):
        # Get info on file again, this should not report a successful file inspection.
        response = api_client.get(
            reverse("manager:topography-api-detail", kwargs=dict(pk=topography_id))
        )
        assert response.status_code == 200, response.content
        assert response.data["task_state"] == final_task_state, response.data[
            "task_state"
        ]

    return response


def search_surfaces(api_client, expr):
    response = api_client.get(reverse("manager:surface-api-list") + f"?search={expr}")
    assert response.status_code == 200
    return response.data
