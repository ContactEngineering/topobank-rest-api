"""Tests for the staff task dashboard endpoint."""

import datetime
import uuid

import pytest
from django.utils import timezone
from rest_framework.reverse import reverse
from topobank.analysis.models import WorkflowResult
from topobank.taskapp.models import TaskStateModel
from topobank.testing.factories import (
    SurfaceAnalysisFactory,
    SurfaceFactory,
    Topography1DFactory,
    TopographyAnalysisFactory,
)


def _set_state(analysis, state, started=None, ended=None, submitted=None):
    analysis.task_state = state
    analysis.task_start_time = started
    analysis.task_end_time = ended
    analysis.task_submission_time = submitted or timezone.now()
    analysis.save(
        update_fields=[
            "task_state",
            "task_start_time",
            "task_end_time",
            "task_submission_time",
        ]
    )
    return analysis


@pytest.fixture
def analyses(db, user_alice, test_workflow):
    """One analysis in each of the interesting task states."""
    now = timezone.now()
    surface = SurfaceFactory(created_by=user_alice)
    topographies = [
        Topography1DFactory(surface=surface, created_by=user_alice) for _ in range(4)
    ]

    succeeded = _set_state(
        TopographyAnalysisFactory(subject_topography=topographies[0]),
        TaskStateModel.SUCCESS,
        started=now - datetime.timedelta(minutes=30),
        ended=now - datetime.timedelta(minutes=29),
    )
    running = _set_state(
        TopographyAnalysisFactory(subject_topography=topographies[1]),
        TaskStateModel.STARTED,
        started=now - datetime.timedelta(minutes=5),
    )
    pending = _set_state(
        TopographyAnalysisFactory(subject_topography=topographies[2]),
        TaskStateModel.PENDING,
        submitted=now - datetime.timedelta(minutes=1),
    )
    failed = _set_state(
        TopographyAnalysisFactory(subject_topography=topographies[3]),
        TaskStateModel.FAILURE,
        started=now - datetime.timedelta(minutes=10),
        ended=now - datetime.timedelta(minutes=9),
    )
    failed.task_error = "Something went wrong"
    failed.save(update_fields=["task_error"])

    return {
        "succeeded": succeeded,
        "running": running,
        "pending": pending,
        "failed": failed,
        "surface": surface,
    }


@pytest.mark.django_db
def test_requires_staff(api_client, user_alice, user_staff):
    url = reverse("staff:task-list")

    assert api_client.get(url).status_code == 403

    api_client.force_authenticate(user_alice)
    assert api_client.get(url).status_code == 403

    api_client.force_authenticate(user_staff)
    assert api_client.get(url).status_code == 200


@pytest.mark.django_db
def test_summary_requires_staff(api_client, user_alice, user_staff):
    url = reverse("staff:task-summary")

    api_client.force_authenticate(user_alice)
    assert api_client.get(url).status_code == 403

    api_client.force_authenticate(user_staff)
    assert api_client.get(url).status_code == 200


@pytest.mark.django_db
def test_running_tasks_come_first(api_client, user_staff, analyses):
    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-list"))
    assert response.status_code == 200

    states = [row["task_state"] for row in response.data["results"]]
    # Running, then queued, then everything terminal.
    assert states[0] == TaskStateModel.STARTED
    assert states[1] == TaskStateModel.PENDING
    assert set(states[2:]) == {TaskStateModel.SUCCESS, TaskStateModel.FAILURE}

    assert response.data["results"][0]["is_running"] is True
    assert response.data["results"][1]["is_running"] is False


@pytest.mark.django_db
def test_ignores_object_permissions(api_client, user_staff, analyses):
    """
    Staff must see every task, including analyses they have no permission on.
    """
    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-list"))
    assert response.data["count"] == WorkflowResult.objects.count() == 4


