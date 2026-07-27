"""
Tests for the asynchronous download of workflow result files as a ZIP archive.
"""

import io
import zipfile

import pytest
from django.urls import resolve, reverse
from rest_framework import status
from topobank.analysis.zip_model import ResultZipContainer
from topobank.testing.factories import (
    PermissionSetFactory,
    Topography1DFactory,
    TopographyAnalysisFactory,
)

#
# Routes
#


def test_download_results_route():
    url = reverse("analysis:download-results-v2", kwargs={"result_ids": "1,2,3"})
    assert url == "/analysis/v2/download-results/1,2,3/"
    assert resolve(url).view_name == "analysis:download-results-v2"


def test_zip_container_route():
    url = reverse("analysis:result-zip-container-v2-detail", kwargs={"pk": 1})
    assert url == "/analysis/v2/zip-container/1/"
    assert resolve(url).view_name == "analysis:result-zip-container-v2-detail"


#
# Requesting an archive
#


@pytest.mark.django_db
def test_download_results_creates_container(
    api_client, user_alice, handle_usage_statistics
):
    topography = Topography1DFactory(created_by=user_alice)
    analysis = TopographyAnalysisFactory(
        subject_topography=topography, created_by=user_alice
    )
    analysis.grant_permission(user_alice, "view")

    api_client.force_login(user_alice)
    response = api_client.post(
        reverse("analysis:download-results-v2", kwargs={"result_ids": analysis.id})
    )

    assert response.status_code == status.HTTP_200_OK
    assert "task_state" in response.data
    assert ResultZipContainer.objects.filter(id=response.data["id"]).exists()


@pytest.mark.django_db
def test_download_results_end_to_end(
    api_client, user_alice, settings, handle_usage_statistics,
    django_capture_on_commit_callbacks
):
    """The full flow: request an archive, let the task run, download the file."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    topography = Topography1DFactory(created_by=user_alice)
    analysis = TopographyAnalysisFactory(
        subject_topography=topography, created_by=user_alice
    )
    analysis.grant_permission(user_alice, "view")

    api_client.force_login(user_alice)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            reverse("analysis:download-results-v2", kwargs={"result_ids": analysis.id})
        )
    assert response.status_code == status.HTTP_200_OK

    # Poll the container; the task has finished by now
    response = api_client.get(response.data["url"])
    assert response.status_code == status.HTTP_200_OK
    assert response.data["task_state"] == "su"

    # The polled container has to carry the URL to download from: this is what
    # the client follows, and without it the download cannot complete.
    assert response.data["manifest"] is not None
    assert response.data["manifest"]["file"]

    container = ResultZipContainer.objects.get(id=response.data["id"])
    with zipfile.ZipFile(io.BytesIO(container.manifest.read()), mode="r") as zip_file:
        names = zip_file.namelist()
        assert "README.txt" in names
        assert f"{analysis.subject.name.lower()}/result.json" in names


@pytest.mark.django_db
def test_download_results_accepts_several_ids(
    api_client, user_alice, handle_usage_statistics
):
    first = TopographyAnalysisFactory(
        subject_topography=Topography1DFactory(created_by=user_alice),
        created_by=user_alice,
    )
    second = TopographyAnalysisFactory(
        subject_topography=Topography1DFactory(created_by=user_alice),
        created_by=user_alice,
    )
    for analysis in [first, second]:
        analysis.grant_permission(user_alice, "view")

    api_client.force_login(user_alice)
    response = api_client.post(
        reverse(
            "analysis:download-results-v2",
            kwargs={"result_ids": f"{first.id},{second.id}"},
        )
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_download_results_rejects_unknown_ids(api_client, user_alice):
    api_client.force_login(user_alice)
    response = api_client.post(
        reverse("analysis:download-results-v2", kwargs={"result_ids": "99999"})
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # No work is dispatched for a request that cannot be served
    assert not ResultZipContainer.objects.exists()


@pytest.mark.django_db
def test_download_results_rejects_inaccessible_results(
    api_client, user_alice, user_bob
):
    analysis = TopographyAnalysisFactory(
        subject_topography=Topography1DFactory(created_by=user_bob),
        created_by=user_bob,
    )

    api_client.force_login(user_alice)
    response = api_client.post(
        reverse("analysis:download-results-v2", kwargs={"result_ids": analysis.id})
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not ResultZipContainer.objects.exists()


@pytest.mark.django_db
def test_download_results_requires_login(api_client):
    response = api_client.post(
        reverse("analysis:download-results-v2", kwargs={"result_ids": "1"})
    )

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]


#
# Polling the container
#


@pytest.mark.django_db
def test_zip_container_retrieve(api_client, user_alice):
    container = ResultZipContainer.objects.create(
        permissions=PermissionSetFactory(user=user_alice, allow="view")
    )

    api_client.force_login(user_alice)
    response = api_client.get(
        reverse("analysis:result-zip-container-v2-detail", kwargs={"pk": container.id})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == container.id
    assert "task_state" in response.data
    # The client follows this once the task has succeeded
    assert "manifest" in response.data


@pytest.mark.django_db
def test_zip_container_retrieve_no_permission(api_client, user_alice, user_bob):
    container = ResultZipContainer.objects.create(
        permissions=PermissionSetFactory(user=user_bob, allow="view")
    )

    api_client.force_login(user_alice)
    response = api_client.get(
        reverse("analysis:result-zip-container-v2-detail", kwargs={"pk": container.id})
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
