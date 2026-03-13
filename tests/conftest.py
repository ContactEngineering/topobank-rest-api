#
# Common settings and fixtures used with pytest
#

import topobank.testing.fixtures  # noqa: F401, F403
import topobank.testing.workflows  # noqa: F401
import topobank_publication.urls  # noqa: F401
from topobank.testing.fixtures import *  # noqa: F401, F403

@pytest.fixture(scope="session", autouse=True)
def register_testing_workflows(django_db_setup, django_db_blocker):
    from django.core.management import call_command
    from topobank.analysis.registry import register_implementation
    from topobank.testing.workflows import (
        TestImplementation,
        TopographyOnlyTestImplementation,
        SecondTestImplementation,
        TestImplementationWithError,
        TestImplementationWithErrorInDependency,
        TestImplementationWithOutputs
    )
    register_implementation(TestImplementation)
    register_implementation(TopographyOnlyTestImplementation)
    register_implementation(SecondTestImplementation)
    register_implementation(TestImplementationWithError)
    register_implementation(TestImplementationWithErrorInDependency)
    register_implementation(TestImplementationWithOutputs)

    with django_db_blocker.unblock():
        call_command("register_analysis_functions")
