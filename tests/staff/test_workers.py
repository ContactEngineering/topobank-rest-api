"""Tests for the Celery worker status endpoint."""

import pytest
from django.core.cache import cache
from rest_framework.reverse import reverse

from topobank_rest_api.staff import celery_inspect

STATS = {
    "celery@worker-a": {
        "pid": 101,
        "uptime": 3600,
        "sw_ver": "5.4.0",
        "total": {"topobank.analysis.tasks.perform_workflow": 12},
        "pool": {
            "max-concurrency": 4,
            "min-concurrency": 4,
            "implementation": "prefork",
            "processes": [1, 2, 3, 4],
        },
    },
    "celery@worker-b": {
        "pid": 202,
        "uptime": 60,
        "sw_ver": "5.4.0",
        "total": {},
        # A solo pool reports no max-concurrency.
        "pool": {"implementation": "solo"},
    },
}

ACTIVE = {"celery@worker-a": [{"id": "1"}, {"id": "2"}], "celery@worker-b": []}
RESERVED = {"celery@worker-a": [{"id": "3"}], "celery@worker-b": []}
QUEUES = {
    "celery@worker-a": [{"name": "analysis"}, {"name": "celery"}],
    "celery@worker-b": [{"name": "manager"}],
}


class FakeInspect:
    def __init__(self, stats=STATS, active=ACTIVE, reserved=RESERVED, queues=QUEUES,
                 error=None):
        self._stats = stats
        self._active = active
        self._reserved = reserved
        self._queues = queues
        self._error = error

    def stats(self):
        if self._error is not None:
            raise self._error
        return self._stats

    def active(self):
        return self._active

    def reserved(self):
        return self._reserved

    def active_queues(self):
        return self._queues


@pytest.fixture(autouse=True)
def clear_worker_cache():
    cache.delete(celery_inspect.CACHE_KEY)
    yield
    cache.delete(celery_inspect.CACHE_KEY)


@pytest.fixture
def fake_workers(monkeypatch):
    def _install(inspect):
        monkeypatch.setattr(
            celery_inspect.app.control, "inspect", lambda *a, **kw: inspect
        )
        return inspect

    return _install


@pytest.mark.django_db
def test_requires_staff(api_client, user_alice, user_staff, fake_workers):
    fake_workers(FakeInspect())
    url = reverse("staff:worker")

    assert api_client.get(url).status_code == 403

    api_client.force_authenticate(user_alice)
    assert api_client.get(url).status_code == 403

    api_client.force_authenticate(user_staff)
    assert api_client.get(url).status_code == 200


@pytest.mark.django_db
def test_reports_workers_and_capacity(api_client, user_staff, fake_workers):
    fake_workers(FakeInspect())
    api_client.force_authenticate(user_staff)

    data = api_client.get(reverse("staff:worker")).data

    assert data["available"] is True
    assert data["num_workers"] == 2
    # 4 prefork slots plus 1 for the solo pool, which reports no
    # max-concurrency of its own.
    assert data["total_concurrency"] == 5
    assert data["active_tasks"] == 2
    assert data["reserved_tasks"] == 1
    assert data["free_slots"] == 3
    assert data["queues"] == ["analysis", "celery", "manager"]

    worker_a, worker_b = data["workers"]
    assert worker_a["nodename"] == "celery@worker-a"
    # The machine the worker runs on.
    assert worker_a["hostname"] == "worker-a"
    assert worker_a["concurrency"] == 4
    assert worker_a["pool"] == "prefork"
    assert worker_a["pid"] == 101
    assert worker_a["processed"] == 12
    assert worker_a["queues"] == ["analysis", "celery"]
    assert worker_a["active_tasks"] == 2

    assert worker_b["hostname"] == "worker-b"
    assert worker_b["concurrency"] == 1
    assert worker_b["processed"] == 0


@pytest.mark.django_db
def test_no_workers_running(api_client, user_staff, fake_workers):
    fake_workers(FakeInspect(stats=None))
    api_client.force_authenticate(user_staff)

    response = api_client.get(reverse("staff:worker"))

    # Still a 200: "no workers" is a state to display, not a server error.
    assert response.status_code == 200
    assert response.data["available"] is False
    assert response.data["num_workers"] == 0
    assert response.data["total_concurrency"] == 0
    assert "No Celery worker replied" in response.data["reason"]


@pytest.mark.django_db
def test_broker_unreachable(api_client, user_staff, fake_workers):
    fake_workers(FakeInspect(error=OSError("Connection refused")))
    api_client.force_authenticate(user_staff)

    response = api_client.get(reverse("staff:worker"))

    assert response.status_code == 200
    assert response.data["available"] is False
    assert "Connection refused" in response.data["reason"]
    assert response.data["workers"] == []


@pytest.mark.django_db
def test_result_is_cached(api_client, user_staff, fake_workers, monkeypatch):
    calls = []

    def counting_inspect(*args, **kwargs):
        calls.append(1)
        return FakeInspect()

    monkeypatch.setattr(celery_inspect.app.control, "inspect", counting_inspect)
    api_client.force_authenticate(user_staff)
    url = reverse("staff:worker")

    api_client.get(url)
    api_client.get(url)
    api_client.get(url)
    assert len(calls) == 1, "polling the dashboard must not hammer the broker"

    # ...but an explicit refresh bypasses the cache.
    api_client.get(url, {"refresh": "1"})
    assert len(calls) == 2
