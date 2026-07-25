"""
Live Celery worker introspection for the task dashboard.

``app.control.inspect()`` is a broadcast RPC over the broker, not a local
call: it costs a round trip, it blocks for up to the configured timeout, and
it fails in whatever way the broker transport happens to fail. The dashboard
polls it, so everything here is short-timeout, cached, and non-raising.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from topobank.taskapp.celeryapp import app

_log = logging.getLogger(__name__)

CACHE_KEY = "staff-dashboard-celery-workers"

#: Short enough that the dashboard shows near-live numbers, long enough that
#: several staff users polling at once do not multiply broker round trips.
CACHE_SECONDS = 5

#: Seconds to wait for workers to reply to the broadcast.
DEFAULT_TIMEOUT = 1.5


def _unavailable(reason):
    return {
        "available": False,
        "reason": reason,
        "workers": [],
        "num_workers": 0,
        "total_concurrency": 0,
        "active_tasks": 0,
        "reserved_tasks": 0,
        "free_slots": 0,
        "queues": [],
    }


def _worker_info(nodename, worker_stats, active, reserved, queues):
    pool = worker_stats.get("pool") or {}

    # Celery node names are "<name>@<hostname>"; the host part is the machine
    # the worker runs on (socket.gethostname(), unless started with -n).
    hostname = nodename.split("@", 1)[1] if "@" in nodename else nodename

    # Most pools report max-concurrency; the solo pool and some alternative
    # pools do not, in which case the process list (or a single slot) is the
    # best available answer.
    concurrency = pool.get("max-concurrency")
    if not concurrency:
        concurrency = len(pool.get("processes") or []) or 1

    return {
        "nodename": nodename,
        "hostname": hostname,
        "concurrency": concurrency,
        "min_concurrency": pool.get("min-concurrency"),
        "pool": pool.get("implementation"),
        "pid": worker_stats.get("pid"),
        "uptime": worker_stats.get("uptime"),
        "processed": sum((worker_stats.get("total") or {}).values()),
        "software": worker_stats.get("sw_ver"),
        "queues": sorted(q.get("name") for q in (queues.get(nodename) or []) if q.get("name")),
        "active_tasks": len(active.get(nodename) or []),
        "reserved_tasks": len(reserved.get(nodename) or []),
    }


def _inspect(timeout):
    try:
        inspect = app.control.inspect(timeout=timeout)
        stats = inspect.stats()
        if not stats:
            return _unavailable(
                "No Celery worker replied within "
                f"{timeout} s. Either no worker is running or the broker is "
                "unreachable."
            )
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        queues = inspect.active_queues() or {}
    except Exception as exc:
        # Deliberately broad: a broker outage surfaces as any of a dozen
        # kombu/redis/socket exception types, and the dashboard must degrade
        # to "workers unknown" rather than return a 500.
        _log.warning("Could not inspect Celery workers: %s", exc)
        return _unavailable(f"Could not reach the Celery broker: {exc}")

    workers = [
        _worker_info(nodename, worker_stats, active, reserved, queues)
        for nodename, worker_stats in sorted(stats.items())
    ]

    total_concurrency = sum(w["concurrency"] for w in workers)
    active_tasks = sum(w["active_tasks"] for w in workers)

    return {
        "available": True,
        "reason": None,
        "workers": workers,
        "num_workers": len(workers),
        # This is the answer to "how many tasks can in principle run in
        # parallel": the sum of every worker's pool size.
        "total_concurrency": total_concurrency,
        "active_tasks": active_tasks,
        "reserved_tasks": sum(w["reserved_tasks"] for w in workers),
        "free_slots": max(0, total_concurrency - active_tasks),
        "queues": sorted({q for w in workers for q in w["queues"]}),
    }


def get_worker_state(use_cache=True):
    """
    Return the current state of the Celery worker fleet.

    Never raises: on any failure the returned dict has ``available: False``
    and a human-readable ``reason``.
    """
    if use_cache:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return cached

    timeout = getattr(
        settings, "TOPOBANK_STAFF_CELERY_INSPECT_TIMEOUT", DEFAULT_TIMEOUT
    )
    state = _inspect(timeout)
    cache.set(CACHE_KEY, state, CACHE_SECONDS)
    return state
