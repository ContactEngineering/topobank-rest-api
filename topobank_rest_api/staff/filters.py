import uuid

from django.db.models import F, Q
from rest_framework import filters


class NullsLastOrderingFilter(filters.OrderingFilter):
    """
    Ordering filter that always sorts NULLs last.

    PostgreSQL defaults to NULLS FIRST on descending sorts, which would put
    every user who has never logged in at the top of a ``-last_login`` sort —
    the opposite of what the column is being sorted for.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset

        terms = []
        for field in ordering:
            if field.startswith("-"):
                terms.append(F(field[1:]).desc(nulls_last=True))
            else:
                terms.append(F(field).asc(nulls_last=True))
        return queryset.order_by(*terms)


class TaskSearchFilter(filters.SearchFilter):
    """
    Search filter that also matches Celery task IDs.

    ``task_id`` is a ``UUIDField``, so it cannot take part in the ``icontains``
    lookups the base class generates. When the search term parses as a UUID it
    is instead matched exactly against the task and launcher IDs, which is how
    an operator arriving from a log line or from Flower will search.
    """

    def filter_queryset(self, request, queryset, view):
        term = request.query_params.get(self.search_param, "").strip()
        if term:
            try:
                task_uuid = uuid.UUID(term)
            except ValueError:
                pass
            else:
                return queryset.filter(
                    Q(task_id=task_uuid) | Q(launcher_task_id=task_uuid)
                )
        return super().filter_queryset(request, queryset, view)
