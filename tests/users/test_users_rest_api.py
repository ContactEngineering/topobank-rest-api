import pytest
from rest_framework.reverse import reverse
from topobank.manager.custodian import periodic_cleanup
from topobank.manager.models import Topography
from allauth.socialaccount.models import SocialAccount
from topobank.testing.factories import OrganizationFactory, SurfaceFactory, UserFactory
from topobank.testing.mock_auth.users.models import User

from topobank.authorization import get_anonymous_user

from topobank_rest_api.utils import get_api_url


@pytest.mark.django_db
def test_create_user(api_client, user_alice, user_staff):
    user_dict = {
        "username": "frank",
        "name": "Frank Smith",
    }

    # Create user as anonymous user should fail
    response = api_client.post(
        reverse("users:user-v1-list"), data=user_dict, format="json"
    )
    assert response.status_code == 403, response.content

    assert User.objects.count() == 3  # Anonymous, alice, staff

    # Create as user alice should also fail
    api_client.force_authenticate(user_alice)
    response = api_client.post(
        reverse("users:user-v1-list"), data=user_dict, format="json"
    )
    assert response.status_code == 403, response.content

    assert User.objects.count() == 3  # Anonymous, alice, staff

    # Create as staff user should succeed
    api_client.force_authenticate(user_staff)
    response = api_client.post(
        reverse("users:user-v1-list"), data=user_dict, format="json"
    )
    assert response.status_code == 201, response.content

    assert User.objects.count() == 4  # Anonymous, alice, staff, frank

    # Create user with same name should fail
    response = api_client.post(
        reverse("users:user-v1-list"), data=user_dict, format="json"
    )
    assert response.status_code == 400, response.content

    assert User.objects.count() == 4  # Anonymous, alice, staff, frank

    # Create user without name should fail
    del user_dict["name"]
    response = api_client.post(
        reverse("users:user-v1-list"), data=user_dict, format="json"
    )
    assert response.status_code == 400, response.content

    assert User.objects.count() == 4  # Anonymous, alice, staff, frank


@pytest.mark.django_db
def test_search_user(api_client, user_alice, user_bob, user_staff):
    # Searching for a user as the anonymous user should not be allowed
    response = api_client.get(f'{reverse("users:user-v1-list")}?name=bob')
    assert response.status_code == 403, response.content

    # Searching for a user when logged in should yield nothing if the users
    # are not in the same organization
    api_client.force_authenticate(user_alice)
    response = api_client.get(f'{reverse("users:user-v1-list")}?name=bob')
    assert response.status_code == 200, response.content
    assert len(response.data) == 0

    # Create an organization and enroll alice and bob
    org = OrganizationFactory()
    org.add(user_alice)
    org.add(user_bob)

    # Now alice can find bob
    response = api_client.get(f'{reverse("users:user-v1-list")}?name=bob')
    assert response.status_code == 200, response.content
    assert len(response.data) == 1
    user = response.data[0]
    assert user["name"] == user_bob.name
    assert user["username"] == user_bob.username
    assert user["id"] == user_bob.id
    assert user["url"] == get_api_url(user_bob, response.wsgi_request)


def _search(api_client, term):
    response = api_client.get(reverse("users:user-v1-list"), {"name": term})
    assert response.status_code == 200, response.content
    return {user["id"] for user in response.data}


def _detail_status(api_client, user):
    return api_client.get(
        reverse("users:user-v1-detail", kwargs={"pk": user.id})
    ).status_code


@pytest.mark.django_db
def test_users_sharing_a_dataset_see_each_other(api_client, user_alice, user_bob):
    # Regression test for topobank#1413: the permissions panel loads every user
    # who has access to a dataset, which returned 404 for everyone but oneself
    user_carol = UserFactory(username="carol", name="Carol Danvers")
    surface = SurfaceFactory(created_by=user_alice)

    api_client.force_authenticate(user_alice)
    assert _detail_status(api_client, user_bob) == 404

    surface.grant_permission(user_bob, "view")

    # Alice and bob now see each other ...
    assert _detail_status(api_client, user_bob) == 200
    assert _search(api_client, "bob") == {user_bob.id}
    api_client.force_authenticate(user_bob)
    assert _detail_status(api_client, user_alice) == 200

    # ... but carol, who shares nothing with them, still sees neither, and
    # neither of them sees carol
    api_client.force_authenticate(user_carol)
    assert _detail_status(api_client, user_alice) == 404
    assert _detail_status(api_client, user_bob) == 404
    api_client.force_authenticate(user_alice)
    assert _detail_status(api_client, user_carol) == 404

    # Revoking access hides bob again
    surface.revoke_permission(user_bob)
    assert _detail_status(api_client, user_alice) == 200  # oneself
    assert _detail_status(api_client, user_bob) == 404


@pytest.mark.django_db
def test_search_finds_unrelated_user_by_exact_name(api_client, user_alice, user_bob):
    # Regression test for topobank#1425: a user could not find anyone to share
    # a dataset with
    api_client.force_authenticate(user_alice)

    # A substring does not reveal users alice does not work with ...
    assert _search(api_client, "bob") == set()
    assert _search(api_client, "Bob Mar") == set()
    # ... but the exact full name does, regardless of case and whitespace
    assert _search(api_client, "Bob Marley") == {user_bob.id}
    assert _search(api_client, "  bob marley ") == {user_bob.id}
    # Finding bob does not make his details visible yet
    assert _detail_status(api_client, user_bob) == 404


