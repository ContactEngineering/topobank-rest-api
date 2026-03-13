#
# Common settings and fixtures used with pytest
#

import pytest
import topobank.testing.fixtures  # noqa: F401, F403
import topobank.testing.workflows  # noqa: F401
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from topobank.testing.fixtures import *  # noqa: F401, F403
from topobank.users.models import User


@receiver(post_save, sender=User)
def add_to_default_group(sender, instance, created, **kwargs):
    if created:
        from topobank.organizations.models import DEFAULT_GROUP_NAME
        group, _ = Group.objects.get_or_create(name=DEFAULT_GROUP_NAME)
        instance.groups.add(group)


@pytest.fixture(scope="session", autouse=True)
def register_testing_workflows(django_db_setup, django_db_blocker):
    from django.core.management import call_command
    from topobank.analysis.registry import register_implementation
    from topobank.testing.workflows import (
        SecondTestImplementation,
        TestImplementation,
        TestImplementationWithError,
        TestImplementationWithErrorInDependency,
        TestImplementationWithOutputs,
        TopographyOnlyTestImplementation,
    )
    register_implementation(TestImplementation)
    register_implementation(TopographyOnlyTestImplementation)
    register_implementation(SecondTestImplementation)
    register_implementation(TestImplementationWithError)
    register_implementation(TestImplementationWithErrorInDependency)
    register_implementation(TestImplementationWithOutputs)

    with django_db_blocker.unblock():
        call_command("register_analysis_functions")
