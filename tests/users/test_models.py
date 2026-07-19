import pytest
from topobank.testing.factories import UserFactory

from topobank_rest_api.utils import get_api_url


@pytest.mark.django_db
def test_absolute_url():
    user = UserFactory(username="testuser")
    assert get_api_url(user) == f"/users/v1/user/{user.id}/"