@pytest.mark.django_db
def test_row_contents(api_client, user_staff, user_alice, analyses):
    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-list"))
    rows = {row["id"]: row for row in response.data["results"]}

    running = rows[analyses["running"].id]
    assert running["workflow_name"] == "topobank.testing.test"
    assert running["task_state_display"] == "started"
    assert running["created_by"]["username"] == user_alice.username
    assert running["subject"]["type"] == "measurement"
    assert running["subject"]["name"] == analyses["running"].subject_topography.name
    assert running["queue"] == "analysis"
    # A running task reports elapsed time rather than nothing.
    assert running["duration"] > 0

    succeeded = rows[analyses["succeeded"].id]
    assert succeeded["duration"] == pytest.approx(60, abs=5)

    pending = rows[analyses["pending"].id]
    assert pending["duration"] is None

    failed = rows[analyses["failed"].id]
    assert failed["task_error"] == "Something went wrong"


@pytest.mark.django_db
def test_surface_subject(api_client, user_staff, user_alice, test_workflow):
    surface = SurfaceFactory(created_by=user_alice)
    analysis = SurfaceAnalysisFactory(subject_surface=surface)

    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-list"))
    row = {r["id"]: r for r in response.data["results"]}[analysis.id]

    assert row["subject"]["type"] == "dataset"
    assert row["subject"]["name"] == surface.name


@pytest.mark.django_db
def test_state_filter(api_client, user_staff, analyses):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:task-list")

    response = api_client.get(url, {"state": TaskStateModel.STARTED})
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == analyses["running"].id

    # Repeated parameter is a union
    response = api_client.get(
        url, {"state": [TaskStateModel.STARTED, TaskStateModel.PENDING]}
    )
    assert response.data["count"] == 2

    # An unknown state is ignored rather than erroring
    response = api_client.get(url, {"state": "not-a-state"})
    assert response.data["count"] == 4


@pytest.mark.django_db
def test_created_by_filter(api_client, user_staff, user_alice, analyses):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:task-list")

    assert api_client.get(url, {"created_by": user_alice.id}).data["count"] == 4
    assert api_client.get(url, {"created_by": user_staff.id}).data["count"] == 0


@pytest.mark.django_db
def test_search(api_client, user_staff, user_alice, analyses):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:task-list")

    # By workflow name
    assert api_client.get(url, {"search": "topobank.testing"}).data["count"] == 4

    # By creator
    assert api_client.get(url, {"search": "Wonderland"}).data["count"] == 4

    # By error message
    response = api_client.get(url, {"search": "went wrong"})
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == analyses["failed"].id

    # By subject name
    name = analyses["running"].subject_topography.name
    response = api_client.get(url, {"search": name})
    assert analyses["running"].id in {r["id"] for r in response.data["results"]}

    assert api_client.get(url, {"search": "no-such-thing"}).data["count"] == 0


@pytest.mark.django_db
def test_search_by_task_id(api_client, user_staff, analyses):
    task_id = uuid.uuid4()
    running = analyses["running"]
    running.task_id = task_id
    running.save(update_fields=["task_id"])

    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-list"), {"search": str(task_id)})

    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == running.id


@pytest.mark.django_db
def test_ordering_and_pagination(api_client, user_staff, analyses):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:task-list")

    # Explicit ordering overrides the running-first default
    response = api_client.get(url, {"ordering": "task_start_time"})
    starts = [
        row["task_start_time"]
        for row in response.data["results"]
        if row["task_start_time"] is not None
    ]
    assert starts == sorted(starts)
    # The queued task has no start time and sorts last, not first
    assert response.data["results"][-1]["task_start_time"] is None

    response = api_client.get(url, {"limit": 2})
    assert len(response.data["results"]) == 2
    assert response.data["count"] == 4
    assert response.data["next"] is not None


@pytest.mark.django_db
def test_summary(api_client, user_staff, analyses):
    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:task-summary"))

    assert response.data["total"] == 4
    assert response.data["running"] == 1
    assert response.data["pending"] == 1
    assert response.data["by_state"][TaskStateModel.SUCCESS] == 1
    assert response.data["failed_last_24h"] == 1
    assert response.data["finished_last_24h"] == 1


@pytest.mark.django_db
def test_summary_ignores_list_filters(api_client, user_staff, analyses):
    """
    The summary is the system-load headline; narrowing the table below it must
    not change the totals above it.
    """
    api_client.force_authenticate(user_staff)
    response = api_client.get(
        reverse("staff:task-summary"), {"state": TaskStateModel.STARTED}
    )
    assert response.data["total"] == 4
