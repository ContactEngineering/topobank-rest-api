# Changelog for plugin *topobank-rest-api*

## 1.3.0 (2026-08-04)

- ENH: The v1 topography list selects and prefetches every relation its
  serializer touches, so listing the measurements of a dataset costs a
  handful of queries instead of ~10 per measurement

## 1.2.0 (2026-08-04)

- ENH: The v2 surface list embeds a lightweight summary of each measurement
  (id, name, task state, thumbnail URL), so a dataset list renders from one
  response instead of one request per row
- ENH: The v2 surface endpoint supports the dataset-list filters that so far
  only v1 had: full-text `search`, `sharing_status`, `author` chips (ANDed),
  `latest_versions` (collapse published versions to the latest) and ordering
  by name. The filter implementations are shared with v1
- ENH: The v2 surface list computes permissions once per unique permission set
  per request, as the topography list already did
- ENH: The v2 surface serializer reports `sharing_status` (own/shared/published)
- API: Retrieving a v2 topography no longer dispatches the inspection task from
  inside serialization — a list GET used to open a transaction and dispatch a
  Celery task per never-inspected row. Inspection now starts only on a detail
  retrieve
- BUG: Creating a dataset through v2 names it "Digital surface twin #<id>" when
  no name is given, like v1 does

## 1.1.0 (2026-08-03)

- API: Removed the `set-name` and `set-result-permissions` endpoints. Neither was
  reachable from any client, and neither was authorized: `set-name` let any logged-in
  user rename an arbitrary result and detach it from its subject, and
  `set-result-permissions` granted and revoked access to a result while checking only
  for `view` permission, so a read-only recipient could re-share it. A result is named
  by a normal field update and its permissions are set through the authorization API
- API: `GET /analysis/api/memory-usage/` is restricted to staff. It reports on every
  analysis in the instance, including analyses of datasets the caller cannot see, and
  was readable without authentication
- ENH: Measurement serializers report `undefined_data_fraction`
- ENH: Measurement serializers report `detrend_parameters`, the trend that
  detrending subtracted
- ENH: The dataset list shows only the latest published version of a dataset, so a
  search no longer returns the same dataset once per version
- ENH: Analysis plots are labelled in a unit that suits the data rather than in the
  unit of the first result, so an axis no longer reads `1.000e-4 mm`. Both axes are
  rewritten over one base length unit, keeping a density consistent with its
  abscissa
- PERF: The card endpoint reads the metadata of the first analysis rather than its
  full result. Both are one read of `result.json`, but the latter also fetched every
  data series of that analysis as a separate object, none of which is needed to
  learn its units and labels
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
