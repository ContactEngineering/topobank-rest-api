"""Tests for the staff user dashboard endpoint."""

import datetime

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.reverse import reverse
from termsandconditions.models import TermsAndConditions, UserTermsAndConditions
from topobank.testing.factories import SurfaceFactory, Topography1DFactory, UserFactory

from topobank_rest_api.staff import queries


@pytest.fixture
def site_terms(db):
    """One active set of terms, plus a superseded older version."""
    TermsAndConditions.objects.create(
        slug="site-terms",
        name="Old terms",
        version_number="1.0",
        date_active=timezone.now() - datetime.timedelta(days=30),
    )
    active = TermsAndConditions.objects.create(
        slug="site-terms",
        name="Site terms",
        version_number="2.0",
        date_active=timezone.now() - datetime.timedelta(days=1),
    )
    # get_active_terms_ids() memoizes in the Django cache; make sure the test
    # sees the terms it just created.
    from django.core.cache import cache

    cache.clear()
    return active


def _rows(response):
    return {row["username"]: row for row in response.data["results"]}


@pytest.mark.django_db
def test_requires_staff(api_client, user_alice, user_staff):
    url = reverse("staff:user-list")

    # Anonymous
    assert api_client.get(url).status_code == 403

    # Ordinary user
    api_client.force_authenticate(user_alice)
    assert api_client.get(url).status_code == 403

    # Staff
    api_client.force_authenticate(user_staff)
    assert api_client.get(url).status_code == 200


@pytest.mark.django_db
def test_is_read_only(api_client, user_staff):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:user-list")
    assert api_client.post(url, data={}, format="json").status_code == 403
    assert api_client.delete(url).status_code == 403


@pytest.mark.django_db
def test_lists_all_users_and_excludes_anonymous(api_client, user_alice, user_bob,
                                                user_staff):
    api_client.force_authenticate(user_staff)
    response = api_client.get(reverse("staff:user-list"))
    assert response.status_code == 200

    usernames = set(_rows(response))
    # Alice and Bob share no groups with staff, but staff still sees them.
    assert {"alice", "bob", "staff"} <= usernames
    # The anonymous user is an implementation detail and must not show up.
    assert "AnonymousUser" not in usernames
    assert response.data["count"] == len(usernames)


@pytest.mark.django_db
def test_object_counts(api_client, user_alice, user_bob, user_staff):
    surface = SurfaceFactory(created_by=user_alice)
    other = SurfaceFactory(created_by=user_alice)
    Topography1DFactory(surface=surface, created_by=user_alice)
    Topography1DFactory(surface=surface, created_by=user_alice)
    # A measurement Bob added to a dataset Alice created counts for Bob, not
    # for Alice: the dashboard reports what each user created.
    Topography1DFactory(surface=surface, created_by=user_bob)

    # Soft-deleted objects must not be counted.
    other.delete()

    api_client.force_authenticate(user_staff)
    rows = _rows(api_client.get(reverse("staff:user-list")))

    assert rows["alice"]["num_surfaces"] == 1
    assert rows["alice"]["num_topographies"] == 2
    assert rows["bob"]["num_surfaces"] == 0
    assert rows["bob"]["num_topographies"] == 1
    assert rows["staff"]["num_surfaces"] == 0
    assert rows["staff"]["num_topographies"] == 0


@pytest.mark.django_db
def test_orcid_and_registration_columns(api_client, user_alice, user_staff):
    api_client.force_authenticate(user_staff)
    row = _rows(api_client.get(reverse("staff:user-list")))["alice"]

    assert row["name"] == "Alice Wonderland"
    assert row["orcid"] == user_alice.orcid_id
    assert row["date_joined"] is not None
    # Never logged in via the login form in this test.
    assert row["last_login"] is None


@pytest.mark.django_db
def test_orcid_annotation_reads_social_account(user_alice):
    """
    The production user model has no ``orcid_id`` column; the iD lives in the
    allauth social account. Exercise that expression directly, since the mock
    user model used by this test suite would otherwise shortcut to the field.
    """
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth import get_user_model

    account = SocialAccount.objects.get(user_id=user_alice.id, provider="orcid")

    annotated = queries.annotate_orcid_from_socialaccount(
        get_user_model().objects.filter(pk=user_alice.pk)
    ).first()

    assert annotated.orcid == account.extra_data["orcid-identifier"]["path"]
    assert annotated.orcid == account.uid


@pytest.mark.django_db
def test_terms_status(api_client, user_alice, user_bob, user_staff, site_terms):
    UserTermsAndConditions.objects.create(user=user_alice, terms=site_terms)

    api_client.force_authenticate(user_staff)
    rows = _rows(api_client.get(reverse("staff:user-list")))

    assert rows["alice"]["terms_status"] == queries.TERMS_ACCEPTED
    assert rows["alice"]["terms_accepted_on"] is not None
    assert rows["bob"]["terms_status"] == queries.TERMS_NOT_ACCEPTED
    assert rows["bob"]["terms_accepted_on"] is None


