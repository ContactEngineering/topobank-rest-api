"""
Tests for the version-collapsing filter without the publication plugin.

The dataset list shows only the latest published version of a dataset
(ContactEngineering/ce-ui#38). Versions exist only where the publication plugin is
installed, which it is not in this test configuration, so what can be checked
here is that the filter stays out of the way — the collapsing itself is covered in
`topobank-publication`, whose test settings install the app.
"""

import pytest
from topobank.manager.models import Surface
from topobank.testing.factories import SurfaceFactory

from topobank_rest_api.manager.filters import filter_to_latest_version


@pytest.mark.django_db
def test_filter_is_inert_without_the_publication_plugin(rf):
    assert not hasattr(Surface, "publication"), (
        "this test asserts the behaviour without the plugin, but it is installed"
    )
    SurfaceFactory(name="One")
    SurfaceFactory(name="Two")

    queryset = Surface.objects.all()
    filtered = filter_to_latest_version(rf.get("/"), queryset)

    assert list(filtered.order_by("name").values_list("name", flat=True)) == [
        "One",
        "Two",
    ]
