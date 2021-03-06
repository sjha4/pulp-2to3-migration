import json
import socket
import unittest

from pulpcore.client.pulpcore import (
    ApiClient as CoreApiClient,
    Configuration,
    TasksApi
)
from pulpcore.client.pulp_file import (
    ApiClient as FileApiClient,
    ContentFilesApi,
    RepositoriesFileApi,
    RepositoriesFileVersionsApi
)
from pulpcore.client.pulp_2to3_migration import (
    ApiClient as MigrationApiClient,
    MigrationPlansApi
)
from pulp_2to3_migration.pulp2.base import (
    Repository as Pulp2Repository,
    RepositoryContentUnit
)
from pulp_2to3_migration.pulp2.connection import initialize
from pulp_2to3_migration.tests.functional.util import monitor_task


# Can't import ISO model due to PLUGIN_MIGRATORS needing Django app
# from pulp_2to3_migration.app.plugin.iso.pulp2_models import ISO


# Initialize MongoDB connection
initialize()


PULP_2_ISO_REPOSITORIES = [
    repo for repo in Pulp2Repository.objects.all()
    if repo.notes.get('_repo-type')[:-5] == 'iso'
]

PULP_2_ISO_FIXTURE_DATA = {
    # {'file': 3, ...}
    repo.repo_id: RepositoryContentUnit.objects.filter(repo_id=repo.repo_id).count()
    for repo in PULP_2_ISO_REPOSITORIES
}

EMPTY_ISO_MIGRATION_PLAN = json.dumps({"plugins": [{"type": "iso"}]})

SPECIFIC_REPOS_MIGRATION_PLAN = json.dumps({
    "plugins": [{
        "type": "iso",
        "repositories": [
            {
                "name": "file",
                "pulp2_importer_repository_id": "file",
                "repository_versions": [
                    {
                        "pulp2_repository_id": "file",
                        "pulp2_distributor_repository_ids": ["file"]
                    }
                ]
            },
            {
                "name": "file2",
                "pulp2_importer_repository_id": "file2",
                "repository_versions": [
                    {
                        "pulp2_repository_id": "file2",
                        "pulp2_distributor_repository_ids": ["file2"]
                    }
                ]
            },
        ]
    }]
})
DIFFERENT_IMPORTER_MIGRATION_PLAN = json.dumps({
    "plugins": [{
        "type": "iso",
        "repositories": [
            {
                "name": "file",
                "pulp2_importer_repository_id": "file2",
                "repository_versions": [
                    {
                        "pulp2_repository_id": "file",
                        "pulp2_distributor_repository_ids": ["file"]
                    }
                ]
            },
            {
                "name": "file2",
                "pulp2_importer_repository_id": "file2",
                "repository_versions": [
                    {
                        "pulp2_repository_id": "file2",
                        "pulp2_distributor_repository_ids": ["file2"]
                    }
                ]
            },
        ]
    }]
})


# TODO:
#   - Clear DB after each test
#   - Check that distributions are created properly
#   - Check that remotes are created properly

class TestMigrationPlan(unittest.TestCase):
    """Test the APIs for creating a Migration Plan."""

    @classmethod
    def setUpClass(cls):
        """
        Create all the client instances needed to communicate with Pulp.
        """
        configuration = Configuration()
        configuration.username = 'admin'
        configuration.password = 'password'
        configuration.host = 'http://{}:24817'.format(socket.gethostname())
        configuration.safe_chars_for_path_param = '/'

        core_client = CoreApiClient(configuration)
        file_client = FileApiClient(configuration)
        migration_client = MigrationApiClient(configuration)

        # Create api clients for all resource types
        cls.file_repo_api = RepositoriesFileApi(file_client)
        cls.file_repo_versions_api = RepositoriesFileVersionsApi(file_client)
        cls.file_content_api = ContentFilesApi(file_client)
        cls.tasks_api = TasksApi(core_client)
        cls.migration_plans_api = MigrationPlansApi(migration_client)

    def _do_test(self, repos, migration_plan):
        mp = self.migration_plans_api.create({'plan': migration_plan})
        mp_run_response = self.migration_plans_api.run(mp.pulp_href, data={})
        task = monitor_task(self.tasks_api, mp_run_response.task)
        self.assertEqual(task.state, "completed")
        for repo_id in repos:
            pulp3repos = self.file_repo_api.list(name=repo_id)
            # Assert that there is a result
            self.failIf(not pulp3repos.results,
                        "Missing a Pulp 3 repository for Pulp 2 "
                        "repository id '{}'".format(repo_id))
            repo_href = pulp3repos.results[0].pulp_href
            # Assert that the name in pulp 3 matches the repo_id in pulp 2
            self.assertEqual(repo_id, pulp3repos.results[0].name)
            # Assert that there is a Repository Version with the same number of content units as
            # associated with the repository in Pulp 2.
            repo_version_href = self.file_repo_versions_api.list(repo_href).results[0].pulp_href
            repo_version_content = self.file_content_api.list(repository_version=repo_version_href)
            self.assertEqual(PULP_2_ISO_FIXTURE_DATA[repo_id], repo_version_content.count)
        # TODO: count only not_in_plan=False repositories from ../pulp2repositories/ endpoint
        self.assertEqual(len(repos), self.file_repo_api.list().count)

    def test_1_migrate_specific_iso_repositories(self):
        """Test that a Migration Plan with repos specified migrates only those repos."""
        repos = list(PULP_2_ISO_FIXTURE_DATA.keys())[:2]
        self._do_test(repos, SPECIFIC_REPOS_MIGRATION_PLAN)

    def test_2_migrate_all_iso_repositories(self):
        """Test that a Migration Plan to mirror Pulp 2 executes correctly."""
        repos = list(PULP_2_ISO_FIXTURE_DATA.keys())
        self._do_test(repos, EMPTY_ISO_MIGRATION_PLAN)

    def test_3_migrate_iso_repositories_with_different_importer(self):
        """Test that a Migration Plan with different importers executes correctly."""
        repos = list(PULP_2_ISO_FIXTURE_DATA.keys())
        self._do_test(repos, DIFFERENT_IMPORTER_MIGRATION_PLAN)