@pytest.mark.django_db
def test_terms_status_exempt(api_client, user_alice, user_staff, site_terms):
    user_alice.user_permissions.add(
        Permission.objects.get(codename="can_skip_terms")
    )

    api_client.force_authenticate(user_staff)
    rows = _rows(api_client.get(reverse("staff:user-list")))

    assert rows["alice"]["terms_status"] == queries.TERMS_EXEMPT


@pytest.mark.django_db
def test_terms_status_when_none_are_active(api_client, user_alice, user_staff):
    from django.core.cache import cache

    cache.clear()
    api_client.force_authenticate(user_staff)
    rows = _rows(api_client.get(reverse("staff:user-list")))
    assert rows["alice"]["terms_status"] == queries.TERMS_NOT_REQUIRED


@pytest.mark.django_db
def test_search(api_client, user_alice, user_bob, user_staff):
    api_client.force_authenticate(user_staff)
    url = reverse("staff:user-list")

    # By name
    rows = _rows(api_client.get(url, {"search": "Wonderland"}))
    assert set(rows) == {"alice"}

    # By username
    rows = _rows(api_client.get(url, {"search": "bob"}))
    assert set(rows) == {"bob"}

    # By email
    rows = _rows(api_client.get(url, {"search": user_bob.email}))
    assert set(rows) == {"bob"}

    # By ORCID iD (an annotated column)
    rows = _rows(api_client.get(url, {"search": user_alice.orcid_id}))
    assert "alice" in rows

    # No match
    assert api_client.get(url, {"search": "nobody-by-that-name"}).data["count"] == 0


@pytest.mark.django_db
def test_ordering(api_client, user_alice, user_bob, user_staff):
    surface = SurfaceFactory(created_by=user_bob)
    Topography1DFactory(surface=surface, created_by=user_bob)

    api_client.force_authenticate(user_staff)
    url = reverse("staff:user-list")

    response = api_client.get(url, {"ordering": "-num_topographies"})
    assert response.data["results"][0]["username"] == "bob"

    response = api_client.get(url, {"ordering": "name"})
    names = [row["name"] for row in response.data["results"]]
    assert names == sorted(names)


@pytest.mark.django_db
def test_ordering_puts_never_logged_in_last(api_client, user_alice, user_bob,
                                            user_staff):
    user_bob.last_login = timezone.now()
    user_bob.save(update_fields=["last_login"])

    api_client.force_authenticate(user_staff)
    response = api_client.get(
        reverse("staff:user-list"), {"ordering": "-last_login"}
    )
    results = response.data["results"]

    # Bob logged in, everybody else never did; PostgreSQL would sort NULLs
    # first on a descending sort without the custom ordering filter.
    assert results[0]["username"] == "bob"
    assert all(row["last_login"] is None for row in results[1:])


@pytest.mark.django_db
def test_pagination(api_client, user_staff):
    for i in range(7):
        UserFactory(username=f"paginated-{i}")

    api_client.force_authenticate(user_staff)
    url = reverse("staff:user-list")

    response = api_client.get(url, {"limit": 3})
    assert len(response.data["results"]) == 3
    assert response.data["count"] == 8  # 7 + staff
    assert response.data["next"] is not None

    response = api_client.get(url, {"limit": 3, "offset": 6})
    assert len(response.data["results"]) == 2


@pytest.mark.django_db
def test_query_count_is_independent_of_page_size(api_client, user_staff,
                                                 django_assert_num_queries,
                                                 site_terms):
    """
    The whole point of annotating instead of reading model properties: more
    users on the page must not mean more queries. Without the annotations,
    ORCID alone would add one query per row.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def make_users(prefix, count):
        for i in range(count):
            user = UserFactory(username=f"{prefix}-{i}")
            surface = SurfaceFactory(created_by=user)
            Topography1DFactory(surface=surface, created_by=user)

    make_users("small", 3)

    api_client.force_authenticate(user_staff)
    url = reverse("staff:user-list")

    # Warm up first: the very first request also populates the active-terms
    # cache and the connection's introspection state.
    assert api_client.get(url, {"limit": 2}).status_code == 200

    with CaptureQueriesContext(connection) as captured:
        assert api_client.get(url, {"limit": 2}).status_code == 200
    baseline = len(captured)

    make_users("large", 10)

    with django_assert_num_queries(baseline):
        response = api_client.get(url, {"limit": 100})
    assert response.status_code == 200
    assert len(response.data["results"]) == 14  # 13 created here + staff
