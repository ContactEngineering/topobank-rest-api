# Changelog for plugin *topobank-rest-api*

## Unreleased

- ENH: The dataset list shows only the latest published version of a dataset, so a
  search no longer returns the same dataset once per version
- BUG: Task dashboard falls back to the username when a user's name is blank

## 1.0.0 (2026-07-31)

Initial release. This package contains the Django REST Framework
implementation that was previously part of `topobank` and `ce-ui`.

- ENH: Search end points
- ENH: End points for the user and tasks dashboard
- ENH: Asynchronous ZIP download
- ENH: Workflow descriptions are exposed through the API
- BUG: `force_inspect` re-dispatches in-flight tasks (`force=True`)
- BUG: Expose the workflow `visualization_type` so analysis cards render
- BUG: Added `is_staff` to the user serializer
- BUG: Fixed the OpenAPI schema of the `allow` field to use enum values and
  updated the schema for `/entry-points/`
- MAINT: All remaining DRF functionality (serializers, filters, pagination, view
  permissions, upload instructions) moved here from `topobank`
- MAINT: Removed organization management and the REST surfaces for
  organization-based sharing
- MAINT: Removed django-guardian and workflow permission checks
- MAINT: `analysis_function` -> `workflow`, `Folder` -> `ManifestSet`, removal of
  `subject_dispatch`
- BUILD: Build system is hatchling; added django-termsandconditions