@pytest.mark.django_db
def test_search_finds_unrelated_user_by_orcid(api_client, user_alice, user_bob):
    user_carol = UserFactory(username="carol", name="Carol Danvers")
    # bob has the ORCID iD stored on the user model (as the mock user does)...
    user_bob.orcid_id = "0000-0002-1825-009X"
    user_bob.save()
    # ...carol only through her ORCID social account (as the ce-ui user does)
    SocialAccount.objects.create(
        user=user_carol, provider="orcid", uid="0000-0001-5109-3700"
    )

    api_client.force_authenticate(user_alice)
    assert _search(api_client, "0000-0002-1825-009X") == {user_bob.id}
    assert _search(api_client, "0000-0002-1825-009x") == {user_bob.id}
    assert _search(api_client, "https://orcid.org/0000-0002-1825-009X") == {
        user_bob.id
    }
    assert _search(api_client, "0000-0001-5109-3700") == {user_carol.id}
    # Partial ORCID iDs do not match
    assert _search(api_client, "0000-0002") == set()


@pytest.mark.django_db
def test_search_never_returns_anonymous_user(api_client, user_alice):
    anonymous = get_anonymous_user()
    anonymous.name = "Anonymous"
    anonymous.save()
    api_client.force_authenticate(user_alice)
    assert _search(api_client, "Anonymous") == set()
    # An empty search lists only the users alice may see: herself
    assert _search(api_client, "") == {user_alice.id}


@pytest.mark.django_db
def test_patch_user(api_client, user_alice, user_bob, user_staff):
    # Changing user information as the anonymous user should fail
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_alice.id}),
        data={"email": "alice@example.com"},
        format="json",
    )
    assert response.status_code == 403, response.content

    # Changing bob as user alice should fail with a 404 because alice cannot
    # see bob
    api_client.force_authenticate(user_alice)
    response = api_client.get(
        reverse("users:user-v1-detail", kwargs={"pk": user_bob.id})
    )
    assert response.status_code == 404, response.content
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_bob.id}),
        data={"email": "bob@example.com"},
        format="json",
    )
    assert response.status_code == 404, response.content

    # We now add bob and alice to the same organization
    org = OrganizationFactory()
    org.add(user_alice)
    org.add(user_bob)

    # Changing bob as user alice should now fail with a 403 because alice
    # can see but not edit bob
    api_client.force_authenticate(user_alice)
    response = api_client.get(
        reverse("users:user-v1-detail", kwargs={"pk": user_bob.id})
    )
    assert response.status_code == 200, response.content
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_bob.id}),
        data={"email": "bob@example.com"},
        format="json",
    )
    assert response.status_code == 403, response.content

    # But changing alice as user alice should work
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_alice.id}),
        data={"email": "alice@example.com"},
        format="json",
    )
    assert response.status_code == 200, response.content

    # Staff user can change all users
    api_client.force_authenticate(user_staff)
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_alice.id}),
        data={"email": "alice@staff.com"},
        format="json",
    )
    assert response.status_code == 200, response.content
    response = api_client.patch(
        reverse("users:user-v1-detail", kwargs={"pk": user_bob.id}),
        data={"email": "bob@staff.com"},
        format="json",
    )
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_delete_user(api_client, one_line_scan, user_alice, user_staff):
    user_line_scan = one_line_scan.created_by
    org = OrganizationFactory()
    one_line_scan.surface.owned_by = org
    one_line_scan.surface.save(update_fields=["owned_by"])

    # Deleting a user information as the anonymous user should fail
    response = api_client.delete(
        reverse("users:user-v1-detail", kwargs={"pk": user_alice.id})
    )
    assert response.status_code == 403, response.content

    # We now add bob and alice to the same organization
    org.add(user_alice)
    org.add(user_line_scan)

    # Deleting bob as user alice should fail because alice cannot delete
    # or edit bob
    api_client.force_authenticate(user_alice)
    response = api_client.delete(
        reverse("users:user-v1-detail", kwargs={"pk": user_line_scan.id})
    )
    assert response.status_code == 403, response.content

    # Staff user can delete user
    api_client.force_authenticate(user_staff)
    response = api_client.delete(
        reverse("users:user-v1-detail", kwargs={"pk": user_line_scan.id})
    )
    assert response.status_code == 204, response.content

    # This should succeed, line scan still exists
    topo = Topography.objects.get(id=one_line_scan.id)
    assert topo.surface.created_by is None

    # Run custodian
    periodic_cleanup()

    # This should succeed, line scan still exists because it has an owner
    topo = Topography.objects.get(id=one_line_scan.id)
    assert topo.surface.created_by is None

    # Remove owner and run custodian
    topo.surface.owned_by = None
    topo.surface.save(update_fields=["owned_by"])
    periodic_cleanup()

    # Line scan should have been deleted
    with pytest.raises(Topography.DoesNotExist):
        Topography.objects.get(id=one_line_scan.id)


@pytest.mark.django_db
def test_user_response_includes_is_staff(api_client, user_alice, user_staff):
    # A regular user's own detail should include is_staff=False
    api_client.force_authenticate(user_alice)
    response = api_client.get(
        reverse("users:user-v1-detail", kwargs={"pk": user_alice.id})
    )
    assert response.status_code == 200, response.content
    assert "is_staff" in response.data
    assert response.data["is_staff"] is False

    # A staff user's own detail should include is_staff=True
    api_client.force_authenticate(user_staff)
    response = api_client.get(
        reverse("users:user-v1-detail", kwargs={"pk": user_staff.id})
    )
    assert response.status_code == 200, response.content
    assert "is_staff" in response.data
    assert response.data["is_staff"] is True
